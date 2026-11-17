import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from rescueai.db.base import Base, enum_column, in_list
from rescueai.db.enums import AnalysisSource


class FailureAnalysis(Base):
    """Advisory diagnosis of a failure (LLM or deterministic fallback). Never executes anything."""

    __tablename__ = "failure_analyses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="RESTRICT"))
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("job_attempts.id", ondelete="RESTRICT")
    )
    source: Mapped[AnalysisSource] = mapped_column(enum_column(AnalysisSource, 16))
    category: Mapped[str] = mapped_column(String(100))
    root_cause: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    recommended_action: Mapped[str] = mapped_column(Text)
    confidence: Mapped[Decimal] = mapped_column(Numeric(3, 2))
    requires_human_approval: Mapped[bool] = mapped_column(Boolean)
    model_name: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(in_list("source", AnalysisSource), name="source_valid"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        CheckConstraint("jsonb_typeof(evidence) = 'array'", name="evidence_is_array"),
        CheckConstraint(
            "source <> 'llm' OR model_name IS NOT NULL", name="llm_analysis_has_model_name"
        ),
        CheckConstraint(
            "(input_tokens IS NULL OR input_tokens >= 0) AND "
            "(output_tokens IS NULL OR output_tokens >= 0)",
            name="token_counts_non_negative",
        ),
    )


Index(
    "ix_failure_analyses_job_id_created_at",
    FailureAnalysis.job_id,
    FailureAnalysis.created_at.desc(),
)
