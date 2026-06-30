from datetime import date, datetime, timedelta
from pathlib import Path
import json
import math
import re

import numpy as np
from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from db import db
from models import (
    AuditLog,
    Billing,
    BillingItem,
    BillingSchedule,
    DailyCheckIn,
    Notification,
    Payment,
    PaymentTransaction,
    User,
    UserDays,
)
from security import admin_required, finance_required, resident_required, user_required
from services.audit_service import record_audit
from services.attendance_service import check_in_user, user_attendance
from services.billing_service import (
    amount_for_user,
    bill_items,
    current_month,
    ensure_payment,
    month_sort_key,
    payment_for_user,
    replace_bill_items,
    sorted_bills,
    total_days_for_month,
)
from services.email_service import send_receipt_email, send_reminder_email
from services.messaging_service import send_sms, send_whatsapp
from services.notification_service import notify, notify_roles
from services.payment_service import add_transaction
from services.pdf_service import generate_pdf
from services.qr_service import generate_qr
from services.server_monitor_service import server_metrics

bp = Blueprint("admin", __name__)


def resident_users():
    return User.query.filter_by(role="user").order_by(User.name).all()


def valid_month(value):
    try:
        datetime.strptime(value, "%B %Y")
        return True
    except (TypeError, ValueError):
        return False


def paid_user_count(month):
    return (
        Payment.query.with_entities(func.count(func.distinct(Payment.user_id)))
        .join(User, User.id == Payment.user_id)
        .filter(
            Payment.month == month,
            Payment.status == "Paid",
            User.role == "user",
        )
        .scalar()
        or 0
    )


def clean_user_form():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    role = request.form.get("role", "user")
    if (
        not name
        or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)
        or role not in {"admin", "finance", "user", "guest"}
    ):
        return None

    def optional_int(field):
        value = request.form.get(field, "").strip()
        return int(value) if value else None

    try:
        values = {
            "name": name,
            "email": email,
            "role": role,
            "age": optional_int("age"),
            "gender": request.form.get("gender", "").strip() or None,
            "block": request.form.get("block", "").strip() or None,
            "floor": optional_int("floor"),
            "unit": optional_int("unit"),
            "room": optional_int("room"),
        }
        if values["age"] is not None and not 16 <= values["age"] <= 100:
            return None
        if any(
            values[field] is not None and values[field] < 1
            for field in ("floor", "unit", "room")
        ):
            return None
        return values
    except ValueError:
        return None


@bp.route("/dashboard")
@finance_required
def dashboard():
    users = resident_users()
    month = current_month()
    paid_count = paid_user_count(month)
    history = sorted_bills()
    bill = Billing.query.filter_by(month=month).first()
    return render_template(
        "dashboard.html",
        users=users,
        paid_count=paid_count,
        months=[bill.month for bill in history],
        totals=[bill.total for bill in history],
        current_total=bill.total if bill else 0,
    )


@bp.route("/api/dashboard_data")
@finance_required
def dashboard_data():
    users = resident_users()
    month = current_month()
    paid_count = paid_user_count(month)
    history = sorted_bills()
    bill = Billing.query.filter_by(month=month).first()
    return {
        "users": len(users),
        "paid": paid_count,
        "pending": max(len(users) - paid_count, 0),
        "revenue": bill.total if bill else 0,
        "months": [bill.month for bill in history],
        "totals": [bill.total for bill in history],
    }


@bp.route("/api/server_metrics")
@admin_required
def server_metrics_data():
    return server_metrics()


@bp.route("/api/predict")
@finance_required
def predict():
    totals = [bill.total for bill in sorted_bills()]
    if len(totals) < 2:
        return {"predicted": []}
    x = np.arange(len(totals))
    slope, intercept = np.polyfit(x, np.array(totals), 1)
    predicted = slope * np.arange(len(totals), len(totals) + 3) + intercept
    return {"predicted": np.maximum(predicted, 0).round(2).tolist()}


@bp.route("/users")
@admin_required
def users():
    return render_template("users.html", users=User.query.order_by(User.name).all())


