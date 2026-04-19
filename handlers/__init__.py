from __future__ import annotations

from aiogram import Router

from .admin import router as admin_router
from .download import router as download_router
from .history import router as history_router
from .reddit import router as reddit_router
from .settings import router as settings_router

router = Router()

router.include_routers(
    admin_router,
    download_router,
    history_router,
    reddit_router,
    settings_router,
)
