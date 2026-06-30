import json

from flask import has_request_context, request, session

from db import db
from models import AuditLog


def record_audit(action, entity_type, entity_id=None, details=None, actor_id=None):
    if details is not None and not isinstance(details, str):
        details = json.dumps(details, ensure_ascii=True, default=str)
    log = AuditLog(
        actor_id=(
            actor_id
            if actor_id is not None
            else (session.get("user") if has_request_context() else None)
        ),
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=details,
        ip_address=(
            request.headers.get("X-Forwarded-For", request.remote_addr)
            if has_request_context()
            else None
        ),
    )
    db.session.add(log)
    return log
