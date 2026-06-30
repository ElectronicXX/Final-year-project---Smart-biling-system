import os
from datetime import date
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

database_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
database_file.close()
os.environ["DATABASE_URL"] = f"sqlite:///{database_file.name.replace(os.sep, '/')}"
os.environ["SECRET_KEY"] = "test-secret-key"

from app import app as bootstrap_app, create_app
from db import db
from models import (
    Billing,
    BillingItem,
    BillingSchedule,
    DailyCheckIn,
    IntegrationSetting,
    Notification,
    Payment,
    PaymentTransaction,
    User,
    UserDays,
)
from services.automation_service import generate_scheduled_bill
from services.billing_service import current_month


class SmartBillingTestCase(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        with bootstrap_app.app_context():
            db.session.remove()
            db.engine.dispose()
        Path(database_file.name).unlink(missing_ok=True)

    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                "MAIL_SUPPRESS_SEND": True,
                "MAIL_USERNAME": None,
                "MAIL_PASSWORD": None,
            }
        )
        self.client = self.app.test_client()
        with self.app.app_context():
            db.drop_all()
            db.create_all()
            admin = User(name="Admin", email="admin@example.com", role="admin")
            admin.set_password("password123")
            resident = User(name="Resident", email="user@example.com", role="user")
            resident.set_password("password123")
            other = User(name="Other", email="other@example.com", role="user")
            other.set_password("password123")
            db.session.add_all([admin, resident, other])
            db.session.commit()
            self.admin_id = admin.id
            self.user_id = resident.id
            self.other_id = other.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

    def sign_in_as(self, user_id, role):
        with self.client.session_transaction() as session:
            session["user"] = user_id
            session["role"] = role
            session["_csrf_token"] = "test-csrf-token"

    @property
    def csrf_headers(self):
        return {"X-CSRF-Token": "test-csrf-token"}

    def create_current_bill(self):
        with self.app.app_context():
            db.session.add(
                Billing(
                    month=current_month(),
                    electricity=600,
                    water=300,
                    total=900,
                )
            )
            db.session.add_all(
                [
                    UserDays(user_id=self.user_id, month=current_month(), days=20),
                    UserDays(user_id=self.other_id, month=current_month(), days=10),
                ]
            )
            db.session.commit()

    def test_admin_route_requires_authentication(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/"))

    @patch("services.server_monitor_service.psutil.cpu_percent", return_value=12.5)
    @patch("services.server_monitor_service.psutil.virtual_memory")
    def test_server_metrics_are_admin_only(self, virtual_memory, _cpu_percent):
        virtual_memory.return_value.percent = 40.0
        virtual_memory.return_value.used = 4 * 1024**3
        virtual_memory.return_value.total = 10 * 1024**3

        self.sign_in_as(self.user_id, "user")
        forbidden = self.client.get("/api/server_metrics")
        self.assertEqual(forbidden.status_code, 403)

        self.sign_in_as(self.admin_id, "admin")
        response = self.client.get("/api/server_metrics")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["cpu_percent"], 12.5)
        self.assertEqual(response.json["ram_percent"], 40.0)
        self.assertEqual(response.json["active_visitors"], 1)
        self.assertGreater(response.json["max_concurrent_users"], 0)

    def test_login_returns_role_specific_destination(self):
        with self.client.session_transaction() as session:
            session["_csrf_token"] = "test-csrf-token"
        response = self.client.post(
            "/",
            data={
                "email": "user@example.com",
                "password": "password123",
                "_csrf_token": "test-csrf-token",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["redirect"], "/user_dashboard")

    def test_post_without_csrf_is_rejected(self):
        self.sign_in_as(self.admin_id, "admin")
        response = self.client.post(
            "/generate_bill",
            data={"month": current_month(), "electricity": "10", "water": "5"},
        )
        self.assertEqual(response.status_code, 400)

    def test_monthly_bill_allocation_and_payment(self):
        self.create_current_bill()
        self.sign_in_as(self.user_id, "user")
        response = self.client.post(
            "/confirm_payment", headers=self.csrf_headers
        )
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            payment = Payment.query.filter_by(
                user_id=self.user_id, month=current_month()
            ).one()
            self.assertEqual(payment.amount, 600)
            self.assertEqual(payment.status, "Paid")
            self.assertTrue(payment.receipt_filename)
            receipt = Path(self.app.root_path) / "static" / "pdf" / payment.receipt_filename
            self.assertTrue(receipt.exists())
            receipt.unlink(missing_ok=True)

    def test_daily_checkin_is_idempotent(self):
        self.sign_in_as(self.user_id, "user")
        first = self.client.post("/checkin", headers=self.csrf_headers)
        second = self.client.post("/checkin", headers=self.csrf_headers)
        self.assertEqual(first.json["status"], "success")
        self.assertEqual(second.json["status"], "already")
        self.assertEqual(second.json["days"], 1)

    def test_admin_can_add_and_remove_checkin_with_days_sync(self):
        self.sign_in_as(self.admin_id, "admin")
        today = date.today().isoformat()
        added = self.client.post(
            f"/attendance/{self.user_id}/add",
            data={"date": today},
            headers=self.csrf_headers,
        )
        self.assertEqual(added.status_code, 200)
        self.assertEqual(added.json["status"], "success")
        with self.app.app_context():
            checkin = DailyCheckIn.query.filter_by(user_id=self.user_id).one()
            checkin_id = checkin.id
            days = UserDays.query.filter_by(
                user_id=self.user_id, month=current_month()
            ).one()
            self.assertEqual(days.days, 1)
            self.assertEqual(checkin.source, "admin")
        removed = self.client.post(
            f"/attendance/{checkin_id}/delete",
            headers=self.csrf_headers,
        )
        self.assertEqual(removed.status_code, 200)
        with self.app.app_context():
            days = UserDays.query.filter_by(
                user_id=self.user_id, month=current_month()
            ).one()
            self.assertEqual(days.days, 0)

    def test_attendance_page_and_dashboard_status(self):
        self.sign_in_as(self.user_id, "user")
        self.client.post("/checkin", headers=self.csrf_headers)
        dashboard = self.client.get("/user_dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn(b"Checked In Today", dashboard.data)
        self.sign_in_as(self.admin_id, "admin")
        attendance = self.client.get("/attendance")
        self.assertEqual(attendance.status_code, 200)
        self.assertIn(b"Resident Attendance", attendance.data)

    def test_user_cannot_download_another_users_receipt(self):
        with self.app.app_context():
            payment = Payment(
                user_id=self.other_id,
                month=current_month(),
                amount=100,
                status="Paid",
                receipt_filename="private.pdf",
            )
            db.session.add(payment)
            db.session.commit()
            payment_id = payment.id
        self.sign_in_as(self.user_id, "user")
        response = self.client.get(f"/download/receipt/{payment_id}")
        self.assertEqual(response.status_code, 404)

    def test_partial_payment_then_full_payment(self):
        self.create_current_bill()
        self.sign_in_as(self.user_id, "user")
        first = self.client.post(
            "/confirm_payment",
            data={"amount": "200"},
            headers=self.csrf_headers,
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json["payment_status"], "Partial")
        self.assertEqual(first.json["balance"], 400)
        second = self.client.post(
            "/confirm_payment",
            data={"amount": "400"},
            headers=self.csrf_headers,
        )
        self.assertEqual(second.json["payment_status"], "Paid")
        with self.app.app_context():
            payment = Payment.query.filter_by(user_id=self.user_id).one()
            self.assertEqual(payment.paid_amount, 600)
            self.assertEqual(len(payment.transactions), 2)
            receipt = Path(self.app.root_path) / "static" / "pdf" / payment.receipt_filename
            receipt.unlink(missing_ok=True)

    def test_itemized_bill_generation(self):
        self.sign_in_as(self.admin_id, "admin")
        response = self.client.post(
            "/generate_bill",
            data={
                "month": current_month(),
                "currency": "MYR",
                "due_date": date.today().isoformat(),
                "item_name": ["Electricity", "Internet", "Cleaning"],
                "item_amount": ["100", "50", "25"],
            },
            headers=self.csrf_headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["total"], 175)
        with self.app.app_context():
            bill = Billing.query.filter_by(month=current_month()).one()
            self.assertEqual(len(bill.items), 3)

    def test_finance_role_permissions(self):
        with self.app.app_context():
            finance = User(name="Finance", email="finance@example.com", role="finance")
            finance.set_password("password123")
            db.session.add(finance)
            db.session.commit()
            finance_id = finance.id
        self.sign_in_as(finance_id, "finance")
        self.assertEqual(self.client.get("/billing").status_code, 200)
        self.assertEqual(self.client.get("/reports").status_code, 200)
        self.assertEqual(self.client.get("/users").status_code, 302)
        self.assertEqual(self.client.get("/audit").status_code, 302)

    def test_report_exports(self):
        self.create_current_bill()
        with self.app.app_context():
            db.session.add(
                Payment(
                    user_id=self.user_id,
                    month=current_month(),
                    amount=600,
                    paid_amount=200,
                    status="Partial",
                    currency="MYR",
                )
            )
            db.session.commit()
        self.sign_in_as(self.admin_id, "admin")
        csv_response = self.client.get("/reports/export.csv")
        xlsx_response = self.client.get("/reports/export.xlsx")
        self.assertEqual(csv_response.status_code, 200)
        self.assertIn(b"Resident", csv_response.data)
        self.assertEqual(xlsx_response.status_code, 200)
        self.assertTrue(xlsx_response.data.startswith(b"PK"))

    def test_user_api_only_returns_own_bills(self):
        with self.app.app_context():
            db.session.add_all(
                [
                    Payment(user_id=self.user_id, month="May 2026", amount=10, status="Pending"),
                    Payment(user_id=self.other_id, month="May 2026", amount=20, status="Pending"),
                ]
            )
            db.session.commit()
        self.sign_in_as(self.user_id, "user")
        response = self.client.get("/api/v1/bills")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["count"], 1)
        self.assertEqual(response.json["items"][0]["user_id"], self.user_id)

    def test_payment_proof_review(self):
        with self.app.app_context():
            payment = Payment(
                user_id=self.user_id,
                month=current_month(),
                amount=100,
                paid_amount=0,
                status="Pending",
                currency="MYR",
            )
            db.session.add(payment)
            db.session.commit()
            payment_id = payment.id
        self.sign_in_as(self.user_id, "user")
        upload = self.client.post(
            f"/payments/{payment_id}/proof",
            data={"amount": "40", "proof": (BytesIO(b"proof"), "proof.png")},
            content_type="multipart/form-data",
            headers=self.csrf_headers,
        )
        self.assertEqual(upload.status_code, 200)
        with self.app.app_context():
            transaction = PaymentTransaction.query.one()
            transaction_id = transaction.id
            proof = Path(self.app.instance_path) / "payment_proofs" / transaction.proof_filename
        self.sign_in_as(self.admin_id, "admin")
        review = self.client.post(
            f"/payment-transactions/{transaction_id}/verify",
            data={"decision": "approve"},
            headers=self.csrf_headers,
        )
        self.assertEqual(review.status_code, 200)
        self.assertEqual(review.json["payment_status"], "Partial")
        proof.unlink(missing_ok=True)

    def test_scheduled_bill_generation(self):
        with self.app.app_context():
            schedule = BillingSchedule(
                enabled=True,
                day_of_month=1,
                currency="MYR",
                items_json=json.dumps(
                    [{"name": "Electricity", "amount": 120}, {"name": "Water", "amount": 30}]
                ),
            )
            db.session.add(schedule)
            db.session.commit()
            bill = generate_scheduled_bill(schedule, today=date.today())
            self.assertIsNotNone(bill)
            self.assertEqual(bill.total, 150)
            self.assertTrue(bill.auto_generated)
            self.assertEqual(BillingItem.query.count(), 2)
            self.assertGreater(Notification.query.count(), 0)

    def test_integration_settings_are_admin_only(self):
        self.sign_in_as(self.user_id, "user")
        self.assertEqual(self.client.get("/integrations").status_code, 302)
        self.sign_in_as(self.admin_id, "admin")
        response = self.client.get("/integrations")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Integration Center", response.data)

    def test_integration_secret_is_encrypted_and_masked(self):
        self.sign_in_as(self.admin_id, "admin")
        response = self.client.post(
            "/integrations/stripe",
            data={
                "enabled": "on",
                "secret_key": "sk_test_private_value",
                "publishable_key": "pk_test_public",
                "webhook_secret": "whsec_private_value",
            },
            headers=self.csrf_headers,
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            setting = IntegrationSetting.query.filter_by(provider="stripe").one()
            self.assertTrue(setting.enabled)
            self.assertNotIn("sk_test_private_value", setting.encrypted_config)
        page = self.client.get("/integrations")
        self.assertNotIn(b"sk_test_private_value", page.data)
        self.assertIn(b"********alue", page.data)

    def test_masked_secret_is_preserved_and_connection_can_be_tested(self):
        self.sign_in_as(self.admin_id, "admin")
        self.client.post(
            "/integrations/stripe",
            data={"enabled": "on", "secret_key": "sk_test_keepme"},
            headers=self.csrf_headers,
        )
        self.client.post(
            "/integrations/stripe",
            data={"enabled": "on", "secret_key": "********epme"},
            headers=self.csrf_headers,
        )
        with patch(
            "routes.portal.test_provider", return_value="Stripe API authenticated."
        ):
            response = self.client.post(
                "/integrations/stripe/test", headers=self.csrf_headers
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["success"])
        with self.app.app_context():
            setting = IntegrationSetting.query.filter_by(provider="stripe").one()
            self.assertEqual(setting.last_test_status, "success")
            from services.integration_service import decrypt_config

            self.assertEqual(decrypt_config(setting.encrypted_config)["secret_key"], "sk_test_keepme")

    def test_smtp_test_requires_enabled_setting(self):
        self.sign_in_as(self.admin_id, "admin")
        self.client.post(
            "/integrations/smtp",
            data={
                "server": "smtp.gmail.com",
                "port": "587",
                "username": "sender@example.com",
                "password": "app-password",
                "sender": "sender@example.com",
                "use_tls": "on",
            },
            headers=self.csrf_headers,
        )
        response = self.client.post("/integrations/smtp/test", headers=self.csrf_headers)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json["success"])
        self.assertIn("disabled", response.json["message"])

    def test_email_message_uses_managed_sender(self):
        self.sign_in_as(self.admin_id, "admin")
        self.client.post(
            "/integrations/smtp",
            data={
                "enabled": "on",
                "server": "smtp.gmail.com",
                "port": "587",
                "username": "managed@example.com",
                "password": "app-password",
                "sender": "managed@example.com",
                "use_tls": "on",
            },
            headers=self.csrf_headers,
        )
        with self.app.app_context():
            from flask_mail import Message
            from services.email_service import configure_message

            message = Message(subject="Test", recipients=["user@example.com"])
            message.sender = "old@example.com"
            configure_message(message)
            self.assertEqual(message.sender, "managed@example.com")

    def test_saved_disabled_smtp_does_not_fallback_to_env(self):
        self.sign_in_as(self.admin_id, "admin")
        self.client.post(
            "/integrations/smtp",
            data={
                "server": "smtp.gmail.com",
                "port": "587",
                "username": "managed@example.com",
                "password": "app-password",
                "sender": "managed@example.com",
                "use_tls": "on",
            },
            headers=self.csrf_headers,
        )
        with self.app.app_context():
            from services.email_service import effective_mail_config, mail_is_configured

            self.assertEqual(effective_mail_config(), {})
            self.assertFalse(mail_is_configured())

    def test_billing_email_template_is_modern_and_concise(self):
        with self.app.app_context():
            from services.email_service import billing_email_html

            html = billing_email_html(
                title="Your bill is ready",
                subtitle="Review your latest shared bill.",
                amount=123.45,
                month="June 2026",
                status="Pending",
                accent="MYR",
                details=[("Bill month", "June 2026"), ("Payment status", "Pending")],
            )
            self.assertIn("Smart Billing", html)
            self.assertIn("border-radius:999px", html)
            self.assertIn("MYR 123.45", html)
            self.assertIn("View bill", html)


if __name__ == "__main__":
    unittest.main()
