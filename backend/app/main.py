"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import alerts, proposals, regimes, risk, strategies, ws
from app.api import settings as settings_router
from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.logging import setup_logging


def create_app() -> FastAPI:
    setup_logging()
    settings = get_settings()
    app = FastAPI(title="Regime Trader API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(strategies.router)
    app.include_router(proposals.router)
    app.include_router(regimes.router)
    app.include_router(risk.router)
    app.include_router(settings_router.router)
    app.include_router(alerts.router)
    app.include_router(ws.router)
    return app


app = create_app()
