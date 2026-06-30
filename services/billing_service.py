from datetime import datetime

from sqlalchemy import func

from db import db
from models import Billing, BillingItem, Payment, User, UserDays


def current_month():
    return datetime.now().strftime("%B %Y")


def month_sort_key(value):
    try:
        return datetime.strptime(value, "%B %Y")
    except (TypeError, ValueError):
        return datetime.min


def sorted_bills():
    return sorted(Billing.query.all(), key=lambda bill: month_sort_key(bill.month))


def total_days_for_month(month):
    return (
        UserDays.query.with_entities(func.coalesce(func.sum(UserDays.days), 0))
        .join(User, User.id == UserDays.user_id)
        .filter(UserDays.month == month, User.role == "user")
        .scalar()
        or 0
    )


def amount_for_user(user_id, month, bill=None, total_days=None):
    bill = bill or Billing.query.filter_by(month=month).first()
    if not bill:
        return 0.0

    record = UserDays.query.filter_by(user_id=user_id, month=month).first()
    days = record.days if record else 0
    total_days = (
        total_days_for_month(month) if total_days is None else total_days
    )
    if not total_days:
        return 0.0
    return round((days / total_days) * bill.total, 2)


def payment_for_user(user_id, month):
    return Payment.query.filter_by(user_id=user_id, month=month).first()


def bill_items(bill):
    if not bill:
        return []
    if bill.items:
        return [{"name": item.name, "amount": item.amount} for item in bill.items]
    return [
        {"name": "Electricity", "amount": bill.electricity or 0},
        {"name": "Water", "amount": bill.water or 0},
    ]


def replace_bill_items(bill, items):
    BillingItem.query.filter_by(billing_id=bill.id).delete()
    for item in items:
        db.session.add(
            BillingItem(
                billing_id=bill.id,
                name=item["name"],
                amount=item["amount"],
            )
        )


def ensure_payment(user_id, month, amount=None, bill=None):
    payment = payment_for_user(user_id, month)
    bill = bill or Billing.query.filter_by(month=month).first()
    if payment:
        return payment
    amount = amount_for_user(user_id, month, bill=bill) if amount is None else amount
    payment = Payment(
        user_id=user_id,
        month=month,
        amount=round(amount, 2),
        paid_amount=0,
        status="Pending",
        currency=(bill.currency if bill else "MYR") or "MYR",
        due_date=bill.due_date if bill else None,
    )
    db.session.add(payment)
    return payment
