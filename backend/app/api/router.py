from fastapi import APIRouter

from app.api.routes import alerts, cash_flow, health, portfolio, strategy, watchlist

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(portfolio.router)
api_router.include_router(strategy.router)
api_router.include_router(cash_flow.router)
api_router.include_router(watchlist.router)
api_router.include_router(alerts.router)
