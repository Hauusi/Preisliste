from sqlalchemy.orm import Session

from backend.models.entities import AuditLog, User


def audit(db: Session, user: User | None, action: str, entity: str | None = None,
          entity_id=None, details: dict | None = None, ip: str | None = None) -> None:
    db.add(AuditLog(
        user_id=user.id if user else None,
        username=user.username if user else None,
        action=action,
        entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=details,
        ip=ip,
    ))
