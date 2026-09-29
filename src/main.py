"""The FastAPI application: routes plus one rule for failures outside the agent's control.

Run: make run   (then open http://localhost:8000/docs)
"""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.api.routes import router
from src.common.config import get_settings
from src.common.exceptions import FinSightError
from src.common.logging_config import setup_logging

logger = logging.getLogger(__name__)

# What the client sees when OpenAI or Snowflake cannot be reached. The real error goes to the log:
# driver messages can name the account, the user or internal hosts.
UNAVAILABLE = "The agent could not reach a service it needs (LLM or Snowflake). Try again later."


async def service_unavailable(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Could not answer %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(status_code=503, content={"detail": UNAVAILABLE})


def create_app() -> FastAPI:
    setup_logging(get_settings().log_level)
    application = FastAPI(title="FinSight AI", version="0.1.0")
    application.include_router(router)
    # A blocked or failed SQL is still an answer (200, see AskResponse.status). An LLM, Snowflake
    # or configuration error means no answer could be produced: 503.
    application.add_exception_handler(FinSightError, service_unavailable)
    return application


app = create_app()
