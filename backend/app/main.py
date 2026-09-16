from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import api_router
from app.core.config import get_settings
from app.escalations.automation import lifespan

settings = get_settings()

app = FastAPI(
    title="SupportPilot API",
    description="Backend service for the SupportPilot AI portfolio project.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Accept", "Authorization", "Content-Type", "X-SupportPilot-Session"],
)

app.include_router(api_router, prefix="/api")
