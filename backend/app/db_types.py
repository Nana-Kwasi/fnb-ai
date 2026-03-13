"""Portable column types for SQLite and PostgreSQL."""
import json
import uuid
from sqlalchemy import String, Text, JSON
from sqlalchemy.types import TypeDecorator, LargeBinary
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY


class UuidType(TypeDecorator):
    """UUID stored as native UUID on Postgres, VARCHAR(36) elsewhere."""

    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.UUID(as_uuid=True))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value if dialect.name == "postgresql" else str(value)
        # Allow strings; normalise to UUID first so Postgres gets a real uuid
        u = uuid.UUID(str(value))
        return u if dialect.name == "postgresql" else str(u)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


class StringArrayType(TypeDecorator):
    """Stores list[str] as TEXT[] on Postgres, JSON string elsewhere."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_ARRAY(Text))
        return dialect.type_descriptor(Text)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            # Expect a Python list for TEXT[]; pass through unchanged.
            return list(value)
        # Non-Postgres: store as JSON text.
        return json.dumps(value) if value else "[]"

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            # asyncpg returns Python lists for text[] already.
            return list(value)
        if isinstance(value, str):
            return json.loads(value) if value else []
        return value


class EmbeddingType(TypeDecorator):
    """Stores float list (e.g. 384-dim embedding) as JSON for SQLite/Postgres."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return json.dumps(value) if value else "[]"

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            return json.loads(value) if value else []
        return value
