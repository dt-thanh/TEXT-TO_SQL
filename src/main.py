"""Create the FastAPI application and register HTTP routes.

TODO: Add lifespan hooks for shared Snowflake and LLM resources.
"""

from fastapi import FastAPI

from src.api.routes import router


def create_app() -> FastAPI:
    """Build an application instance suitable for uvicorn and tests.

    TODO: Add middleware, structured logging, and exception handlers.
    """

    application = FastAPI(
        title="Text-to-SQL Agent on Snowflake",
        version="0.1.0",
    )
    application.include_router(router)
    return application


app = create_app()
