import uuid
from typing import Any

from sqlalchemy.orm import Session

from rescueai.db.models import OutboxEvent


class OutboxRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(
        self,
        *,
        aggregate_type: str,
        aggregate_id: uuid.UUID,
        event_type: str,
        payload: dict[str, Any],
    ) -> OutboxEvent:
        event = OutboxEvent(
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            payload=payload,
        )
        self._session.add(event)
        return event