@bp.route("/billing")
@finance_required
def billing():
    history = sorted_bills()
    selected_month = request.args.get("month") or current_month()
    if not valid_month(selected_month):
        selected_month = current_month()
    bill = Billing.query.filter_by(month=selected_month).first()
    total_days = total_days_for_month(selected_month)
    status_filter = request.args.get("status", "").strip()
    user_filter = request.args.get("user", type=int)
    search = request.args.get("q", "").strip().lower()
    data = []
    for user in resident_users():
        calculated_amount = amount_for_user(
            user.id, selected_month, bill=bill, total_days=total_days
        )
        payment = payment_for_user(user.id, selected_month)
        if bill and not payment:
            payment = ensure_payment(
                user.id, selected_month, calculated_amount, bill=bill
            )
        elif payment and not payment.transactions and payment.status != "Paid":
            payment.amount = calculated_amount
            payment.currency = (bill.currency if bill else payment.currency) or "MYR"
            payment.due_date = bill.due_date if bill else payment.due_date
        status = payment.status if payment else "Pending"
        if status_filter and status != status_filter:
            continue
        if user_filter and user.id != user_filter:
            continue
        if search and search not in user.name.lower() and search not in user.email.lower():
            continue
        data.append(
            {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "amount": payment.amount if payment else calculated_amount,
                "paid_amount": payment.paid_amount if payment else 0,
                "balance": payment.balance if payment else calculated_amount,
                "status": status,
            }
        )
    db.session.commit()
    months = [item.month for item in history]
    if selected_month not in months:
        months.append(selected_month)
    schedule = BillingSchedule.query.first()
    try:
        schedule_items_data = json.loads(schedule.items_json) if schedule else []
    except json.JSONDecodeError:
        schedule_items_data = []
    return render_template(
        "billing.html",
        bill=bill,
        history=history,
        months=months,
        totals=[item.total for item in history],
        chart_months=[item.month for item in history],
        selected_month=selected_month,
        data=data,
        residents=resident_users(),
        filters=request.args,
        bill_items=bill_items(bill),
        currency=(bill.currency if bill else current_app.config["DEFAULT_CURRENCY"]),
        schedule=schedule,
        schedule_items=schedule_items_data,
    )


@bp.route("/send_reminder/<int:user_id>", methods=["POST"])
@finance_required
def send_reminder(user_id):
    user = db.session.get(User, user_id)
    if not user or user.role != "user":
        return jsonify(error="user not found"), 404
    month = request.form.get("month") or current_month()
    if not valid_month(month):
        return jsonify(error="month must use the format 'June 2026'"), 400
    bill = Billing.query.filter_by(month=month).first()
    if not bill:
        return jsonify(error="bill not found"), 404
    payment = payment_for_user(user_id, month)
    if payment and payment.status == "Paid":
        return jsonify(error="payment is already complete"), 400
    email_status = send_reminder_email(
        user.email,
        amount_for_user(user_id, month, bill=bill),
        month,
        currency=bill.currency or "MYR",
    )
    sms_status = "no_phone"
    whatsapp_status = "no_phone"
    if user.phone:
        reminder_text = (
            f"Smart Billing: your {month} bill of "
            f"{bill.currency or 'MYR'} {amount_for_user(user_id, month, bill=bill):.2f} "
            "is outstanding."
        )
        try:
            sms_status = send_sms(user.phone, reminder_text)
        except Exception:
            current_app.logger.exception("Unable to send SMS reminder")
            sms_status = "delivery_failed"
        try:
            whatsapp_status = send_whatsapp(user.phone, reminder_text)
        except Exception:
            current_app.logger.exception("Unable to send WhatsApp reminder")
            whatsapp_status = "delivery_failed"
    notify(
        user.id,
        "Payment reminder",
        f"Your {month} bill is still outstanding.",
        "warning",
        "/user_dashboard",
    )
    record_audit("send_reminder", "payment", details={"user_id": user.id, "month": month})
    db.session.commit()
    return {
        "status": "success",
        "email_sent": email_status == "sent",
        "email_status": email_status,
        "sms_status": sms_status,
        "whatsapp_status": whatsapp_status,
    }


