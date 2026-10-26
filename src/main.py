"""The FastAPI application: routes, access check, request ids, and one rule for failures outside
the agent's control.

Run: make run   (then open http://localhost:8000/docs)
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from src.api import pulse
from src.api.routes import public, router
from src.api.security import check_startup, require_access
from src.common.config import get_settings
from src.common.exceptions import FinSightError
from src.common.logging_config import setup_logging
from src.common.request_context import new_request_id, request_facts_var, request_id_var

logger = logging.getLogger(__name__)

# What the client sees when OpenAI or Snowflake cannot be reached. The real error goes to the log:
# driver messages can name the account, the user or internal hosts.
UNAVAILABLE = "The agent could not reach a service it needs (LLM or Snowflake). Try again later."
# Requests worth a row in CONTROL.REQUEST_LOG: the ones that use the LLM or write CONTROL.
LOGGED_PATHS = ("/ask", "/research", "/brief", "/watchlists")

# One background writer: a request log row never delays or fails the response it describes.
_log_writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="request-log")


async def service_unavailable(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Could not answer %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(status_code=503, content={"detail": UNAVAILABLE})


def write_request_log(row: dict[str, Any]) -> None:
    try:
        pulse.get_control().execute(
            """
INSERT INTO FINSIGHT.CONTROL.REQUEST_LOG
    (request_id, logged_at, endpoint, status, http_status, seconds, sql_count, input_tokens,
     output_tokens, cost_usd)
VALUES
    (%(request_id)s, CURRENT_TIMESTAMP(), %(endpoint)s, %(status)s, %(http_status)s, %(seconds)s,
     %(sql_count)s, %(input_tokens)s, %(output_tokens)s, %(cost_usd)s)
""",
            row,
        )
    except Exception as err:  # noqa: BLE001  (logging must never break anything)
        logger.warning("Request log row not written: %s", type(err).__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_format)
    check_startup(settings)  # deployed without a service key: refuse to start
    application = FastAPI(title="FinSight AI", version="0.2.0")
    application.include_router(public)

    @application.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        """The API has no page of its own: send a browser to its interactive docs."""

        return RedirectResponse("/docs")

    guarded = [Depends(require_access)]
    application.include_router(router, dependencies=guarded)
    application.include_router(pulse.router, dependencies=guarded)
    # A blocked or failed SQL is still an answer (200, see AskResponse.status). An LLM, Snowflake
    # or configuration error means no answer could be produced: 503.
    application.add_exception_handler(FinSightError, service_unavailable)

    @application.middleware("http")
    async def request_id(request: Request, call_next: Any) -> Any:
        rid = new_request_id(request.headers.get("x-request-id"))
        token, facts_token = request_id_var.set(rid), request_facts_var.set({})
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            facts = request_facts_var.get() or {}
            request_id_var.reset(token)
            request_facts_var.reset(facts_token)
        seconds = time.perf_counter() - started
        response.headers["X-Request-ID"] = rid
        path = request.url.path
        logger.info(
            "request id=%s %s %s -> %d in %.2fs",
            rid,
            request.method,
            path,
            response.status_code,
            seconds,
        )
        if (
            path.startswith(LOGGED_PATHS)
            and request.method != "GET"
            and settings.snowflake_app_user
        ):
            row = {"request_id": rid, "endpoint": f"{request.method} {path}",
                   "http_status": response.status_code, "seconds": round(seconds, 3),
                   "status": None, "sql_count": None, "input_tokens": None,
                   "output_tokens": None, "cost_usd": None, **facts}  # fmt: skip
            _log_writer.submit(write_request_log, row)
        return response

    return application


app = create_app()
