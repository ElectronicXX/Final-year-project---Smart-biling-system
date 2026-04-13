from flask_mail import Message
from extensions import mail 


def send_reminder_email(to_email, amount, month="Current Month", status="Pending"):

    subject = "💡 Smart Billing Notification"
    html = f"""
    <div style="font-family: Arial; background:#f4f6f9; padding:20px;">
        
        <div style="max-width:600px; margin:auto; background:white; border-radius:10px; overflow:hidden; box-shadow:0 5px 15px rgba(0,0,0,0.1);">
            
            <!-- Header -->
            <div style="background:#007bff; color:white; padding:15px; text-align:center;">
                <h2>💡 Smart Billing System</h2>
            </div>

            <!-- Body -->
            <div style="padding:20px; text-align:center;">

                <h3>Hello 👋</h3>

                <p>Your monthly bill is ready</p>

                <!-- Amount -->
                <div style="margin:20px 0;">
                    <h1 style="color:#28a745;">RM {amount}</h1>
                    <p>{month}</p>
                </div>

                <!-- Status -->
                <div style="margin:20px 0;">
                    {"<span style='color:red;'>🔴 Pending</span>" if status != "Paid" else "<span style='color:green;'>🟢 Paid</span>"}
                </div>

                <p>Please complete your payment as soon as possible.</p>

                <!-- Button -->
                <a href="http://127.0.0.1:5000/user_dashboard" 
                   style="display:inline-block; padding:10px 20px; background:#007bff; color:white; border-radius:5px; text-decoration:none;">
                   View Dashboard
                </a>

            </div>

            <!-- Footer -->
            <div style="background:#f1f1f1; padding:10px; text-align:center; font-size:12px;">
                Smart Billing System © 2026
            </div>

        </div>

    </div>
    """

    msg = Message(
        subject=subject,
        recipients=[to_email],
        html=html,
        sender="smartbilingsb@gmail.com"
    )

    mail.send(msg)

def send_receipt_email(to_email, amount, month, pdf_path):

    html = f"""
    <div style="font-family: Arial; background:#f4f6f9; padding:20px;">
        
        <div style="max-width:600px; margin:auto; background:white; border-radius:10px; overflow:hidden; box-shadow:0 5px 15px rgba(0,0,0,0.1);">
            
            <!-- HEADER -->
            <div style="background:#28a745; color:white; padding:15px; text-align:center;">
                <h2>🟢 Payment Successful</h2>
            </div>

            <!-- BODY -->
            <div style="padding:20px; text-align:center;">

                <p>Thank you for your payment!</p>

                <p>Month: <b>{month}</b></p>

                <h1 style="color:#28a745;">RM {amount}</h1>

                <p>Your receipt is attached in this email.</p>

                <a href="http://127.0.0.1:5000/user_dashboard"
                   style="display:inline-block; padding:10px 20px; background:#28a745; color:white; border-radius:5px; text-decoration:none;">
                   View Dashboard
                </a>

            </div>

            <!-- FOOTER -->
            <div style="background:#f1f1f1; padding:10px; text-align:center; font-size:12px;">
                Smart Billing System © 2026
            </div>

        </div>

    </div>
    """
    msg = Message(
        subject="🟢 Payment Receipt",
        recipients=[to_email],
        html=html,
        sender="smartbilingsb@gmail.com"
    )

    with open(pdf_path, "rb") as f:
        msg.attach("invoice.pdf", "application/pdf", f.read())

    mail.send(msg)