@bp.route("/generate_bill", methods=["POST"])
@finance_required
def generate_bill():
    month = request.form.get("month", "").strip() or current_month()
    if not valid_month(month):
        return jsonify(error="month must use the format 'June 2026'"), 400
    names = request.form.getlist("item_name")
    amounts = request.form.getlist("item_amount")
    items = []
    try:
        for name, amount_value in zip(names, amounts):
            name = name.strip()
            if not name:
                continue
            amount = round(float(amount_value), 2)
            if not math.isfinite(amount) or amount < 0:
                raise ValueError
            items.append({"name": name, "amount": amount})
    except ValueError:
        return jsonify(error="all billing items must have valid non-negative amounts"), 400
    if not items:
        return jsonify(error="add at least one billing item"), 400
    total = round(sum(item["amount"] for item in items), 2)
    currency = request.form.get("currency", "MYR").strip().upper()
    if len(currency) != 3:
        return jsonify(error="currency must be a three-letter code"), 400
    try:
        due_date = datetime.strptime(request.form.get("due_date", ""), "%Y-%m-%d").date()
    except ValueError:
        due_date = datetime.now().date() + timedelta(days=14)
    if Payment.query.filter_by(month=month, status="Paid").first():
        return jsonify(error="a bill with completed payments cannot be changed"), 409

    bill = Billing.query.filter_by(month=month).first()
    if not bill:
        bill = Billing(month=month)
        db.session.add(bill)
        db.session.flush()
    bill.electricity = next(
        (item["amount"] for item in items if item["name"].lower() == "electricity"),
        0,
    )
    bill.water = next(
        (item["amount"] for item in items if item["name"].lower() == "water"),
        0,
    )
    bill.total = total
    bill.currency = currency
    bill.due_date = due_date
    replace_bill_items(bill, items)
    record_audit(
        "save_bill",
        "billing",
        bill.id,
        {"month": month, "currency": currency, "items": items, "total": total},
    )
    for user in resident_users():
        notify(
            user.id,
            "Bill updated",
            f"The {month} bill is now {currency} {total:.2f}.",
            "billing",
            "/user_dashboard",
        )
    db.session.commit()
    return {"status": "success", "month": month, "total": bill.total}


@bp.route("/billing/schedule", methods=["POST"])
@finance_required
def save_billing_schedule():
    try:
        day_of_month = int(request.form.get("day_of_month", "1"))
    except ValueError:
        return jsonify(error="generation day must be a number"), 400
    if not 1 <= day_of_month <= 28:
        return jsonify(error="generation day must be between 1 and 28"), 400
    items = []
    try:
        for name, value in zip(
            request.form.getlist("schedule_item_name"),
            request.form.getlist("schedule_item_amount"),
        ):
            if not name.strip():
                continue
            amount = round(float(value), 2)
            if amount < 0 or not math.isfinite(amount):
                raise ValueError
            items.append({"name": name.strip(), "amount": amount})
    except ValueError:
        return jsonify(error="scheduled item amounts must be valid"), 400
    if not items:
        return jsonify(error="add at least one scheduled item"), 400
    schedule = BillingSchedule.query.first() or BillingSchedule()
    db.session.add(schedule)
    schedule.name = request.form.get("name", "").strip() or "Monthly Utilities"
    schedule.enabled = request.form.get("enabled") == "on"
    schedule.day_of_month = day_of_month
    schedule.currency = request.form.get("currency", "MYR").upper()
    schedule.items_json = json.dumps(items)
    schedule.send_reminders = request.form.get("send_reminders") == "on"
    record_audit(
        "save_schedule",
        "billing_schedule",
        details={"enabled": schedule.enabled, "day": day_of_month, "items": items},
    )
    db.session.commit()
    return {"status": "success"}


@bp.route("/add_user", methods=["POST"])
@admin_required
def add_user():
    values = clean_user_form()
    password = request.form.get("password", "")
    if not values or len(password) < 8:
        flash("Complete the form and use a password of at least 8 characters.", "danger")
        return redirect(url_for("admin.users"))
    if User.query.filter_by(email=values["email"]).first():
        flash("That email address is already in use.", "danger")
        return redirect(url_for("admin.users"))
    user = User(**values)
    user.set_password(password)
    db.session.add(user)
    record_audit("create_user", "user", details={"email": user.email, "role": user.role})
    db.session.commit()
    flash("User created.", "success")
    return redirect(url_for("admin.users"))


