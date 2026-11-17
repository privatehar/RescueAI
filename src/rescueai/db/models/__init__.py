"""SQLAlchemy ORM models. Importing this package registers every table on ``Base.metadata``."""

from rescueai.db.models.analysis import FailureAnalysis
from rescueai.db.models.attempt import JobAttempt
from rescueai.db.models.audit_event import AuditEvent
from rescueai.db.models.job import Job
from rescueai.db.models.outbox_event import OutboxEvent
from rescueai.db.models.recovery_action import RecoveryAction

__all__ = [
    "AuditEvent",
    "FailureAnalysis",
    "Job",
    "JobAttempt",
    "OutboxEvent",
    "RecoveryAction",
]
