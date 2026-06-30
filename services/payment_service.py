from datetime import datetime

from db import db
from models import Payment, PaymentTransaction


def refresh_payment_status(payment):
    approved = sum(
        transaction.amount
        for transaction in payment.transactions
        if transaction.verification_status == "Approved"
    )
    payment.paid_amount = round(approved, 2)
    if payment.paid_amount <= 0:
        payment.status = "Pending"
    elif payment.paid_amount + 0.005 >= payment.amount:
        payment.paid_amount = round(payment.amount, 2)
        payment.status = "Paid"
    else:
        payment.status = "Partial"
    payment.updated_at = datetime.now()
    return payment


def add_transaction(
    payment,
    amount,
    method="manual",
    verification_status="Approved",
    proof_filename=None,
    provider_reference=None,
    notes=None,
    verified_by=None,
):
    if amount <= 0:
        raise ValueError("Payment amount must be greater than zero.")
    if verification_status == "Approved" and amount > payment.balance + 0.005:
        raise ValueError("Payment amount exceeds the outstanding balance.")
    transaction = PaymentTransaction(
        payment=payment,
        amount=round(amount, 2),
        method=method,
        verification_status=verification_status,
        proof_filename=proof_filename,
        provider_reference=provider_reference,
        notes=notes,
        verified_by=verified_by if verification_status == "Approved" else None,
        verified_at=datetime.now() if verification_status == "Approved" else None,
    )
    db.session.add(transaction)
    db.session.flush()
    refresh_payment_status(payment)
    return transaction
