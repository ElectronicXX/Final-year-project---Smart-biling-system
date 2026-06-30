from datetime import datetime
from pathlib import Path
import re
from xml.sax.saxutils import escape

from flask import current_app
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def safe_month_slug(month):
    return re.sub(r"[^A-Za-z0-9_-]+", "-", month).strip("-").lower()


def generate_pdf(user_id, name, amount, month, currency="MYR", items=None):
    pdf_directory = Path(current_app.root_path) / "static" / "pdf"
    pdf_directory.mkdir(parents=True, exist_ok=True)
    filename = f"receipt-{user_id}-{safe_month_slug(month)}.pdf"
    path = pdf_directory / filename

    doc = SimpleDocTemplate(str(path), pagesize=A4)
    styles = getSampleStyleSheet()
    logo_path = Path(current_app.root_path) / "static" / "SB_logo.png"
    logo = Image(str(logo_path), width=90, height=90) if logo_path.exists() else ""
    invoice_info = [
        [Paragraph("<b>PAYMENT RECEIPT</b>", styles["Heading2"])],
        [Paragraph(f"Date: {datetime.now():%d/%m/%Y}", styles["Normal"])],
        [Paragraph(f"Billing month: {escape(month)}", styles["Normal"])],
    ]
    elements = [
        Table(
            [[logo, invoice_info]],
            colWidths=[180, 320],
            style=[
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ],
        ),
        Spacer(1, 20),
        Paragraph("<b>SMART BILLING SYSTEM</b>", styles["Title"]),
        Paragraph("Smart Hostel Management", styles["Normal"]),
        Spacer(1, 20),
        Paragraph(f"<b>Bill To:</b> {escape(name)}", styles["Normal"]),
        Spacer(1, 20),
    ]
    data = [["Description", "Amount"]]
    if items:
        data.extend(
            [[escape(item["name"]), f"{currency} {item['amount']:.2f}"] for item in items]
        )
    else:
        data.append(["Hostel utilities", f"{currency} {amount:.2f}"])
    table = Table(data, colWidths=[300, 150])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("ALIGN", (1, 1), (-1, -1), "CENTER"),
            ]
        )
    )
    elements.extend(
        [
            table,
            Spacer(1, 20),
            Paragraph(f"<b>Total: {currency} {amount:.2f}</b>", styles["Heading3"]),
            Spacer(1, 30),
            Paragraph("Thank you for your payment.", styles["Normal"]),
            Paragraph("This is a system-generated receipt.", styles["Normal"]),
        ]
    )
    doc.build(elements)
    return filename, str(path)
