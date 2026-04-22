from __future__ import annotations

from .admin import router as admin_router
from .cancel import router as cancel_router
from .download import router as download_router
from .history import router as history_router
from .reddit import router as reddit_router
from .settings import router as settings_router
from .start import router as start_router

__all__ = [
    "admin_router",
    "cancel_router",
    "download_router",
    "history_router",
    "reddit_router",
    "settings_router",
    "start_router",
]
