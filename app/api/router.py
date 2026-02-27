from fastapi import APIRouter

from app.api.routes.auth import router as auth_router
from app.api.routes.chat import router as chat_router
from app.api.routes.docs import router as docs_router
from app.api.routes.exercises import router as exercises_router
from app.api.routes.health import router as health_router
from app.api.routes.user import router as user_router

api_router = APIRouter()
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(health_router, tags=["health"])
api_router.include_router(docs_router, tags=["docs"])
api_router.include_router(exercises_router, tags=["exercises"])
api_router.include_router(user_router, prefix="/user", tags=["user"])
api_router.include_router(chat_router, prefix="/chat", tags=["chat"])