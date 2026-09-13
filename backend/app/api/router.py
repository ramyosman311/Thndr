from fastapi import APIRouter, Depends

from app.api.routes import (
    alerts,
    analytics,
    assets,
    cash_flow,
    health,
    portfolio,
    prices,
    strategy,
    strategy_admin,
    transactions,
    watchlist,
)
from app.core.auth import require_api_token

api_router = APIRouter(prefix="/api")

# Liveness/readiness must stay reachable with no credential -- a hosting
# platform's health checks (and Render's own container HEALTHCHECK) never
# send an Authorization header. See app/core/auth.py.
api_router.include_router(health.router)

# Every other router requires API_AUTH_TOKEN (P0-2) -- attached once here,
# not per-route, so no individual route can be added later and accidentally
# ship unauthenticated.
_protected = Depends(require_api_token)
api_router.include_router(assets.router, dependencies=[_protected])
api_router.include_router(portfolio.router, dependencies=[_protected])
api_router.include_router(strategy.router, dependencies=[_protected])
api_router.include_router(strategy_admin.router, dependencies=[_protected])
api_router.include_router(cash_flow.router, dependencies=[_protected])
api_router.include_router(transactions.router, dependencies=[_protected])
api_router.include_router(watchlist.router, dependencies=[_protected])
api_router.include_router(alerts.router, dependencies=[_protected])
api_router.include_router(prices.router, dependencies=[_protected])
api_router.include_router(analytics.router, dependencies=[_protected])
