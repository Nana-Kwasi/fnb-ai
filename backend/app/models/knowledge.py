import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
from app.db_types import UuidType, EmbeddingType


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UuidType(), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UuidType(), ForeignKey("tenant_banks.id"), nullable=False)
    document_name: Mapped[str] = mapped_column(String(255), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list] = mapped_column(EmbeddingType(), nullable=False)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
