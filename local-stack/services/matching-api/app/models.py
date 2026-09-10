"""Modèles SQLAlchemy pour la persistance des embeddings (pgvector).

EMBEDDING_DIM doit rester cohérent avec le modèle sentence-transformers
configuré (SENTENCE_MODEL) : intfloat/multilingual-e5-base produit des
vecteurs à 768 dimensions. Changer de modèle pour un modèle d'une autre
dimension nécessite une nouvelle migration Alembic.
"""

from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 768


class Base(DeclarativeBase):
    pass


class JobEmbedding(Base):
    __tablename__ = "job_embeddings"
    __table_args__ = (UniqueConstraint("job_id", name="ux_job_embeddings_job_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CvEmbedding(Base):
    __tablename__ = "cv_embeddings"
    __table_args__ = (UniqueConstraint("cv_id", name="ux_cv_embeddings_cv_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cv_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
