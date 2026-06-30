from datetime import date, datetime
from io import BytesIO, StringIO
import csv
from pathlib import Path
import secrets

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import or_
from werkzeug.utils import secure_filename

from db import db
from models import (
    AuditLog,
    Billing,
    BillingDispute,
    DailyCheckIn,
    IntegrationSetting,
    Notification,
    Payment,
    PaymentTransaction,
    User,
)
from security import admin_required, finance_required, roles_required
from services.audit_service import record_audit
from services.attendance_service import (
    check_in_user,
    month_bounds,
    remove_checkin,
    user_attendance,
)
from services.billing_service import bill_items, month_sort_key
from services.integration_service import (
    PROVIDERS,
    get_config,
    masked_config,
    record_test,
    save_config,
    test_provider,
)
from services.notification_service import notify, notify_roles
from services.payment_service import refresh_payment_status

bp = Blueprint("portal", __name__)
all_accounts_required = roles_required("admin", "finance", "user", "guest")


def filtered_payments():
    query = Payment.query.join(User, User.id == Payment.user_id)
    month = request.args.get("month", "").strip()
    status = request.args.get("status", "").strip()
    user_id = request.args.get("user", type=int)
    search = request.args.get("q", "").strip()
    if month:
        query = query.filter(Payment.month == month)
    if status:
        query = query.filter(Payment.status == status)
    if user_id:
        query = query.filter(Payment.user_id == user_id)
    if search:
        query = query.filter(
            or_(
                User.name.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%"),
                Payment.month.ilike(f"%{search}%"),
            )
        )
    return query.order_by(Payment.id.desc())


@bp.route("/account", methods=["GET", "POST"])
@all_accounts_required
def account():
    user = db.get_or_404(User, session["user"])
    if request.method == "POST":
        action = request.form.get("action", "profile")
        if action == "password":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            if not user.check_password(current_password) or len(new_password) < 8:
                flash("Current password is incorrect or the new password is too short.", "danger")
            else:
                user.set_password(new_password)
                record_audit("change_password", "user", user.id)
                db.session.commit()
                flash("Password updated.", "success")
        else:
            user.name = request.form.get("name", "").strip() or user.name
            user.phone = request.form.get("phone", "").strip() or None
            currency = request.form.get("preferred_currency", "MYR").upper()
            user.preferred_currency = currency if len(currency) == 3 else "MYR"
            record_audit("update_profile", "user", user.id)
            db.session.commit()
            flash("Profile updated.", "success")
        return redirect(url_for("portal.account"))
    return render_template("account.html", user=user)


@bp.route("/notifications")
@all_accounts_required
def notifications():
    items = (
        Notification.query.filter_by(user_id=session["user"])
        .order_by(Notification.created_at.desc())
        .all()
    )
    return render_template("notifications.html", notifications=items)


@bp.route("/notifications/<int:notification_id>/read", methods=["POST"])
@all_accounts_required
def mark_notification_read(notification_id):
    item = db.get_or_404(Notification, notification_id)
    if item.user_id != session["user"]:
        return jsonify(error="notification not found"), 404
    item.is_read = True
    db.session.commit()
    return {"status": "success"}


@bp.route("/audit")
@admin_required
def audit_logs():
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(500).all()
    users = {user.id: user for user in User.query.all()}
    return render_template("audit.html", logs=logs, users=users)


@bp.route("/integrations")
@admin_required
def integrations():
    providers = []
    for name, metadata in PROVIDERS.items():
        setting, values = masked_config(name)
        providers.append(
            {
                "name": name,
                "metadata": metadata,
                "setting": setting,
                "config_values": values,
            }
        )
    webhook_base = current_app.config["APP_BASE_URL"].rstrip("/")
    return render_template(
        "integrations.html",
        providers=providers,
        webhook_base=webhook_base,
    )


