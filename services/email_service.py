import logging
from html import escape
from pathlib import Path
from smtplib import SMTPAuthenticationError, SMTPException

from flask import current_app
from flask_mail import Message

from extensions import mail
from services.integration_service import get_config, get_setting

log = logging.getLogger(__name__)


def mail_is_configured():
    config = effective_mail_config()
    return bool(
        config.get("server")
        and config.get("username")
        and config.get("password")
        and config.get("sender")
    )


def effective_mail_config():
    managed_setting = get_setting("smtp")
    if managed_setting and not managed_setting.enabled:
        return {}
    managed = get_config("smtp")
    if managed:
        return managed
    return {
        "server": current_app.config.get("MAIL_SERVER"),
        "port": current_app.config.get("MAIL_PORT", 587),
        "username": current_app.config.get("MAIL_USERNAME"),
        "password": current_app.config.get("MAIL_PASSWORD"),
        "sender": current_app.config.get("MAIL_DEFAULT_SENDER"),
        "use_tls": current_app.config.get("MAIL_USE_TLS", True),
    }


def apply_mail_config():
    config = effective_mail_config()
    state = current_app.extensions["mail"]
    state.server = config.get("server")
    state.port = int(config.get("port") or 587)
    state.username = config.get("username")
    state.password = config.get("password")
    state.default_sender = config.get("sender") or config.get("username")
    state.use_tls = bool(config.get("use_tls", True))
    state.use_ssl = False
    return config


def configure_message(message):
    config = apply_mail_config()
    sender = config.get("sender") or config.get("username")
    if sender:
        message.sender = sender
    return message


def dashboard_url():
    base_url = current_app.config.get("APP_BASE_URL") or "http://127.0.0.1:5000"
    return f"{base_url.rstrip('/')}/user_dashboard"


def money(amount, currency="MYR"):
    return f"{escape(currency or 'MYR')} {float(amount or 0):,.2f}"


def billing_email_html(title, subtitle, amount, month, status, accent, details=None):
    details = details or []
    rows = "".join(
        f"""
        <tr>
          <td style="padding:14px 0;color:#707070;font-size:14px;border-bottom:1px solid #eeeeee;">{escape(label)}</td>
          <td style="padding:14px 0;color:#111111;font-size:14px;font-weight:600;text-align:right;border-bottom:1px solid #eeeeee;">{escape(str(value))}</td>
        </tr>
        """
        for label, value in details
    )
    return f"""
    <!doctype html>
    <html>
    <body style="margin:0;padding:0;background:#ffffff;color:#111111;font-family:Arial,'Helvetica Neue',Helvetica,sans-serif;">
      <div style="display:none;max-height:0;overflow:hidden;color:#ffffff;opacity:0;">
        {escape(subtitle)}
      </div>
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#ffffff;">
        <tr>
          <td align="center" style="padding:56px 20px 42px;">
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;margin:0 auto;">
              <tr>
                <td align="center" style="padding-bottom:32px;font-size:20px;font-weight:700;color:#111111;">
                  Smart Billing
                </td>
              </tr>
              <tr>
                <td align="center">
                  <h1 style="margin:0;color:#202124;font-size:34px;line-height:1.22;font-weight:500;letter-spacing:-0.6px;">
                    {escape(title)}
                  </h1>
                  <p style="margin:20px 0 0;color:#444444;font-size:16px;line-height:1.7;">
                    {escape(subtitle)}
                  </p>
                </td>
              </tr>
              <tr>
                <td align="center" style="padding:28px 0 38px;">
                  <a href="{escape(dashboard_url())}" style="display:inline-block;background:#000000;color:#ffffff;text-decoration:none;font-size:15px;font-weight:700;padding:14px 26px;border-radius:999px;">
                    View bill
                  </a>
                </td>
              </tr>
              <tr>
                <td style="padding:0;">
                  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border:1px solid #eeeeee;border-radius:24px;background:#fafafa;overflow:hidden;">
                    <tr>
                      <td style="padding:30px;">
                        <div style="color:#777777;font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:0.12em;">
                          {escape(month)}
                        </div>
                        <div style="margin-top:12px;color:#111111;font-size:38px;line-height:1.15;font-weight:700;letter-spacing:-0.8px;">
                          {money(amount, accent)}
                        </div>
                        <div style="display:inline-block;margin-top:18px;padding:8px 12px;border-radius:999px;background:#ffffff;color:#111111;font-size:13px;font-weight:700;border:1px solid #eeeeee;">
                          {escape(status)}
                        </div>
                        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:24px;">
                          {rows}
                        </table>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>
              <tr>
                <td align="center" style="padding-top:28px;color:#8a8a8a;font-size:12px;line-height:1.7;">
                  This message was sent by Smart Billing. If you have questions, reply to your billing administrator.
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </body>
    </html>
    """


