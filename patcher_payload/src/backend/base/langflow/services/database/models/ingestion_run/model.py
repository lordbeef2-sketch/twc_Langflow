"""Persistent record of a single KB ingestion run."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import JSON, BigInteger, CheckConstraint, Column, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

JsonVariant = JSON().with_variant(JSONB(), "postgresql")
_RUN_STATUS_VALUES = ("pending", "running", "succeeded", "partial", "failed", "cancelled")


class IngestionRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class IngestionRunBase(SQLModel):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    job_id: UUID | None = Field(default=None, index=True, nullable=True)
    kb_name: str = Field(index=True, nullable=False)
    kb_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            sa.Uuid(),
            ForeignKey("knowledge_base.id", ondelete="SET NULL"),
            index=True,
            nullable=True,
        ),
    )
    user_id: UUID | None = Field(default=None, index=True, nullable=True)
    source_type: str = Field(index=True, nullable=False)
    source_config: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JsonVariant, nullable=False))
    status: str = Field(default=IngestionRunStatus.PENDING.value, index=True, nullable=False)
    error_message: str | None = Field(default=None, nullable=True)
    total_items: int = Field(default=0, nullable=False)
    succeeded: int = Field(default=0, nullable=False)
    failed: int = Field(default=0, nullable=False)
    skipped: int = Field(default=0, nullable=False)
    total_bytes: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, server_default="0"))
    chunks_created: int = Field(default=0, nullable=False)
    items: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JsonVariant, nullable=False))
    user_metadata: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JsonVariant, nullable=False, server_default="{}"),
    )
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True),
    )
    finished_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))


class IngestionRun(IngestionRunBase, table=True):  # type: ignore[call-arg]
    __tablename__ = "ingestion_run"
    __table_args__ = (
        CheckConstraint(
            "status IN (" + ", ".join(f"'{value}'" for value in _RUN_STATUS_VALUES) + ")",
            name="ck_ingestion_run_status",
        ),
    )
