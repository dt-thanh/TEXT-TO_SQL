"""Expose health and question-answering endpoints.

TODO: Invoke the compiled LangGraph from the /ask endpoint.
"""

from fastapi import APIRouter

from src.models.schemas import AskRequest, AskResponse, HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Report that the API process is alive.

    TODO: Optionally add separate readiness checks for external dependencies.
    """

    return HealthResponse(status="ok")


@router.post("/ask", response_model=AskResponse)
async def ask(payload: AskRequest) -> AskResponse:
    """Accept a natural-language question and return a placeholder response.

    TODO: Pass the question into the agent graph and map final state to this model.
    """

    return AskResponse(
        question=payload.question,
        status="stub",
        answer="TODO: Connect this endpoint to the Text-to-SQL LangGraph.",
    )
