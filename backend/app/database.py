from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool
from app.config import settings

_url = settings.database_url
_is_sqlite = "sqlite" in _url
_connect_args = {}
_engine_kw = dict(echo=settings.debug)
if _is_sqlite:
    _engine_kw["connect_args"] = {"check_same_thread": False}
    _engine_kw["poolclass"] = StaticPool
else:
    _engine_kw["pool_pre_ping"] = True
    _engine_kw["pool_size"] = 5
    _engine_kw["max_overflow"] = 10

engine = create_async_engine(_url, **_engine_kw)
_read_url = (settings.read_replica_database_url or "").strip() or _url
_read_is_sqlite = "sqlite" in _read_url
_read_engine_kw = dict(echo=settings.debug)
if _read_is_sqlite:
    _read_engine_kw["connect_args"] = {"check_same_thread": False}
    _read_engine_kw["poolclass"] = StaticPool
else:
    _read_engine_kw["pool_pre_ping"] = True
    _read_engine_kw["pool_size"] = 5
    _read_engine_kw["max_overflow"] = 10
read_engine = create_async_engine(_read_url, **_read_engine_kw)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)
AsyncReadSessionLocal = async_sessionmaker(
    read_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_read_db():
    async with AsyncReadSessionLocal() as session:
        yield session
