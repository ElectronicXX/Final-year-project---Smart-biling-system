import os
import secrets
import logging
import time
from datetime import date

from flask import Flask, jsonify, request, session
from dotenv import load_dotenv
from db import db
from extensions import mail
from security import generate_csrf_token
from services.migration_service import upgrade_schema

load_dotenv()

class IgnoreAPI(logging.Filter):
    def filter(self, record):
        return '/api/' not in record.getMessage()


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY") or secrets.token_hex(32),
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", "sqlite:///app.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAIL_SERVER=os.getenv("MAIL_SERVER", "smtp.gmail.com"),
        MAIL_PORT=int(os.getenv("MAIL_PORT", "587")),
        MAIL_USERNAME=os.getenv("MAIL_USERNAME"),
        MAIL_PASSWORD=os.getenv("MAIL_PASSWORD"),
        MAIL_USE_TLS=os.getenv("MAIL_USE_TLS", "true").lower() == "true",
        MAIL_DEFAULT_SENDER=os.getenv("MAIL_DEFAULT_SENDER")
        or os.getenv("MAIL_USERNAME"),
        APP_BASE_URL=os.getenv("APP_BASE_URL", "http://127.0.0.1:5000"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").lower()
        == "true",
        MAX_CONTENT_LENGTH=int(os.getenv("PAYMENT_PROOF_MAX_MB", "5"))
        * 1024
        * 1024,
        AUTO_GENERATE_BILLS=os.getenv("AUTO_GENERATE_BILLS", "false").lower()
        == "true",
        DEFAULT_CURRENCY=os.getenv("DEFAULT_CURRENCY", "MYR").upper(),
        PAYMENT_PROVIDER=os.getenv("PAYMENT_PROVIDER", "manual").lower(),
        PAYMENT_PROOF_MAX_MB=int(os.getenv("PAYMENT_PROOF_MAX_MB", "5")),
        ACTIVITY_HEARTBEAT_SECONDS=int(
            os.getenv("ACTIVITY_HEARTBEAT_SECONDS", "30")
        ),
    )
    if test_config:
        app.config.update(test_config)

    mail.init_app(app)
    db.init_app(app)

    from routes import auth, admin, api, portal

    app.register_blueprint(auth.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(api.bp)
    app.register_blueprint(portal.bp)

    @app.context_processor
    def inject_csrf_token():
        from models import Notification, User

        account = (
            db.session.get(User, session["user"]) if session.get("user") else None
        )
        unread_count = (
            Notification.query.filter_by(
                user_id=session["user"], is_read=False
            ).count()
            if session.get("user")
            else 0
        )
        return {
            "csrf_token": generate_csrf_token,
            "current_account": account,
            "unread_count": unread_count,
        }

    @app.before_request
    def protect_csrf():
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return None
        expected = session.get("_csrf_token")
        supplied = request.form.get("_csrf_token") or request.headers.get(
            "X-CSRF-Token"
        )
        if not expected or not supplied or not secrets.compare_digest(expected, supplied):
            if request.path.startswith("/api/") or request.is_json:
                return jsonify(error="invalid CSRF token"), 400
            return "Invalid CSRF token", 400
        return None

    @app.before_request
    def track_active_session():
        if not session.get("user") or request.path.startswith("/static/"):
            return None

        now = int(time.time())
        if now - session.get("_last_activity_ping", 0) < app.config[
            "ACTIVITY_HEARTBEAT_SECONDS"
        ]:
            return None

        from services.server_monitor_service import record_session_activity

        token = session.setdefault("_visitor_token", secrets.token_hex(24))
        record_session_activity(token, session["user"], request.remote_addr)
        session["_last_activity_ping"] = now
        return None

    with app.app_context():
        upgrade_schema()

    @app.cli.command("generate-monthly-bills")
    def generate_monthly_bills_command():
        from services.automation_service import run_due_schedules

        generated = run_due_schedules()
        print(f"Generated {len(generated)} billing period(s).")

    @app.cli.command("send-overdue-reminders")
    def send_overdue_reminders_command():
        from models import Payment, User
        from services.email_service import send_overdue_email
        from services.notification_service import notify

        sent = 0
        overdue = Payment.query.filter(
            Payment.due_date < date.today(), Payment.status != "Paid"
        ).all()
        for payment in overdue:
            user = db.session.get(User, payment.user_id)
            if not user:
                continue
            send_overdue_email(
                user.email,
                payment.balance,
                payment.month,
                payment.due_date,
                payment.currency or "MYR",
            )
            notify(
                user.id,
                "Overdue bill",
                f"Your {payment.month} balance is overdue.",
                "warning",
                "/user_dashboard",
            )
            sent += 1
        db.session.commit()
        print(f"Processed {sent} overdue reminder(s).")

    app.extensions["last_automation_check"] = None

    @app.before_request
    def run_automatic_billing():
        if not app.config.get("AUTO_GENERATE_BILLS"):
            return None
        today = date.today()
        if app.extensions.get("last_automation_check") == today:
            return None
        from services.automation_service import run_due_schedules

        run_due_schedules(today)
        app.extensions["last_automation_check"] = today
        return None

    return app


app = create_app()

log = logging.getLogger("werkzeug")
log.addFilter(IgnoreAPI())

if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
