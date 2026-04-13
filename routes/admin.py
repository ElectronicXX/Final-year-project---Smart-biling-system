import random
from services.email_service import send_receipt_email, send_reminder_email
from services.pdf_service import generate_pdf
from flask import Blueprint, render_template, send_file, session, redirect, request
from models import User, Billing, UserDays, Payment
from db import db
from datetime import date, datetime
from services.qr_service import generate_qr
from services.pdf_service import generate_pdf

bp = Blueprint('admin', __name__)

def is_admin():
    return session.get("role") == "admin"

def is_user():
    return session.get("role") == "user"

@bp.route("/dashboard")
def dashboard():
    if not is_admin():
        return redirect("/user_dashboard")

    users = User.query.all()
    payments = Payment.query.all()

    paid_count = len([p for p in payments if p.status == "Paid"])

    history = Billing.query.all()
    months = [h.month for h in history]
    totals = [h.total for h in history]

    return render_template(
        "dashboard.html",
        users=users,
        paid_count=paid_count,
        months=months,
        totals=totals
    )

@bp.route("/api/dashboard_data")
def dashboard_data():
    if not is_admin():
        return {"error": "unauthorized"}

    users = User.query.all()
    payments = Payment.query.all()
    history = Billing.query.all()

    paid_count = len([p for p in payments if p.status == "Paid"])

    months = [h.month for h in history]
    totals = [h.total for h in history]

    return {
        "users": len(users),
        "paid": paid_count,
        "pending": len(users) - paid_count,
        "months": months,
        "totals": totals
    }
import numpy as np

@bp.route("/api/predict")
def predict():

    history = Billing.query.all()
    totals = [h.total for h in history]

    if len(totals) < 2:
        return {"predicted": []}

    x = np.arange(len(totals))
    y = np.array(totals)

    coef = np.polyfit(x, y, 1)

    future_x = np.arange(len(totals), len(totals)+3)
    predicted = coef[0] * future_x + coef[1]

    return {
        "predicted": predicted.tolist()
    }

@bp.route("/users")
def users():
    if not is_admin():
        return redirect("/user_dashboard")

    all_users = User.query.all()
    return render_template("users.html", users=all_users)


@bp.route("/billing")
def billing():
    if not is_admin():
        return redirect("/user_dashboard")

    import random

    current_month = datetime.now().strftime("%B %Y")
    selected_month = request.args.get("month") or current_month

    bill = Billing.query.filter_by(month=selected_month).first()

    if not bill and selected_month == current_month:
        electricity = random.randint(300, 800)
        water = random.randint(100, 300)
        total = electricity + water

        bill = Billing(
            month=current_month,
            electricity=electricity,
            water=water,
            total=total
        )

        db.session.add(bill)
        db.session.commit()

    users = User.query.all()

    data = []

    for user in users:
        record = UserDays.query.filter_by(user_id=user.id, month=selected_month).first()
        days = record.days if record else 0
        total_days = sum([d.days for d in UserDays.query.filter_by(month=selected_month).all()])
        amount = (days / total_days) * bill.total if (bill and total_days > 0) else 0
        amount = round(amount, 2)
        payment = Payment.query.filter_by(user_id=user.id, month=selected_month).first()
        status = payment.status if payment else "Pending"

        data.append({
            "id": user.id,
            "name": user.name,
            "amount": amount,
            "status": status
        })

    history = Billing.query.all()
    months = list(set([h.month for h in history]))
    totals = [h.total for h in history]

    return render_template(
        "billing.html",
        bill=bill,
        history=history,
        months=months,
        totals=totals,
        selected_month=selected_month,
        data=data
    )

@bp.route("/send_reminder/<int:user_id>")
def send_reminder(user_id):
    user = User.query.get(user_id)
    if not user:
        return {"status": "error"}
    month = datetime.now().strftime("%B %Y")
    bill = Billing.query.filter_by(month=month).first()
    user_days = UserDays.query.filter_by(user_id=user_id, month=month).first()
    days = user_days.days if user_days else 0
    total_days = sum([d.days for d in UserDays.query.filter_by(month=month).all()])
    amount = (days / total_days) * bill.total if (bill and total_days > 0) else 0
    amount = round(amount, 2)

    send_reminder_email(
        user.email,
        amount,
        month
    )

    return {"status": "success"}

@bp.route("/generate_bill")
def generate_bill():
    if not is_admin():
        return {"status": "error"}
    month = datetime.now().strftime("%B %Y")
    electricity = random.randint(300, 1000)
    water = random.randint(100, 400)
    total = electricity + water
    old = Billing.query.filter_by(month=month).first()
    if old:
        db.session.delete(old)

    bill = Billing(
        month=month,
        electricity=electricity,
        water=water,
        total=total
    )

    db.session.add(bill)
    db.session.commit()

    return {"status": "success"}

