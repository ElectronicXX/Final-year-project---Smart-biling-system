import base64
from datetime import datetime
import hashlib
import json
import smtplib
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

from db import db
from models import IntegrationSetting


PROVIDERS = {
    "smtp": {
        "label": "SMTP Email",
        "icon": "envelope",
        "fields": [
            ("server", "Mail server", "text", False),
            ("port", "Port", "number", False),
            ("username", "Username", "text", False),
            ("password", "Password / app password", "password", True),
            ("sender", "Default sender", "email", False),
            ("use_tls", "Use STARTTLS", "checkbox", False),
        ],
    },
    "stripe": {
        "label": "Stripe",
        "icon": "credit-card",
        "fields": [
            ("secret_key", "Secret key", "password", True),
            ("publishable_key", "Publishable key", "text", False),
            ("webhook_secret", "Webhook signing secret", "password", True),
        ],
    },
    "paypal": {
        "label": "PayPal",
        "icon": "paypal",
        "fields": [
            ("client_id", "Client ID", "text", False),
            ("client_secret", "Client secret", "password", True),
            ("environment", "Environment (sandbox/live)", "text", False),
            ("webhook_id", "Webhook ID", "text", False),
        ],
    },
    "razorpay": {
        "label": "Razorpay",
        "icon": "money-check-alt",
        "fields": [
            ("key_id", "Key ID", "text", False),
            ("key_secret", "Key secret", "password", True),
            ("webhook_secret", "Webhook secret", "password", True),
        ],
    },
    "twilio_sms": {
        "label": "Twilio SMS",
        "icon": "sms",
        "fields": [
            ("account_sid", "Account SID", "text", False),
            ("auth_token", "Auth token", "password", True),
            ("from_number", "Sender phone number", "text", False),
        ],
    },
    "whatsapp": {
        "label": "WhatsApp Cloud API",
        "icon": "whatsapp",
        "fields": [
            ("access_token", "Permanent access token", "password", True),
            ("phone_number_id", "Phone number ID", "text", False),
            ("business_account_id", "Business account ID", "text", False),
            ("verify_token", "Webhook verify token", "password", True),
        ],
    },
}


def _fernet():
    secret = str(current_app.config["SECRET_KEY"]).encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def encrypt_config(config):
    raw = json.dumps(config, separators=(",", ":")).encode()
    return _fernet().encrypt(raw).decode()


def decrypt_config(value):
    if not value:
        return {}
    try:
        return json.loads(_fernet().decrypt(value.encode()).decode())
    except (InvalidToken, ValueError, json.JSONDecodeError):
        current_app.logger.error("Unable to decrypt integration configuration.")
        return {}


def get_setting(provider):
    return IntegrationSetting.query.filter_by(provider=provider).first()


def _environment_config(provider):
    if provider != "smtp":
        return {}
    return {
        "server": current_app.config.get("MAIL_SERVER"),
        "port": current_app.config.get("MAIL_PORT", 587),
        "username": current_app.config.get("MAIL_USERNAME"),
        "password": current_app.config.get("MAIL_PASSWORD"),
        "sender": current_app.config.get("MAIL_DEFAULT_SENDER"),
        "use_tls": current_app.config.get("MAIL_USE_TLS", True),
    }


def get_config(provider, include_disabled=False):
    setting = get_setting(provider)
    if not setting or (not setting.enabled and not include_disabled):
        return {}
    return decrypt_config(setting.encrypted_config)


def save_config(provider, values, enabled, actor_id):
    if provider not in PROVIDERS:
        raise ValueError("Unknown integration provider.")
    setting = get_setting(provider) or IntegrationSetting(provider=provider)
    existing = (
        decrypt_config(setting.encrypted_config)
        if setting.encrypted_config
        else _environment_config(provider)
    )
    for name, _, field_type, secret in PROVIDERS[provider]["fields"]:
        value = values.get(name)
        if field_type == "checkbox":
            existing[name] = bool(value)
        elif value not in (None, "") and not str(value).startswith("********"):
            existing[name] = str(value).strip()
        elif not secret:
            existing[name] = ""
    setting.enabled = enabled
    setting.encrypted_config = encrypt_config(existing)
    setting.updated_by = actor_id
    db.session.add(setting)
    return setting


