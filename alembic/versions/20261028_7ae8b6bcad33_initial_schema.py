"""initial schema

Creates the persistence layer: jobs, job_attempts, failure_analyses, recovery_actions,
audit_events and outbox_events, with CHECK / UNIQUE / FOREIGN KEY constraints and indexes.
audit_events is made append-only by a trigger (hand-written; Alembic cannot autogenerate it).

Revision ID: 7ae8b6bcad33
Revises:
Create Date: 2026-10-28 22:47:29.566378+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7ae8b6bcad33"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "audit_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "actor_type",
            sa.Enum("SYSTEM", "USER", "ANONYMOUS", name="actortype", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("actor_id", sa.String(length=128), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "actor_type IN ('SYSTEM', 'USER', 'ANONYMOUS')",
            name=op.f("ck_audit_events_actor_type_valid"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(details) = 'object'", name=op.f("ck_audit_events_details_is_object")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(
        "ix_audit_events_entity",
        "audit_events",
        ["entity_type", "entity_id", "occurred_at"],
        unique=False,
    )
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"], unique=False)
    op.create_table(
        "jobs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "job_type",
            sa.Enum("api_call", "etl", "report", name="jobtype", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "QUEUED",
                "RUNNING",
                "SUCCEEDED",
                "RETRY_SCHEDULED",
                "FAILED",
                "DEAD_LETTER",
                "CANCELLED",
                name="jobstatus",
                native_enum=False,
                length=20,
            ),
            server_default=sa.text("'PENDING'"),
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=128), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cancel_requested", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status IN ('SUCCEEDED', 'FAILED', 'DEAD_LETTER', 'CANCELLED')) = (completed_at IS NOT NULL)",
            name=op.f("ck_jobs_completed_at_matches_final_status"),
        ),
        sa.CheckConstraint(
            "job_type IN ('api_call', 'etl', 'report')", name=op.f("ck_jobs_job_type_valid")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name=op.f("ck_jobs_payload_is_object")
        ),
        sa.CheckConstraint(
            "status <> 'RETRY_SCHEDULED' OR next_retry_at IS NOT NULL",
            name=op.f("ck_jobs_retry_scheduled_has_next_retry_at"),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'QUEUED', 'RUNNING', 'SUCCEEDED', 'RETRY_SCHEDULED', 'FAILED', 'DEAD_LETTER', 'CANCELLED')",
            name=op.f("ck_jobs_status_valid"),
        ),
        sa.CheckConstraint(
            "attempt_count <= max_attempts", name=op.f("ck_jobs_attempts_within_max")
        ),
        sa.CheckConstraint("attempt_count >= 0", name=op.f("ck_jobs_attempt_count_non_negative")),
        sa.CheckConstraint(
            "char_length(request_hash) = 64", name=op.f("ck_jobs_request_hash_length")
        ),
        sa.CheckConstraint(
            "idempotency_key IS NULL OR char_length(idempotency_key) BETWEEN 1 AND 128",
            name=op.f("ck_jobs_idempotency_key_length"),
        ),
        sa.CheckConstraint(
            "max_attempts BETWEEN 1 AND 10", name=op.f("ck_jobs_max_attempts_range")
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR completed_at IS NULL OR completed_at >= started_at",
            name=op.f("ck_jobs_completed_after_started"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_jobs_idempotency_key")),
    )
    op.create_index(
        "ix_jobs_created_at_id",
        "jobs",
        [sa.literal_column("created_at DESC"), sa.literal_column("id DESC")],
        unique=False,
    )
    op.create_index(
        "ix_jobs_job_type_created_at_id",
        "jobs",
        ["job_type", sa.literal_column("created_at DESC"), sa.literal_column("id DESC")],
        unique=False,
    )
    op.create_index(
        "ix_jobs_status_created_at_id",
        "jobs",
        ["status", sa.literal_column("created_at DESC"), sa.literal_column("id DESC")],
        unique=False,
    )
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("aggregate_type", sa.String(length=50), nullable=False),
        sa.Column("aggregate_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publish_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name=op.f("ck_outbox_events_payload_is_object")
        ),
        sa.CheckConstraint(
            "publish_attempts >= 0", name=op.f("ck_outbox_events_publish_attempts_non_negative")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_events")),
    )
    op.create_index(
        "ix_outbox_events_unpublished",
        "outbox_events",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.create_table(
        "job_attempts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "RUNNING",
                "SUCCEEDED",
                "FAILED",
                "INTERRUPTED",
                "TIMED_OUT",
                name="attemptstatus",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("error_type", sa.String(length=200), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("stack_trace", sa.Text(), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=True),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "(status = 'RUNNING') = (finished_at IS NULL)",
            name=op.f("ck_job_attempts_finished_at_matches_status"),
        ),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'INTERRUPTED', 'TIMED_OUT')",
            name=op.f("ck_job_attempts_status_valid"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('FAILED', 'TIMED_OUT') OR error_type IS NOT NULL",
            name=op.f("ck_job_attempts_failure_has_error_type"),
        ),
        sa.CheckConstraint(
            "attempt_number >= 1", name=op.f("ck_job_attempts_attempt_number_positive")
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name=op.f("ck_job_attempts_duration_non_negative"),
        ),
        sa.CheckConstraint(
            "error_message IS NULL OR char_length(error_message) <= 4000",
            name=op.f("ck_job_attempts_error_message_length"),
        ),
        sa.CheckConstraint(
            "stack_trace IS NULL OR char_length(stack_trace) <= 20000",
            name=op.f("ck_job_attempts_stack_trace_length"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_job_attempts_job_id_jobs"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_attempts")),
        sa.UniqueConstraint(
            "job_id", "attempt_number", name=op.f("uq_job_attempts_job_id_attempt_number")
        ),
    )
    op.create_index(
        "uq_job_attempts_one_running_per_job",
        "job_attempts",
        ["job_id"],
        unique=True,
        postgresql_where=sa.text("status = 'RUNNING'"),
    )
    op.create_table(
        "failure_analyses",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("attempt_id", sa.UUID(), nullable=True),
        sa.Column(
            "source",
            sa.Enum("llm", "fallback", name="analysissource", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("root_cause", sa.Text(), nullable=False),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=3, scale=2), nullable=False),
        sa.Column("requires_human_approval", sa.Boolean(), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=True),
        sa.Column("prompt_version", sa.String(length=50), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "analyzed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(evidence) = 'array'", name=op.f("ck_failure_analyses_evidence_is_array")
        ),
        sa.CheckConstraint(
            "source <> 'llm' OR model_name IS NOT NULL",
            name=op.f("ck_failure_analyses_llm_analysis_has_model_name"),
        ),
        sa.CheckConstraint(
            "source IN ('llm', 'fallback')", name=op.f("ck_failure_analyses_source_valid")
        ),
        sa.CheckConstraint(
            "(input_tokens IS NULL OR input_tokens >= 0) AND (output_tokens IS NULL OR output_tokens >= 0)",
            name=op.f("ck_failure_analyses_token_counts_non_negative"),
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 1", name=op.f("ck_failure_analyses_confidence_range")
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["job_attempts.id"],
            name=op.f("fk_failure_analyses_attempt_id_job_attempts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_failure_analyses_job_id_jobs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_failure_analyses")),
    )
    op.create_index(
        "ix_failure_analyses_job_id_created_at",
        "failure_analyses",
        ["job_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_table(
        "recovery_actions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("attempt_id", sa.UUID(), nullable=True),
        sa.Column("analysis_id", sa.UUID(), nullable=True),
        sa.Column(
            "action_type",
            sa.Enum(
                "RETRY_SCHEDULED",
                "DEAD_LETTERED",
                "MARKED_FAILED",
                "MANUAL_RETRY",
                "CANCEL_REQUESTED",
                "CANCELLED",
                "INTERRUPTED_RECOVERED",
                name="recoveryactiontype",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "actor_type",
            sa.Enum("SYSTEM", "USER", "ANONYMOUS", name="actortype", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("actor_id", sa.String(length=128), nullable=True),
        sa.Column(
            "from_status",
            sa.Enum(
                "PENDING",
                "QUEUED",
                "RUNNING",
                "SUCCEEDED",
                "RETRY_SCHEDULED",
                "FAILED",
                "DEAD_LETTER",
                "CANCELLED",
                name="jobstatus",
                native_enum=False,
                length=20,
            ),
            nullable=True,
        ),
        sa.Column(
            "to_status",
            sa.Enum(
                "PENDING",
                "QUEUED",
                "RUNNING",
                "SUCCEEDED",
                "RETRY_SCHEDULED",
                "FAILED",
                "DEAD_LETTER",
                "CANCELLED",
                name="jobstatus",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action_type IN ('RETRY_SCHEDULED', 'DEAD_LETTERED', 'MARKED_FAILED', 'MANUAL_RETRY', 'CANCEL_REQUESTED', 'CANCELLED', 'INTERRUPTED_RECOVERED')",
            name=op.f("ck_recovery_actions_action_type_valid"),
        ),
        sa.CheckConstraint(
            "actor_type <> 'USER' OR actor_id IS NOT NULL",
            name=op.f("ck_recovery_actions_user_has_actor_id"),
        ),
        sa.CheckConstraint(
            "actor_type IN ('SYSTEM', 'USER', 'ANONYMOUS')",
            name=op.f("ck_recovery_actions_actor_type_valid"),
        ),
        sa.CheckConstraint(
            "from_status IN ('PENDING', 'QUEUED', 'RUNNING', 'SUCCEEDED', 'RETRY_SCHEDULED', 'FAILED', 'DEAD_LETTER', 'CANCELLED')",
            name=op.f("ck_recovery_actions_from_status_valid"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(details) = 'object'", name=op.f("ck_recovery_actions_details_is_object")
        ),
        sa.CheckConstraint(
            "to_status IN ('PENDING', 'QUEUED', 'RUNNING', 'SUCCEEDED', 'RETRY_SCHEDULED', 'FAILED', 'DEAD_LETTER', 'CANCELLED')",
            name=op.f("ck_recovery_actions_to_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["failure_analyses.id"],
            name=op.f("fk_recovery_actions_analysis_id_failure_analyses"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["job_attempts.id"],
            name=op.f("fk_recovery_actions_attempt_id_job_attempts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_recovery_actions_job_id_jobs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recovery_actions")),
    )
    op.create_index(
        "ix_recovery_actions_job_id_created_at",
        "recovery_actions",
        ["job_id", sa.literal_column("created_at DESC")],
        unique=False,
    )

    # Hand-written: make audit_events append-only. Row-level triggers do not fire for TRUNCATE,
    # which is intentional (only a DBA / test cleanup can wipe the table, never application code).
    op.execute(
        """
        CREATE FUNCTION audit_events_block_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only (% not allowed)', TG_OP
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_events_append_only
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION audit_events_block_mutation()
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_recovery_actions_job_id_created_at", table_name="recovery_actions")
    op.drop_table("recovery_actions")
    op.drop_index("ix_failure_analyses_job_id_created_at", table_name="failure_analyses")
    op.drop_table("failure_analyses")
    op.drop_index(
        "uq_job_attempts_one_running_per_job",
        table_name="job_attempts",
        postgresql_where=sa.text("status = 'RUNNING'"),
    )
    op.drop_table("job_attempts")
    op.drop_index(
        "ix_outbox_events_unpublished",
        table_name="outbox_events",
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.drop_table("outbox_events")
    op.drop_index("ix_jobs_status_created_at_id", table_name="jobs")
    op.drop_index("ix_jobs_job_type_created_at_id", table_name="jobs")
    op.drop_index("ix_jobs_created_at_id", table_name="jobs")
    op.drop_table("jobs")
    op.execute("DROP TRIGGER trg_audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION audit_events_block_mutation()")
    op.drop_index("ix_audit_events_occurred_at", table_name="audit_events")
    op.drop_index("ix_audit_events_entity", table_name="audit_events")
    op.drop_table("audit_events")
