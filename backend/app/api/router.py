from fastapi import APIRouter

from app.api.routes import cash_flow, health, portfolio, strategy

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(portfolio.router)
api_router.include_router(strategy.router)
api_router.include_router(cash_flow.router)
