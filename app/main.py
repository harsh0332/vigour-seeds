from fastapi import FastAPI
from app.api.health import router as health_router
from app.api.webhook import router as webhook_router
from app.services.metrics import router as metrics_router
from app.api.dashboard import router as dashboard_router
from app.core.logging import logger
from app.core.config import settings
from app.core.errors import handle_unhandled_error
from fastapi import Request

app = FastAPI(
    title="Vigour Seeds WhatsApp Agent Backend",
    description="Production WhatsApp Automation Agent for Vigour Seeds",
    version="1.0.0"
)

# Mount endpoints directly to match required paths: /health, /webhook, and /metrics
app.include_router(health_router)
app.include_router(webhook_router)
app.include_router(metrics_router)
app.include_router(dashboard_router)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled HTTP exception", exc_info=exc)
    await handle_unhandled_error(exc, None)
    return {"status": "error", "message": "An unexpected error occurred."}


@app.on_event("startup")
async def startup_event():
    logger.info(
        "Application startup initiated",
        extra={
            "env": settings.APP_ENV,
            "provider": settings.AI_PROVIDER
        }
    )

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Application shutdown initiated")
