from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.platform_deps import hash_password
from app.config import settings
from app.models.platform_user import PlatformUser


async def ensure_bootstrap_platform_owner(session: AsyncSession) -> None:
    n = (await session.execute(select(func.count()).select_from(PlatformUser))).scalar_one()
    if int(n or 0) > 0:
        return
    email = (getattr(settings, "platform_bootstrap_owner_email", "") or "").strip().lower()
    password = getattr(settings, "platform_bootstrap_owner_password", "") or ""
    if not email or not password:
        return
    now = datetime.now(timezone.utc)
    session.add(
        PlatformUser(
            email=email,
            password_hash=hash_password(password),
            role="owner",
            must_change_password=False,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
    )
    await session.flush()
