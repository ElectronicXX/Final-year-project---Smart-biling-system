import base64
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from services.integration_service import get_config


def send_sms(to_number, message):
    config = get_config("twilio_sms")
    if not config:
        return "not_configured"
    sid = config["account_sid"]
    token = base64.b64encode(f"{sid}:{config['auth_token']}".encode()).decode()
    request = Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        data=urlencode(
            {"To": to_number, "From": config["from_number"], "Body": message}
        ).encode(),
        headers={
            "Authorization": f"Basic {token}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urlopen(request, timeout=15):
        return "sent"


def send_whatsapp(to_number, message):
    config = get_config("whatsapp")
    if not config:
        return "not_configured"
    payload = json.dumps(
        {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "text",
            "text": {"body": message},
        }
    ).encode()
    request = Request(
        f"https://graph.facebook.com/v21.0/{config['phone_number_id']}/messages",
        data=payload,
        headers={
            "Authorization": f"Bearer {config['access_token']}",
            "Content-Type": "application/json",
        },
    )
    with urlopen(request, timeout=15):
        return "sent"
