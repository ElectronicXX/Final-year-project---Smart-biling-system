import qrcode
import os

def generate_qr(name, amount):
    data = f"Pay {name} RM{amount}"

    img = qrcode.make(data)

    os.makedirs("static/qr", exist_ok=True)

    filename = f"qr_{name}.png"
    path = os.path.join("static/qr", filename)

    img.save(path)

    return f"/static/qr/{filename}"