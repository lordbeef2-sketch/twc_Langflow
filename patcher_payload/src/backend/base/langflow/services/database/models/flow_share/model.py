from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import Enum as SQLEnum
from sqlmodel import Column, DateTime, Field, Relationship, SQLModel, func

from langflow.schema.serialize import UUIDstr

if TYPE_CHECKING:
    from langflow.services.database.models.flow.model import Flow

SHARED_WITH_ME_FOLDER_ID = "__shared_with_me__"


class FlowSharePermission(str, Enum):
    READ = "read"
    EDIT = "edit"


class FlowShareStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class FlowAccessLevel(str, Enum):
    OWNER = "owner"
    READ = "read"
    EDIT = "edit"


class FlowShare(SQLModel, table=True):  # type: ignore[call-arg]
    __tablename__ = "flow_share"
    __table_args__ = (sa.UniqueConstraint("flow_id", "recipient_user_id", name="uq_flow_share_flow_recipient"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    flow_id: UUID = Field(
        sa_column=Column(sa.Uuid(), sa.ForeignKey("flow.id", ondelete="CASCADE"), nullable=False, index=True)
    )
    owner_user_id: UUIDstr = Field(
        sa_column=Column(sa.Uuid(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    )
    recipient_user_id: UUIDstr = Field(
        sa_column=Column(sa.Uuid(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    )
    permission: FlowSharePermission = Field(
        sa_column=Column(
            SQLEnum(
                FlowSharePermission,
                name="flow_share_permission_enum",
                values_callable=lambda enum: [member.value for member in enum],
            ),
            nullable=False,
        )
    )
    status: FlowShareStatus = Field(
        default=FlowShareStatus.PENDING,
        sa_column=Column(
            SQLEnum(
                FlowShareStatus,
                name="flow_share_status_enum",
                values_callable=lambda enum: [member.value for member in enum],
            ),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
    )
    created_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False),
    )
    updated_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False),
    )
    responded_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))

    flow: "Flow" = Relationship(back_populates="shares")


class FlowShareCreate(SQLModel):
    recipient_user_ids: list[UUID]
    permission: FlowSharePermission = Field(default=FlowSharePermission.READ)


class FlowShareRespond(SQLModel):
    accept: bool = Field(default=True)


class FlowShareRead(SQLModel):
    id: UUID
    flow_id: UUID
    recipient_user_id: UUID
    recipient_username: str
    permission: FlowSharePermission
    status: FlowShareStatus
    created_at: datetime
    updated_at: datetime
    responded_at: datetime | None = None


class IncomingFlowShareRead(SQLModel):
    id: UUID
    flow_id: UUID
    flow_name: str
    owner_user_id: UUID
    owner_username: str
    permission: FlowSharePermission
    status: FlowShareStatus
    created_at: datetime
    responded_at: datetime | None = None
