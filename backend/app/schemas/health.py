from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    database: str


class ReadinessResponse(BaseModel):
    """On failure the route raises HTTPException(503) instead of returning
    this model — the body is then FastAPI's standard {"detail": "..."}."""

    status: str
