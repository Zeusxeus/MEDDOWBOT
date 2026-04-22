from __future__ import annotations

from typing import Optional
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.state import State, StatesGroup


class AdminAction(CallbackData, prefix="adm"):
    """Callback data for admin menu navigation."""
    action: str
    page: int = 1
    user_id: Optional[int] = None
    data: Optional[str] = None


class AdminStates(StatesGroup):
    """FSM states for admin operations."""
    waiting_for_broadcast = State()
    confirm_broadcast = State()
    waiting_for_proxy = State()
    waiting_for_cookie_platform = State()
    waiting_for_cookie_file = State()
    waiting_for_rate_limit = State()
