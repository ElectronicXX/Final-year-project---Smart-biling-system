from calendar import monthrange
from datetime import date, datetime
import json

from db import db
from models import Billing, BillingItem, BillingSchedule, User
from services.audit_service import record_audit
from services.billing_service import current_month
from services.notification_service import notify


def schedule_items(schedule):
    try:
        items = json.loads(schedule.items_json or "[]")
    except json.JSONDecodeError:
        return []
    return [
        {"name": str(item.get("name", "")).strip(), "amount": float(item.get("amount", 0))}
        for item in items
        if str(item.get("name", "")).strip() and float(item.get("amount", 0)) >= 0
    ]


def generate_scheduled_bill(schedule, today=None):
    today = today or date.today()
    month = today.strftime("%B %Y")
    if not schedule.enabled or schedule.last_generated_month == month:
        return None
    if today.day < min(schedule.day_of_month, monthrange(today.year, today.month)[1]):
        return None
    if Billing.query.filter_by(month=month).first():
        schedule.last_generated_month = month
        db.session.commit()
        return None

    items = schedule_items(schedule)
    if not items:
        return None
    total = round(sum(item["amount"] for item in items), 2)
    due_day = min(schedule.day_of_month + 14, monthrange(today.year, today.month)[1])
    bill = Billing(
        month=month,
        electricity=next(
            (item["amount"] for item in items if item["name"].lower() == "electricity"),
            0,
        ),
        water=next(
            (item["amount"] for item in items if item["name"].lower() == "water"),
            0,
        ),
        total=total,
        currency=schedule.currency,
        due_date=date(today.year, today.month, due_day),
        auto_generated=True,
    )
    db.session.add(bill)
    db.session.flush()
    for item in items:
        db.session.add(
            BillingItem(billing_id=bill.id, name=item["name"], amount=item["amount"])
        )
    schedule.last_generated_month = month
    if schedule.send_reminders:
        for user in User.query.filter_by(role="user").all():
            notify(
                user.id,
                "New monthly bill",
                f"The {month} bill has been generated.",
                "billing",
                "/user_dashboard",
            )
    record_audit(
        "auto_generate",
        "billing",
        bill.id,
        {"month": month, "total": total},
        actor_id=None,
    )
    db.session.commit()
    return bill


def run_due_schedules(today=None):
    generated = []
    for schedule in BillingSchedule.query.filter_by(enabled=True).all():
        bill = generate_scheduled_bill(schedule, today=today)
        if bill:
            generated.append(bill)
    return generated