@bp.route("/integrations/<provider>", methods=["POST"])
@admin_required
def update_integration(provider):
    if provider not in PROVIDERS:
        return jsonify(error="unknown integration provider"), 404
    values = {}
    for name, _, field_type, _ in PROVIDERS[provider]["fields"]:
        values[name] = request.form.get(name) if field_type != "checkbox" else name in request.form
    setting = save_config(
        provider,
        values,
        enabled=request.form.get("enabled") == "on",
        actor_id=session["user"],
    )
    record_audit(
        "update_integration",
        "integration_setting",
        setting.id,
        {"provider": provider, "enabled": setting.enabled},
    )
    db.session.commit()
    flash(f"{PROVIDERS[provider]['label']} settings saved.", "success")
    return redirect(url_for("portal.integrations", provider=provider))


@bp.route("/integrations/<provider>/test", methods=["POST"])
@admin_required
def test_integration(provider):
    if provider not in PROVIDERS:
        return jsonify(error="unknown integration provider"), 404
    setting = IntegrationSetting.query.filter_by(provider=provider).first()
    if not setting:
        return jsonify(error="save the integration settings first"), 400
    if provider == "smtp" and not setting.enabled:
        message = "SMTP settings are saved but disabled. Enable SMTP before testing or sending email."
        record_test(setting, False, message)
        record_audit(
            "test_integration",
            "integration_setting",
            setting.id,
            {"provider": provider, "success": False},
        )
        db.session.commit()
        return jsonify(success=False, message=message), 400
    config = get_config(provider, include_disabled=True)
    try:
        message = test_provider(provider, config)
        success = True
    except Exception as error:
        current_app.logger.warning("%s integration test failed: %s", provider, error)
        message = str(error)
        success = False
    record_test(setting, success, message)
    record_audit(
        "test_integration",
        "integration_setting",
        setting.id,
        {"provider": provider, "success": success},
    )
    db.session.commit()
    return jsonify(success=success, message=message), 200 if success else 400


@bp.route("/attendance")
@finance_required
def attendance():
    month_value = request.args.get("month", "").strip()
    try:
        selected = datetime.strptime(month_value, "%Y-%m").date()
    except ValueError:
        selected = date.today()
    residents = User.query.filter_by(role="user").order_by(User.name).all()
    rows = []
    for resident in residents:
        stats = user_attendance(resident.id, selected)
        rows.append({"user": resident, **stats})
    return render_template(
        "attendance.html",
        rows=rows,
        selected_month=selected.strftime("%Y-%m"),
        selected_label=selected.strftime("%B %Y"),
    )


@bp.route("/attendance/<int:user_id>/add", methods=["POST"])
@finance_required
def add_attendance(user_id):
    user = db.get_or_404(User, user_id)
    if user.role != "user":
        return jsonify(error="resident not found"), 404
    try:
        checkin_date = datetime.strptime(
            request.form.get("date", ""), "%Y-%m-%d"
        ).date()
    except ValueError:
        return jsonify(error="valid date is required"), 400
    if checkin_date > date.today():
        return jsonify(error="future check-ins are not allowed"), 400
    item, record, created = check_in_user(user_id, checkin_date, source="admin")
    if created:
        record_audit(
            "admin_check_in",
            "daily_check_in",
            item.id,
            {"user_id": user_id, "date": checkin_date.isoformat()},
        )
    db.session.commit()
    return {"status": "success" if created else "already", "days": record.days}


@bp.route("/attendance/<int:checkin_id>/delete", methods=["POST"])
@finance_required
def delete_attendance(checkin_id):
    item = db.get_or_404(DailyCheckIn, checkin_id)
    details = {"user_id": item.user_id, "date": item.checkin_date.isoformat()}
    remove_checkin(item)
    record_audit("delete_check_in", "daily_check_in", checkin_id, details)
    db.session.commit()
    return {"status": "success"}


