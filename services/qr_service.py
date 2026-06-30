from pathlib import Path
import re

from flask import current_app, url_for
import qrcode


def generate_qr(user_id, name, amount, month, currency="MYR"):
    data = (
        f"Smart Billing|user={user_id}|name={name}|month={month}|"
        f"currency={currency}|amount={amount:.2f}"
    )
    qr_directory = Path(current_app.root_path) / "static" / "qr"
    qr_directory.mkdir(parents=True, exist_ok=True)
    month_slug = re.sub(r"[^A-Za-z0-9_-]+", "-", month).strip("-").lower()
    filename = f"payment-{user_id}-{month_slug}.png"
    qrcode.make(data).save(qr_directory / filename)
    return url_for("static", filename=f"qr/{filename}")
