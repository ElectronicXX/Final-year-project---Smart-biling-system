import os
from datetime import datetime, timedelta

import psutil

from db import db
from models import ActiveSession


ACTIVE_WINDOW_MINUTES = 5


def record_session_activity(token, user_id, ip_address=None):
    now = datetime.now()
    active_session = db.session.get(ActiveSession, token)
    if active_session:
        active_session.user_id = user_id
        active_session.ip_address = ip_address
        active_session.last_seen = now
    else:
        db.session.add(
            ActiveSession(
                token=token,
                user_id=user_id,
                ip_address=ip_address,
                last_seen=now,
            )
        )
    db.session.commit()


def remove_session_activity(token):
    if not token:
        return
    active_session = db.session.get(ActiveSession, token)
    if active_session:
        db.session.delete(active_session)
        db.session.commit()


def active_visitor_count():
    cutoff = datetime.now() - timedelta(minutes=ACTIVE_WINDOW_MINUTES)
    ActiveSession.query.filter(ActiveSession.last_seen < cutoff).delete(
        synchronize_session=False
    )
    db.session.commit()
    return ActiveSession.query.filter(ActiveSession.last_seen >= cutoff).count()


def server_metrics():
    memory = psutil.virtual_memory()
    workers = max(int(os.getenv("GUNICORN_WORKERS", "2")), 1)
    configured_capacity = max(
        int(os.getenv("MAX_CONCURRENT_USERS", str(workers * 50))),
        1,
    )
    active_visitors = active_visitor_count()

    return {
        "cpu_percent": round(psutil.cpu_percent(interval=0.1), 1),
        "ram_percent": round(memory.percent, 1),
        "memory_used_bytes": memory.used,
        "memory_total_bytes": memory.total,
        "active_visitors": active_visitors,
        "max_concurrent_users": configured_capacity,
        "capacity_percent": round(
            min(active_visitors / configured_capacity * 100, 100),
            1,
        ),
        "active_window_minutes": ACTIVE_WINDOW_MINUTES,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
