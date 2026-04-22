from __future__ import annotations

import structlog
from aiogram import Router, types
from aiogram.filters import Command

from database import crud
from database.models import User
from database.session import get_db

log = structlog.get_logger(__name__)
router = Router(name="cancel")


@router.message(Command("cancel"))
async def cancel_command(message: types.Message, db_user: User) -> None:
    """
    Cancel the user's most recent active download job.
    """
    async with get_db() as session:
        active_job = await crud.get_active_job_by_user(session, db_user.id)
        if not active_job:
            await message.answer("❌ You don't have any active jobs to cancel.")
            return

        success = await crud.cancel_job(session, active_job.id)
        if success:
            log.info("job_cancelled_by_user", job_id=active_job.id, user_id=db_user.id)
            await message.answer(f"✅ Job <code>{str(active_job.id)[:8]}</code> has been cancelled.")
        else:
            await message.answer("❌ Failed to cancel the job. It might have already finished.")