def deliver(message):
    if not mail_is_configured():
        current_app.logger.warning("Email skipped because SMTP is not configured.")
        return "not_configured"
    try:
        configure_message(message)
        mail.send(message)
        return "sent"
    except SMTPAuthenticationError:
        current_app.logger.error(
            "Email authentication failed. For Gmail, use a 16-digit app password."
        )
        return "authentication_failed"
    except SMTPException:
        log.exception("SMTP rejected the billing email")
        return "delivery_failed"
    except OSError:
        log.exception("Unable to connect to the mail server")
        return "connection_failed"
    except Exception:
        log.exception("Unable to send billing email")
        return "delivery_failed"


def send_reminder_email(
    to_email, amount, month="Current Month", status="Pending", currency="MYR"
):
    apply_mail_config()
    if not mail_is_configured():
        current_app.logger.warning("Reminder email skipped: SMTP is not configured.")
        return "not_configured"
    html = billing_email_html(
        title="Your bill is ready",
        subtitle="A quick reminder to review and settle your latest shared bill.",
        amount=amount,
        month=month,
        status=status,
        accent=currency,
        details=[
            ("Bill month", month),
            ("Amount due", money(amount, currency)),
            ("Payment status", status),
        ],
    )
    return deliver(
        Message(
            subject="Smart Billing Reminder",
            recipients=[to_email],
            body=(
                f"Your {month} bill is {money(amount, currency)}. "
                f"Status: {status}. View it at {dashboard_url()}"
            ),
            html=html,
        )
    )


def send_receipt_email(to_email, amount, month, pdf_path, currency="MYR"):
    apply_mail_config()
    if not mail_is_configured():
        current_app.logger.warning("Receipt email skipped: SMTP is not configured.")
        return "not_configured"
    html = billing_email_html(
        title="Payment received",
        subtitle="Thanks. Your payment has been recorded and the receipt is attached.",
        amount=amount,
        month=month,
        status="Paid",
        accent=currency,
        details=[
            ("Bill month", month),
            ("Amount paid", money(amount, currency)),
            ("Receipt", "Attached PDF"),
        ],
    )
    message = Message(
        subject="Smart Billing Payment Receipt",
        recipients=[to_email],
        body=(
            f"Payment received for {month}: {money(amount, currency)}. "
            "Your receipt is attached."
        ),
        html=html,
    )
    path = Path(pdf_path)
    with path.open("rb") as receipt:
        message.attach(path.name, "application/pdf", receipt.read())
    return deliver(message)


def send_overdue_email(to_email, balance, month, due_date, currency="MYR"):
    apply_mail_config()
    if not mail_is_configured():
        current_app.logger.warning("Overdue email skipped: SMTP is not configured.")
        return "not_configured"
    html = billing_email_html(
        title="Your bill is overdue",
        subtitle="Please review the outstanding balance or submit your payment proof.",
        amount=balance,
        month=month,
        status="Overdue",
        accent=currency,
        details=[
            ("Bill month", month),
            ("Outstanding balance", money(balance, currency)),
            ("Due date", due_date),
        ],
    )
    return deliver(
        Message(
            subject="Smart Billing Overdue Notice",
            recipients=[to_email],
            body=(
                f"Your {month} balance is overdue: {money(balance, currency)}. "
                f"Due date: {due_date}. View it at {dashboard_url()}"
            ),
            html=html,
        )
    )