@bp.route("/reports")
@finance_required
def reports():
    payments = filtered_payments().all()
    users = User.query.filter_by(role="user").order_by(User.name).all()
    months = sorted({payment.month for payment in Payment.query.all()}, key=month_sort_key)
    summary = {
        "billed": round(sum(payment.amount or 0 for payment in payments), 2),
        "collected": round(sum(payment.paid_amount or 0 for payment in payments), 2),
        "outstanding": round(sum(payment.balance for payment in payments), 2),
        "overdue": sum(
            1
            for payment in payments
            if payment.due_date
            and payment.due_date < datetime.now().date()
            and payment.status != "Paid"
        ),
    }
    return render_template(
        "reports.html",
        payments=payments,
        users=users,
        months=months,
        summary=summary,
        filters=request.args,
        user_map={user.id: user for user in User.query.all()},
        pending_transactions=PaymentTransaction.query.filter_by(
            verification_status="Pending"
        ).order_by(PaymentTransaction.created_at.desc()).all(),
        disputes=BillingDispute.query.order_by(
            BillingDispute.created_at.desc()
        ).all(),
    )


def report_rows():
    rows = []
    for payment in filtered_payments().all():
        user = db.session.get(User, payment.user_id)
        rows.append(
            [
                payment.month,
                user.name if user else "Deleted user",
                user.email if user else "",
                payment.currency or "MYR",
                payment.amount or 0,
                payment.paid_amount or 0,
                payment.balance,
                payment.status,
                payment.due_date.isoformat() if payment.due_date else "",
            ]
        )
    return rows


REPORT_HEADERS = [
    "Month",
    "User",
    "Email",
    "Currency",
    "Billed",
    "Paid",
    "Balance",
    "Status",
    "Due Date",
]


@bp.route("/reports/export.csv")
@finance_required
def export_csv():
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(REPORT_HEADERS)
    writer.writerows(report_rows())
    record_audit("export_csv", "report", details=dict(request.args))
    db.session.commit()
    return current_app.response_class(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=billing-report.csv"},
    )


