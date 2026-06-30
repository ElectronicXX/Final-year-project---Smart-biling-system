from db import db
from models import Notification, User


def notify(user_id, title, message, category="info", link=None):
    notification = Notification(
        user_id=user_id,
        title=title,
        message=message,
        category=category,
        link=link,
    )
    db.session.add(notification)
    return notification


def notify_roles(roles, title, message, category="info", link=None):
    users = User.query.filter(User.role.in_(roles)).all()
    for user in users:
        notify(user.id, title, message, category, link)
    return len(users)
