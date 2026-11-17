import uuid
from typing import Any

from sqlalchemy.orm import Session

from rescueai.db.enums import ActorType
from rescueai.db.models import AuditEvent


class AuditRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(
        self,
        *,
        actor_type: ActorType,
        actor_id: str | None,
        action: str,
        entity_type: str,
        entity_id: uuid.UUID,
        correlation_id: str | None,
        details: dict[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            correlation_id=correlation_id,
            details=details or {},
        )
        self._session.add(event)
        return event
