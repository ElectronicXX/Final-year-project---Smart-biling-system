FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/instance/payment_proofs /app/static/pdf /app/static/qr

EXPOSE 5000

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:5000 --workers ${GUNICORN_WORKERS:-2} app:app"]