@bp.route("/reports/export.xlsx")
@finance_required
def export_xlsx():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Billing Report"
    sheet.append(REPORT_HEADERS)
    for row in report_rows():
        sheet.append(row)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    record_audit("export_xlsx", "report", details=dict(request.args))
    db.session.commit()
    return send_file(
        output,
        as_attachment=True,
        download_name="billing-report.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@bp.route("/payments/<int:payment_id>/proof", methods=["POST"])
@roles_required("user")
def upload_payment_proof(payment_id):
    payment = db.get_or_404(Payment, payment_id)
    if payment.user_id != session["user"] or payment.status == "Paid":
        return jsonify(error="payment not available"), 404
    upload = request.files.get("proof")
    try:
        amount = round(float(request.form.get("amount", "0")), 2)
    except ValueError:
        return jsonify(error="invalid amount"), 400
    if not upload or amount <= 0 or amount > payment.balance:
        return jsonify(error="valid proof and amount are required"), 400
    extension = Path(secure_filename(upload.filename)).suffix.lower()
    if extension not in {".png", ".jpg", ".jpeg", ".pdf"}:
        return jsonify(error="proof must be PNG, JPG or PDF"), 400
    directory = Path(current_app.instance_path) / "payment_proofs"
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{payment.id}-{secrets.token_hex(8)}{extension}"
    upload.save(directory / filename)
    transaction = PaymentTransaction(
        payment_id=payment.id,
        amount=amount,
        method="bank_transfer",
        proof_filename=filename,
        verification_status="Pending",
    )
    db.session.add(transaction)
    notify_roles(
        {"admin", "finance"},
        "Payment proof submitted",
        f"A payment proof was submitted for {payment.month}.",
        "payment",
        "/reports",
    )
    record_audit("upload_proof", "payment_transaction", details={"payment_id": payment.id, "amount": amount})
    db.session.commit()
    return {"status": "success"}


@bp.route("/payment-transactions/<int:transaction_id>/verify", methods=["POST"])
@finance_required
def verify_payment_proof(transaction_id):
    transaction = db.get_or_404(PaymentTransaction, transaction_id)
    decision = request.form.get("decision")
    if transaction.verification_status != "Pending" or decision not in {"approve", "reject"}:
        return jsonify(error="invalid verification request"), 400
    transaction.verification_status = "Approved" if decision == "approve" else "Rejected"
    transaction.verified_by = session["user"]
    transaction.verified_at = datetime.now()
    refresh_payment_status(transaction.payment)
    notify(
        transaction.payment.user_id,
        "Payment proof reviewed",
        f"Your payment proof was {transaction.verification_status.lower()}.",
        "payment",
        "/user_dashboard",
    )
    record_audit(decision + "_proof", "payment_transaction", transaction.id)
    db.session.commit()
    return {"status": "success", "payment_status": transaction.payment.status}


@bp.route("/payment-transactions/<int:transaction_id>/proof")
@finance_required
def download_payment_proof(transaction_id):
    transaction = db.get_or_404(PaymentTransaction, transaction_id)
    if not transaction.proof_filename:
        return jsonify(error="proof not found"), 404
    path = Path(current_app.instance_path) / "payment_proofs" / transaction.proof_filename
    if not path.is_file():
        return jsonify(error="proof not found"), 404
    return send_file(path, as_attachment=True, download_name=transaction.proof_filename)


@bp.route("/payments/<int:payment_id>/dispute", methods=["POST"])
@roles_required("user")
def submit_dispute(payment_id):
    payment = db.get_or_404(Payment, payment_id)
    reason = request.form.get("reason", "").strip()
    if payment.user_id != session["user"] or len(reason) < 10:
        return jsonify(error="a detailed reason is required"), 400
    dispute = BillingDispute(payment_id=payment.id, user_id=session["user"], reason=reason)
    db.session.add(dispute)
    notify_roles(
        {"admin", "finance"},
        "New billing dispute",
        f"A dispute was submitted for {payment.month}.",
        "warning",
        "/reports",
    )
    record_audit("submit_dispute", "billing_dispute", details={"payment_id": payment.id})
    db.session.commit()
    return {"status": "success"}


@bp.route("/disputes/<int:dispute_id>/resolve", methods=["POST"])
@finance_required
def resolve_dispute(dispute_id):
    dispute = db.get_or_404(BillingDispute, dispute_id)
    status = request.form.get("status")
    response = request.form.get("response", "").strip()
    if status not in {"Resolved", "Rejected"} or not response:
        return jsonify(error="decision and response are required"), 400
    dispute.status = status
    dispute.admin_response = response
    dispute.resolved_at = datetime.now()
    notify(
        dispute.user_id,
        "Billing dispute updated",
        f"Your dispute was {status.lower()}: {response}",
        "billing",
        "/user_dashboard",
    )
    record_audit("resolve_dispute", "billing_dispute", dispute.id, {"status": status})
    db.session.commit()
    return {"status": "success"}


@bp.route("/api/v1/bills")
@all_accounts_required
def bills_api():
    query = Payment.query
    if session.get("role") in {"user", "guest"}:
        query = query.filter_by(user_id=session["user"])
    data = []
    for payment in query.order_by(Payment.id.desc()).all():
        data.append(
            {
                "id": payment.id,
                "user_id": payment.user_id,
                "month": payment.month,
                "currency": payment.currency,
                "amount": payment.amount,
                "paid_amount": payment.paid_amount,
                "balance": payment.balance,
                "status": payment.status,
                "due_date": payment.due_date.isoformat() if payment.due_date else None,
            }
        )
    return {"items": data, "count": len(data)}


@bp.route("/api/v1/billing-periods")
@finance_required
def billing_periods_api():
    return {
        "items": [
            {
                "id": bill.id,
                "month": bill.month,
                "currency": bill.currency,
                "total": bill.total,
                "due_date": bill.due_date.isoformat() if bill.due_date else None,
                "items": bill_items(bill),
            }
            for bill in Billing.query.order_by(Billing.id.desc()).all()
        ]
    }
