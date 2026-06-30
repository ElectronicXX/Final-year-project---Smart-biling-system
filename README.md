# Smart Billing System

Flask-based hostel billing system with role-based dashboards, monthly cost
allocation, payment tracking, email reminders, PDF receipts, QR codes, and
basic billing prediction.

## Upgraded behavior

- Itemized monthly bills support custom charges and currencies.
- Resident shares are calculated only from check-ins in the selected month.
- Payments support installments, balances, and uploaded transfer proof.
- Receipts are unique per resident/month and protected by ownership checks.
- SMTP failures do not undo successful payments; receipts remain downloadable.
- Roles include administrator, finance, resident, and read-only guest.
- Notifications, audit logs, disputes, CSV/Excel reports, and API endpoints
  are included.
- Monthly schedules can automatically generate itemized bills.
- Administrators can manage SMTP, Stripe, PayPal, Razorpay, Twilio SMS, and
  WhatsApp Cloud API credentials from one encrypted integration center.
- Light and dark themes use a mobile-responsive interface.
- All state-changing requests are protected with CSRF tokens.

## Local setup

On Windows, double-click `setup.bat` for dependency installation and tests,
then double-click `start.bat` to run the application. `test.bat` reruns the
test suite.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
flask --app app run
```

Set the values from `.env` in your shell or use an environment loader before
starting Flask. Never commit the real mail password or `SECRET_KEY`. Keep
`SECRET_KEY` unchanged after saving integration credentials because it is used
to encrypt and decrypt them.

Existing plaintext passwords are automatically replaced with secure hashes
after each user's first successful login.

For HTTPS deployments, set `SESSION_COOKIE_SECURE=true` and set `APP_BASE_URL`
to the public application URL.

## Tests

```powershell
python -m unittest discover -s tests -v
```

## Automatic billing

Enable `AUTO_GENERATE_BILLS=true`, then configure the schedule on the Billing
page. The application checks once per day. It can also be run explicitly:

```powershell
flask --app app generate-monthly-bills
flask --app app send-overdue-reminders
```

## Reports and API

Finance and administrator accounts can use `/reports` and export CSV or Excel.
Session-authenticated API endpoints are available at:

- `GET /api/v1/bills`
- `GET /api/v1/billing-periods`

## Payments

Manual installments and payment-proof review work without external accounts.
`PAYMENT_PROVIDER=manual` is the default. Administrators can open
`/integrations` to save and test Stripe, PayPal, Razorpay, SMTP, Twilio SMS, and
WhatsApp credentials. SMTP, Twilio, WhatsApp, and Stripe API adapters are
connected to the application. PayPal and Razorpay credentials can be verified,
while their hosted checkout flows still require provider-specific completion.

Saved secrets are encrypted in the database and only masked values are rendered
in the browser. SMTP values from `.env` appear as defaults until the first
managed SMTP configuration is saved.

## Docker

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Open `http://127.0.0.1:5000`. Before production, set a strong `SECRET_KEY`,
enable HTTPS, and set `SESSION_COOKIE_SECURE=true`.

<img width="1865" height="872" alt="image" src="https://github.com/user-attachments/assets/179a038c-4dd4-4f7b-80d2-c3f8fc17042a" />

<img width="1662" height="843" alt="image" src="https://github.com/user-attachments/assets/cba9afa0-f0a1-4f3e-9274-7fa94969157d" />

<img width="1840" height="872" alt="image" src="https://github.com/user-attachments/assets/f0394b3c-9fb7-4d8d-90d4-ddcd3b7059a2" />

<img width="1831" height="879" alt="image" src="https://github.com/user-attachments/assets/c58c0749-ef7f-4d2e-83b3-f2cab28b35ac" />

<img width="1838" height="871" alt="image" src="https://github.com/user-attachments/assets/90d20ee1-d328-4be4-84f6-450e5169ef84" />

<img width="1854" height="869" alt="image" src="https://github.com/user-attachments/assets/e0c89c3f-c8de-403c-8a95-059c4b81a862" />

<img width="1827" height="873" alt="image" src="https://github.com/user-attachments/assets/5f27f9f7-30cf-4fc0-b4f0-cf32f1fe4bcf" />
<img width="1846" height="863" alt="image" src="https://github.com/user-attachments/assets/43aee78f-d8bc-40d5-9930-ab2cc6dad9e1" />
<img width="1511" height="445" alt="image" src="https://github.com/user-attachments/assets/d6a547df-7c61-416e-a097-f150d8f410c3" />
<img width="1511" height="590" alt="image" src="https://github.com/user-attachments/assets/b47bae8a-e54f-402a-9dc0-f1e7a9a7ca6c" />