#add_user, delete user, edit user
@bp.route("/add_user", methods=["POST"])
def add_user():
    name = request.form["name"]
    email = request.form["email"]
    password = request.form["password"]
    role = request.form["role"]
    user = User(name=name, email=email, password=password, role=role)
    db.session.add(user)
    db.session.commit()

    return redirect("/users")

@bp.route("/edit_user/<int:id>", methods=["POST"])
def edit_user(id):
    user = User.query.get(id)
    user.name = request.form["name"]
    user.email = request.form["email"]
    user.password = request.form["password"]
    user.role = request.form["role"]

    db.session.commit()

    return redirect("/users")

@bp.route("/delete_user/<int:id>")
def delete_user(id):
    user = User.query.get(id)

    db.session.delete(user)
    db.session.commit()

    return redirect("/users")

@bp.route("/user_dashboard")
def user_dashboard():
    user_id = session["user"]
    user = User.query.get(user_id)
    month = datetime.now().strftime("%B %Y")
    bill = Billing.query.filter_by(month=month).first()
    days = UserDays.query.filter_by(user_id=user_id, month=month).first()
    total_days = sum([d.days for d in UserDays.query.filter_by(month=month).all()])
    amount = (days.days / total_days) * bill.total if days and total_days else 0
    amount = round(amount, 2)
    payment = Payment.query.filter_by(user_id=user_id, month=month).first()
    status = payment.status if payment else "Pending"
    payments = Payment.query.filter_by(user_id=user_id).all()

    history = []
    for p in payments:
        history.append({
            "month": p.month,
            "amount": p.amount,
            "status": p.status,
            "pdf": f"{user.name}_invoice.pdf"
        })

    months = [h["month"] for h in history]
    totals = [h["amount"] for h in history]

    qr_path = generate_qr(user.name, amount)

    return render_template(
        "user_dashboard.html",
        user=user,
        amount=amount,
        status=status,
        month=month,
        qr=qr_path,
        history=history,
        months=months,
        totals=totals
    )

@bp.route("/download/<filename>")
def download_file(filename):
    return send_file(f"static/pdf/{filename}", as_attachment=True)

@bp.route("/checkin")
def checkin():
    if "user" not in session:
        return {"status": "error"}
    
    user_id = session["user"]
    month = datetime.now().strftime("%B %Y")
    today = date.today()
    record = UserDays.query.filter_by(user_id=user_id, month=month).first()

    if record and hasattr(record, "last_checkin") and record.last_checkin == today:
        return {"status": "already", "days": record.days}

    if record:
        record.days += 1
        record.last_checkin = today
    else:
        record = UserDays(user_id=user_id, days=1, month=month)
        record.last_checkin = today
        db.session.add(record)

    db.session.commit()

    return {"status": "success", "days": record.days}

@bp.route("/user_billing")
def user_billing():
    if not is_user():
        return redirect("/dashboard")

    user_id = session["user"]
    user = User.query.get(user_id)
    days = UserDays.query.filter_by(user_id=user_id).first()
    bill = Billing.query.order_by(Billing.id.desc()).first()
    total_days = sum([d.days for d in UserDays.query.all()])
    amount = (days.days / total_days) * bill.total if total_days > 0 else 0
    amount = round(amount, 2)
    qr_path = generate_qr(user.name, amount)

    return render_template("user_billing.html", user=user, amount=amount, qr=qr_path)

@bp.route("/pay")
def pay():
    if not is_user():
        return redirect("/dashboard")

    user_id = session["user"]
    user = User.query.get(user_id)
    bill = Billing.query.order_by(Billing.id.desc()).first()
    days = UserDays.query.filter_by(user_id=user_id).first()
    total_days = sum([d.days for d in UserDays.query.all()])
    amount = (days.days / total_days) * bill.total if total_days > 0 else 0
    amount = round(amount, 2)
    qr_path = generate_qr(user.name, amount)

    return render_template("payment.html", user=user, amount=amount, qr=qr_path)


@bp.route("/confirm_payment")
def confirm_payment():
    user_id = session["user"]

    payment = Payment.query.filter_by(user_id=user_id).order_by(Payment.id.desc()).first()
    month = datetime.now().strftime("%B %Y")
    bill = Billing.query.order_by(Billing.id.desc()).first()
    record = UserDays.query.filter_by(user_id=user_id, month=month).first()
    days = record.days if record else 0
    total_days = sum([d.days for d in UserDays.query.filter_by(month=month).all()])
    amount = (days / total_days) * bill.total if total_days > 0 else 0
    amount = round(amount, 2)
    payment = Payment.query.filter_by(user_id=user_id, month=month).first()

    if not payment:
        payment = Payment(
            user_id=user_id,
            amount=amount,
            month=month,
            status="Paid"
        )
        db.session.add(payment)
    else:
        payment.amount = amount
        payment.status = "Paid"

    db.session.commit()

    user = User.query.get(user_id)
    pdf_path = generate_pdf(user.name, amount)

    send_receipt_email(
        user.email,
        amount,
        month,
        pdf_path
    )

    return {"status": "success"}