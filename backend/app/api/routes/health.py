from fastapi import APIRouter, HTTPException, status

from app.schemas.health import HealthResponse, ReadinessResponse
from app.services.health_service import get_health_status, is_ready

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness: is the process running and able to respond at all. Never
    fails on a database hiccup — see get_health_status's own docstring."""
    return await get_health_status()


@router.get("/health/ready", response_model=ReadinessResponse)
async def readiness() -> ReadinessResponse:
    """Readiness (Phase 23): required infrastructure (the database) is
    reachable, so this instance can actually serve requests. A hosting
    platform's load balancer/orchestrator should use this, not `/health`,
    to decide whether to route traffic to this instance."""
    if not await is_ready():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="database unavailable")
    return ReadinessResponse(status="ready")