def masked_config(provider):
    setting = get_setting(provider)
    config = (
        decrypt_config(setting.encrypted_config)
        if setting and setting.encrypted_config
        else _environment_config(provider)
    )
    fields = {}
    for name, _, field_type, secret in PROVIDERS[provider]["fields"]:
        value = config.get(name, "")
        if secret and value:
            fields[name] = "********" + value[-4:]
        else:
            fields[name] = value
    return setting, fields


def _json_request(url, headers=None, data=None):
    payload = urlencode(data).encode() if data is not None else None
    request = Request(url, data=payload, headers=headers or {})
    try:
        with urlopen(request, timeout=12) as response:
            body = response.read().decode()
            return response.status, json.loads(body) if body else {}
    except HTTPError as error:
        body = error.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {error.code}: {body[:180]}") from error
    except URLError as error:
        raise RuntimeError(f"Connection failed: {error.reason}") from error


def _basic_auth(username, password):
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_provider(provider, config):
    if provider == "smtp":
        server = config.get("server")
        port = int(config.get("port") or 587)
        username = config.get("username")
        password = config.get("password")
        if not all([server, username, password]):
            raise ValueError("Server, username and password are required.")
        with smtplib.SMTP(server, port, timeout=12) as client:
            client.ehlo()
            if config.get("use_tls", True):
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            client.login(username, password)
        return "SMTP authentication succeeded."

    if provider == "stripe":
        key = config.get("secret_key")
        if not key:
            raise ValueError("Stripe secret key is required.")
        status, _ = _json_request(
            "https://api.stripe.com/v1/balance",
            headers=_basic_auth(key, ""),
        )
        return f"Stripe API authenticated (HTTP {status})."

    if provider == "paypal":
        client_id, secret = config.get("client_id"), config.get("client_secret")
        if not client_id or not secret:
            raise ValueError("PayPal client ID and secret are required.")
        base = (
            "https://api-m.paypal.com"
            if config.get("environment") == "live"
            else "https://api-m.sandbox.paypal.com"
        )
        status, _ = _json_request(
            f"{base}/v1/oauth2/token",
            headers={**_basic_auth(client_id, secret), "Accept": "application/json"},
            data={"grant_type": "client_credentials"},
        )
        return f"PayPal API authenticated (HTTP {status})."

    if provider == "razorpay":
        key_id, secret = config.get("key_id"), config.get("key_secret")
        if not key_id or not secret:
            raise ValueError("Razorpay key ID and secret are required.")
        status, _ = _json_request(
            "https://api.razorpay.com/v1/payments?count=1",
            headers=_basic_auth(key_id, secret),
        )
        return f"Razorpay API authenticated (HTTP {status})."

    if provider == "twilio_sms":
        sid, token = config.get("account_sid"), config.get("auth_token")
        if not sid or not token:
            raise ValueError("Twilio account SID and auth token are required.")
        status, _ = _json_request(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}.json",
            headers=_basic_auth(sid, token),
        )
        return f"Twilio API authenticated (HTTP {status})."

    if provider == "whatsapp":
        token, phone_id = config.get("access_token"), config.get("phone_number_id")
        if not token or not phone_id:
            raise ValueError("WhatsApp access token and phone number ID are required.")
        status, _ = _json_request(
            f"https://graph.facebook.com/v21.0/{phone_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        return f"WhatsApp API authenticated (HTTP {status})."

    raise ValueError("Unsupported integration provider.")


def record_test(setting, success, message):
    setting.last_test_status = "success" if success else "failed"
    setting.last_test_message = message[:500]
    setting.last_tested_at = datetime.now()
    db.session.commit()
