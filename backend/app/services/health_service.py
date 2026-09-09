from app.core.database import check_database_connection
from app.schemas.health import HealthResponse


async def get_health_status() -> HealthResponse:
    """Report application liveness plus an informational database connectivity flag.

    `status` reflects only that the application process is running and able to
    respond — it does not flip to an error state on a database hiccup, so
    hosting platforms can use this endpoint as a stable liveness probe.
    `database` is diagnostic: "connected" or "unavailable".
    """
    db_ok = await check_database_connection()
    return HealthResponse(status="ok", database="connected" if db_ok else "unavailable")
