from datetime import datetime

from db import db
from werkzeug.security import check_password_hash, generate_password_hash


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=False, unique=True, index=True)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(10), nullable=False, default="user")

    age = db.Column(db.Integer)
    gender = db.Column(db.String(10))
    block = db.Column(db.String(10))
    floor = db.Column(db.Integer)
    unit = db.Column(db.Integer)
    room = db.Column(db.Integer)
    phone = db.Column(db.String(30))
    group_name = db.Column(db.String(100))
    preferred_currency = db.Column(db.String(3), default="MYR")
    created_at = db.Column(db.DateTime, default=datetime.now)

    def __repr__(self):
        return f"<User {self.id} {self.email}>"

    def set_password(self, password):
        self.password = generate_password_hash(password)

    def check_password(self, password):
        is_hash = self.password.startswith(("scrypt:", "pbkdf2:"))
        if is_hash:
            return check_password_hash(self.password, password)

        # Upgrade legacy plaintext passwords after the first successful login.
        if self.password == password:
            self.set_password(password)
            db.session.commit()
            return True

        return False


class Billing(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    month = db.Column(db.String(20))
    electricity = db.Column(db.Float)
    water = db.Column(db.Float)
    total = db.Column(db.Float)
    currency = db.Column(db.String(3), default="MYR")
    due_date = db.Column(db.Date)
    auto_generated = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    __table_args__ = (
        db.UniqueConstraint("month", name="uq_billing_month"),
    )


class BillingItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    billing_id = db.Column(
        db.Integer, db.ForeignKey("billing.id"), nullable=False, index=True
    )
    name = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False, default=0)
    billing = db.relationship(
        "Billing", backref=db.backref("items", cascade="all, delete-orphan")
    )


class UserDays(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    days = db.Column(db.Integer, default=0)
    month = db.Column(db.String(50))

    __table_args__ = (
        db.UniqueConstraint("user_id", "month", name="uq_user_days_user_month"),
    )


class DailyCheckIn(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    checkin_date = db.Column(db.Date, nullable=False)
    checked_in_at = db.Column(db.DateTime, default=datetime.now)
    source = db.Column(db.String(20), default="self")

    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "checkin_date",
            name="uq_daily_checkin_user_date",
        ),
    )


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    amount = db.Column(db.Float)
    month = db.Column(db.String(50))
    status = db.Column(db.String(20))

    receipt_filename = db.Column(db.String(255))
    paid_amount = db.Column(db.Float, default=0)
    currency = db.Column(db.String(3), default="MYR")
    due_date = db.Column(db.Date)
    updated_at = db.Column(
        db.DateTime, default=datetime.now, onupdate=datetime.now
    )

    __table_args__ = (
        db.UniqueConstraint("user_id", "month", name="uq_payment_user_month"),
    )

    @property
    def balance(self):
        return round(max((self.amount or 0) - (self.paid_amount or 0), 0), 2)


class PaymentTransaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(
        db.Integer, db.ForeignKey("payment.id"), nullable=False, index=True
    )
    amount = db.Column(db.Float, nullable=False)
    method = db.Column(db.String(30), default="manual")
    provider_reference = db.Column(db.String(150))
    proof_filename = db.Column(db.String(255))
    verification_status = db.Column(db.String(20), default="Approved")
    notes = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.now)
    verified_at = db.Column(db.DateTime)
    verified_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    payment = db.relationship(
        "Payment", backref=db.backref("transactions", cascade="all, delete-orphan")
    )


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.String(1000), nullable=False)
    category = db.Column(db.String(30), default="info")
    link = db.Column(db.String(255))
    is_read = db.Column(db.Boolean, default=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.now)


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)
    action = db.Column(db.String(80), nullable=False)
    entity_type = db.Column(db.String(50), nullable=False)
    entity_id = db.Column(db.String(50))
    details = db.Column(db.String(1000))
    ip_address = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)


class ActiveSession(db.Model):
    token = db.Column(db.String(64), primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    ip_address = db.Column(db.String(64))
    last_seen = db.Column(db.DateTime, default=datetime.now, nullable=False, index=True)


class BillingSchedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, default="Monthly Utilities")
    enabled = db.Column(db.Boolean, default=False)
    day_of_month = db.Column(db.Integer, default=1)
    currency = db.Column(db.String(3), default="MYR")
    items_json = db.Column(db.Text, default="[]")
    send_reminders = db.Column(db.Boolean, default=True)
    last_generated_month = db.Column(db.String(20))
    updated_at = db.Column(
        db.DateTime, default=datetime.now, onupdate=datetime.now
    )


class BillingDispute(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payment.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    reason = db.Column(db.String(1000), nullable=False)
    status = db.Column(db.String(20), default="Open")
    admin_response = db.Column(db.String(1000))
    created_at = db.Column(db.DateTime, default=datetime.now)
    resolved_at = db.Column(db.DateTime)


class IntegrationSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(30), nullable=False, unique=True, index=True)
    enabled = db.Column(db.Boolean, default=False)
    encrypted_config = db.Column(db.Text, nullable=False, default="")
    last_test_status = db.Column(db.String(20))
    last_test_message = db.Column(db.String(500))
    last_tested_at = db.Column(db.DateTime)
    updated_at = db.Column(
        db.DateTime, default=datetime.now, onupdate=datetime.now
    )
    updated_by = db.Column(db.Integer, db.ForeignKey("user.id"))