@bp.route("/edit_user/<int:user_id>", methods=["POST"])
@admin_required
def edit_user(user_id):
    user = db.get_or_404(User, user_id)
    values = clean_user_form()
    if not values:
        flash("Invalid user details.", "danger")
        return redirect(url_for("admin.users"))
    duplicate = User.query.filter(
        User.email == values["email"], User.id != user.id
    ).first()
    if duplicate:
        flash("That email address is already in use.", "danger")
        return redirect(url_for("admin.users"))
    if user.id == session["user"] and values["role"] != "admin":
        flash("You cannot remove your own administrator role.", "danger")
        return redirect(url_for("admin.users"))
    for field, value in values.items():
        setattr(user, field, value)
    new_password = request.form.get("password", "")
    if new_password:
        if len(new_password) < 8:
            flash("New password must contain at least 8 characters.", "danger")
            return redirect(url_for("admin.users"))
        user.set_password(new_password)
    record_audit("update_user", "user", user.id, {"role": user.role})
    db.session.commit()
    flash("User updated.", "success")
    return redirect(url_for("admin.users"))


@bp.route("/delete_user/<int:user_id>", methods=["POST"])
@admin_required
def delete_user(user_id):
    user = db.get_or_404(User, user_id)
    if user.id == session["user"]:
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("admin.users"))
    if user.role == "admin" and User.query.filter_by(role="admin").count() <= 1:
        flash("The final administrator account cannot be deleted.", "danger")
        return redirect(url_for("admin.users"))
    pdf_directory = Path(current_app.root_path) / "static" / "pdf"
    for payment in Payment.query.filter_by(user_id=user.id).all():
        if (
            payment.receipt_filename
            and Path(payment.receipt_filename).name == payment.receipt_filename
        ):
            (pdf_directory / payment.receipt_filename).unlink(missing_ok=True)
    DailyCheckIn.query.filter_by(user_id=user.id).delete()
    UserDays.query.filter_by(user_id=user.id).delete()
    payment_ids = [
        item.id for item in Payment.query.filter_by(user_id=user.id).all()
    ]
    if payment_ids:
        PaymentTransaction.query.filter(
            PaymentTransaction.payment_id.in_(payment_ids)
        ).delete(synchronize_session=False)
    Payment.query.filter_by(user_id=user.id).delete()
    Notification.query.filter_by(user_id=user.id).delete()
    AuditLog.query.filter_by(actor_id=user.id).update({"actor_id": None})
    record_audit("delete_user", "user", user.id, {"email": user.email})
    db.session.delete(user)
    db.session.commit()
    flash("User and related billing records deleted.", "success")
    return redirect(url_for("admin.users"))


@bp.route("/user_dashboard")
@resident_required
def user_dashboard():
    user = db.session.get(User, session["user"])
    if not user:
        session.clear()
        return redirect(url_for("auth.login"))
    month = current_month()
    bill = Billing.query.filter_by(month=month).first()
    calculated_amount = amount_for_user(user.id, month, bill=bill)
    payment = payment_for_user(user.id, month)
    if bill and not payment:
        payment = ensure_payment(user.id, month, calculated_amount, bill=bill)
        db.session.commit()
    amount = payment.amount if payment else calculated_amount
    payments = sorted(
        Payment.query.filter_by(user_id=user.id).all(),
        key=lambda item: month_sort_key(item.month),
    )
    history = [
        {
            "id": item.id,
            "month": item.month,
            "amount": item.amount,
            "paid_amount": item.paid_amount or 0,
            "balance": item.balance,
            "currency": item.currency or "MYR",
            "status": item.status,
            "has_receipt": bool(item.receipt_filename),
            "due_date": item.due_date,
            "pending_proof": any(
                transaction.verification_status == "Pending"
                for transaction in item.transactions
            ),
        }
        for item in payments
    ]
    current_currency = payment.currency if payment else (bill.currency if bill else "MYR")
    qr_path = generate_qr(user.id, user.name, amount, month, current_currency)
    attendance = user_attendance(user.id)
    return render_template(
        "user_dashboard.html",
        user=user,
        amount=amount,
        status=payment.status if payment else "Pending",
        month=month,
        qr=qr_path,
        history=history,
        months=[item["month"] for item in history],
        totals=[item["amount"] for item in history],
        payment=payment,
        currency=current_currency,
        unread_notifications=Notification.query.filter_by(
            user_id=user.id, is_read=False
        ).count(),
        attendance=attendance,
    )


