import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from rescueai.db.base import Base, enum_column, in_list
from rescueai.db.enums import ActorType


class AuditEvent(Base):
    """Append-only record of who did what. UPDATE and DELETE are blocked by a DB trigger.

    ``details`` must never contain job payloads or secrets.
    """

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    actor_type: Mapped[ActorType] = mapped_column(enum_column(ActorType, 16))
    actor_id: Mapped[str | None] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(100))  # e.g. "job.created"
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))

    __table_args__ = (
        CheckConstraint(in_list("actor_type", ActorType), name="actor_type_valid"),
        CheckConstraint("jsonb_typeof(details) = 'object'", name="details_is_object"),
    )


# "History of this entity", oldest first.
Index(
    "ix_audit_events_entity", AuditEvent.entity_type, AuditEvent.entity_id, AuditEvent.occurred_at
)
Index("ix_audit_events_occurred_at", AuditEvent.occurred_at)
