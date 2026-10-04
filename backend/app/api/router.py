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
from app.core.auth import get_current_user, verify_internal_proxy_token

api_router = APIRouter(prefix="/api")

# Liveness/readiness must stay reachable with no credential -- a hosting
# platform's health checks (and Render's own container HEALTHCHECK) never
# send an Authorization header. See app/core/auth.py.
api_router.include_router(health.router)

# Every other router requires a verified Supabase user (P0-3C) -- attached
# once here, not per-route, so no individual route can be added later and
# accidentally ship unauthenticated. `verify_internal_proxy_token` is the
# optional server-to-server signal from our own proxy; it is never identity.
# Routes that touch user-owned data additionally take `get_current_user` as
# a parameter and scope every query by `user.id`.
_protected = [Depends(verify_internal_proxy_token), Depends(get_current_user)]
api_router.include_router(assets.router, dependencies=_protected)
api_router.include_router(portfolio.router, dependencies=_protected)
api_router.include_router(strategy.router, dependencies=_protected)
api_router.include_router(strategy_admin.router, dependencies=_protected)
api_router.include_router(cash_flow.router, dependencies=_protected)
api_router.include_router(transactions.router, dependencies=_protected)
api_router.include_router(watchlist.router, dependencies=_protected)
api_router.include_router(alerts.router, dependencies=_protected)
api_router.include_router(prices.router, dependencies=_protected)
api_router.include_router(analytics.router, dependencies=_protected)
