import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from rescueai.db.base import Base


class OutboxEvent(Base):
    """Transactional outbox: a message to publish to the broker, committed *with* the state change.

    Writing the job and its outbox row in one transaction closes the gap between "committed to
    PostgreSQL" and "published to Redis". A relay (a later phase) publishes unpublished rows and
    marks them; publishing is at-least-once, so consumers must tolerate duplicates.
    """

    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    aggregate_type: Mapped[str] = mapped_column(String(50))
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    event_type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publish_attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("publish_attempts >= 0", name="publish_attempts_non_negative"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_is_object"),
    )


# Partial index: the relay only ever scans the (small) unpublished tail, never the history.
Index(
    "ix_outbox_events_unpublished",
    OutboxEvent.created_at,
    postgresql_where=text("published_at IS NULL"),
)
