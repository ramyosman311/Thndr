from fastapi import APIRouter

from app.api.routes import health, portfolio, strategy

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(portfolio.router)
api_router.include_router(strategy.router)
