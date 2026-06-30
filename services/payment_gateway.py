import base64
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import current_app

from services.integration_service import get_config, get_setting


class PaymentGatewayError(RuntimeError):
    pass


def create_checkout(payment, user):
    provider = next(
        (
            name
            for name in ("stripe", "paypal", "razorpay")
            if get_setting(name) and get_setting(name).enabled
        ),
        current_app.config.get("PAYMENT_PROVIDER", "manual"),
    )
    if provider == "manual":
        return {
            "provider": "manual",
            "checkout_url": None,
            "message": "Manual and proof-upload payments are enabled.",
        }
    config = get_config(provider)
    if provider == "stripe":
        key = config.get("secret_key")
        if not key:
            raise PaymentGatewayError("Stripe secret key is not configured.")
        data = urlencode(
            {
                "mode": "payment",
                "success_url": f"{current_app.config['APP_BASE_URL']}/user_dashboard?payment=success",
                "cancel_url": f"{current_app.config['APP_BASE_URL']}/user_dashboard?payment=cancelled",
                "line_items[0][price_data][currency]": payment.currency.lower(),
                "line_items[0][price_data][product_data][name]": f"Smart Billing {payment.month}",
                "line_items[0][price_data][unit_amount]": int(payment.balance * 100),
                "line_items[0][quantity]": 1,
                "client_reference_id": str(payment.id),
                "customer_email": user.email,
            }
        ).encode()
        token = base64.b64encode(f"{key}:".encode()).decode()
        request = Request(
            "https://api.stripe.com/v1/checkout/sessions",
            data=data,
            headers={
                "Authorization": f"Basic {token}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        with urlopen(request, timeout=15) as response:
            result = json.loads(response.read().decode())
        return {"provider": "stripe", "checkout_url": result["url"]}
    raise PaymentGatewayError(
        f"{provider.title()} is configured and verified, but hosted checkout is not yet implemented."
    )
