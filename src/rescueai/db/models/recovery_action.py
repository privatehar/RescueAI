import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from rescueai.db.base import Base, enum_column, in_list
from rescueai.db.enums import ActorType, JobStatus, RecoveryActionType


class RecoveryAction(Base):
    """A recovery *decision* applied to a job (retry scheduled, dead-lettered, manual retry...).

    ``analysis_id`` links the AI recommendation that informed a human decision, if any. The LLM
    itself never appears as an actor: it recommends, the engine or a person acts.
    """

    __tablename__ = "recovery_actions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="RESTRICT"))
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("job_attempts.id", ondelete="RESTRICT")
    )
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("failure_analyses.id", ondelete="RESTRICT")
    )
    action_type: Mapped[RecoveryActionType] = mapped_column(enum_column(RecoveryActionType, 32))
    actor_type: Mapped[ActorType] = mapped_column(enum_column(ActorType, 16))
    actor_id: Mapped[str | None] = mapped_column(String(128))
    from_status: Mapped[JobStatus | None] = mapped_column(enum_column(JobStatus, 20))
    to_status: Mapped[JobStatus] = mapped_column(enum_column(JobStatus, 20))
    reason: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(in_list("action_type", RecoveryActionType), name="action_type_valid"),
        CheckConstraint(in_list("actor_type", ActorType), name="actor_type_valid"),
        CheckConstraint(in_list("from_status", JobStatus), name="from_status_valid"),
        CheckConstraint(in_list("to_status", JobStatus), name="to_status_valid"),
        CheckConstraint("jsonb_typeof(details) = 'object'", name="details_is_object"),
        # A person must be identifiable; SYSTEM / ANONYMOUS need no id.
        CheckConstraint("actor_type <> 'USER' OR actor_id IS NOT NULL", name="user_has_actor_id"),
    )


Index(
    "ix_recovery_actions_job_id_created_at", RecoveryAction.job_id, RecoveryAction.created_at.desc()
)
