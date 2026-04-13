from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
import os
from datetime import datetime

def generate_pdf(name, amount):

    os.makedirs("static/pdf", exist_ok=True)
    path = f"static/pdf/{name}_invoice.pdf"
    doc = SimpleDocTemplate(path, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []
    logo_path = r"static\SB_logo.png"

    logo = ""
    if os.path.exists(logo_path):
        logo = Image(logo_path, width=150, height=150)

    today = datetime.now().strftime("%d/%m/%Y")

    invoice_info = [
        [Paragraph("<b>INVOICE</b>", styles['Heading2'])],
        [Paragraph(f"Date: {today}", styles['Normal'])]
    ]

    header_table = Table(
        [[logo, invoice_info]],
        colWidths=[200, 300],
        style=[
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('ALIGN', (1,0), (1,0), 'RIGHT')
        ]
    )
    elements.append(header_table)
    elements.append(Spacer(1, 20))
    elements.append(Paragraph("<b>SMART BILLING SYSTEM</b>", styles['Title']))
    elements.append(Paragraph("Smart Hostel Management", styles['Normal']))
    elements.append(Paragraph("Malaysia", styles['Normal']))
    elements.append(Spacer(1, 20))
    elements.append(Paragraph(f"<b>Bill To:</b> {name}", styles['Normal']))
    elements.append(Spacer(1, 20))
    data = [
        ["Description", "Qty", "Unit Price", "Amount"],
        ["Hostel Management fee", "1", f"RM {amount}", f"RM {amount}"]
    ]

    table = Table(data, colWidths=[200, 50, 100, 100])

    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.grey),
        ('TEXTCOLOR',(0,0),(-1,0),colors.white),

        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('ALIGN',(1,1),(-1,-1),'CENTER')
    ]))

    elements.append(table)
    elements.append(Spacer(1, 20))
    elements.append(Paragraph(f"<b>Total: RM {amount}</b>", styles['Heading3']))
    elements.append(Spacer(1, 30))
    elements.append(Paragraph("Thank you for your payment!", styles['Normal']))
    elements.append(Paragraph("This is a system-generated invoice.", styles['Normal']))

    doc.build(elements)

    return path