@bp.route("/download/receipt/<int:payment_id>")
@resident_required
def download_receipt(payment_id):
    payment = db.get_or_404(Payment, payment_id)
    if payment.user_id != session["user"] or not payment.receipt_filename:
        return jsonify(error="receipt not found"), 404
    pdf_directory = Path(current_app.root_path) / "static" / "pdf"
    return send_from_directory(
        pdf_directory, payment.receipt_filename, as_attachment=True
    )


@bp.route("/checkin", methods=["POST"])
@user_required
def checkin():
    user_id = session["user"]
    try:
        item, record, created = check_in_user(user_id)
        if created:
            record_audit(
                "check_in",
                "daily_check_in",
                item.id,
                {"date": item.checkin_date.isoformat(), "source": "self"},
            )
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        attendance = user_attendance(user_id)
        return {
            "status": "already",
            "days": attendance["count"],
            "streak": attendance["streak"],
            "attendance_rate": attendance["attendance_rate"],
        }
    attendance = user_attendance(user_id)
    return {
        "status": "success" if created else "already",
        "days": record.days,
        "streak": attendance["streak"],
        "attendance_rate": attendance["attendance_rate"],
        "checked_in_at": item.checked_in_at.isoformat() if item.checked_in_at else None,
    }


@bp.route("/user_billing")
@resident_required
def user_billing():
    return redirect(url_for("admin.user_dashboard"))


@bp.route("/pay")
@resident_required
def pay():
    return redirect(url_for("admin.user_dashboard"))


@bp.route("/confirm_payment", methods=["POST"])
@user_required
def confirm_payment():
    user = db.session.get(User, session["user"])
    month = current_month()
    bill = Billing.query.filter_by(month=month).first()
    if not bill:
        return jsonify(error="No bill exists for the current month."), 400
    billed_amount = amount_for_user(user.id, month, bill=bill)
    if billed_amount <= 0:
        return jsonify(error="No payable amount is available."), 400

    payment = payment_for_user(user.id, month) or ensure_payment(
        user.id, month, billed_amount, bill=bill
    )
    if payment and payment.status == "Paid":
        return {
            "status": "success",
            "email_sent": False,
            "already_paid": True,
        }
    try:
        requested_amount = request.form.get("amount")
        amount = payment.balance if not requested_amount else round(float(requested_amount), 2)
        transaction = add_transaction(
            payment,
            amount,
            method="simulated_online",
            verification_status="Approved",
            verified_by=user.id,
        )
    except (ValueError, TypeError) as error:
        return jsonify(error=str(error)), 400

    pdf_path = None
    if payment.status == "Paid":
        receipt_filename, pdf_path = generate_pdf(
            user.id,
            user.name,
            payment.amount,
            month,
            currency=payment.currency or "MYR",
            items=bill_items(bill),
        )
        payment.receipt_filename = receipt_filename
    notify_roles(
        {"admin", "finance"},
        "Payment received",
        f"{user.name} paid {payment.currency} {amount:.2f} for {month}.",
        "payment",
        "/reports",
    )
    record_audit(
        "record_payment",
        "payment_transaction",
        transaction.id,
        {"payment_id": payment.id, "amount": amount, "status": payment.status},
    )
    db.session.commit()

    email_status = (
        send_receipt_email(
            user.email,
            payment.amount,
            month,
            pdf_path,
            currency=payment.currency or "MYR",
        )
        if payment.status == "Paid"
        else "not_applicable"
    )
    return {
        "status": "success",
        "payment_status": payment.status,
        "paid_amount": payment.paid_amount,
        "balance": payment.balance,
        "email_sent": email_status == "sent",
        "email_status": email_status,
    }
