from logging.config import fileConfig
from sqlalchemy import create_engine
from alembic import context

from app.config import settings
from app.database import Base
from app.models import (
    TenantBank,
    Customer,
    Transaction,
    FraudScore,
    ChatSession,
    ChatMessage,
    KnowledgeChunk,
    AuditLog,
)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

sync_url = settings.database_url.replace("+asyncpg", "")
# Escape % for ConfigParser interpolation in alembic.ini
config.set_main_option("sqlalchemy.url", sync_url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(sync_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
