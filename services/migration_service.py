from sqlalchemy import inspect, text

from db import db


COLUMNS = {
    "user": {
        "phone": "VARCHAR(30)",
        "group_name": "VARCHAR(100)",
        "preferred_currency": "VARCHAR(3) DEFAULT 'MYR'",
        "created_at": "DATETIME",
    },
    "billing": {
        "currency": "VARCHAR(3) DEFAULT 'MYR'",
        "due_date": "DATE",
        "auto_generated": "BOOLEAN DEFAULT 0",
        "created_at": "DATETIME",
    },
    "payment": {
        "receipt_filename": "VARCHAR(255)",
        "paid_amount": "FLOAT DEFAULT 0",
        "currency": "VARCHAR(3) DEFAULT 'MYR'",
        "due_date": "DATE",
        "updated_at": "DATETIME",
    },
    "daily_check_in": {
        "checked_in_at": "DATETIME",
        "source": "VARCHAR(20) DEFAULT 'self'",
    },
}


def upgrade_schema():
    db.create_all()
    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    for table, definitions in COLUMNS.items():
        if table not in tables:
            continue
        existing = {column["name"] for column in inspector.get_columns(table)}
        for name, definition in definitions.items():
            if name not in existing:
                db.session.execute(
                    text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}')
                )
    db.session.execute(
        text(
            "UPDATE payment SET paid_amount = amount "
            "WHERE status = 'Paid' AND (paid_amount IS NULL OR paid_amount = 0)"
        )
    )
    db.session.execute(
        text("UPDATE payment SET paid_amount = 0 WHERE paid_amount IS NULL")
    )
    db.session.commit()
