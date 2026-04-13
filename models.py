from db import db

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(100))
    password = db.Column(db.String(100))
    role = db.Column(db.String(10))

    age = db.Column(db.Integer)
    gender = db.Column(db.String(10))
    block = db.Column(db.String(10))
    floor = db.Column(db.Integer)
    unit = db.Column(db.Integer)
    room = db.Column(db.Integer)


class Billing(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    month = db.Column(db.String(20))
    electricity = db.Column(db.Float)
    water = db.Column(db.Float)
    total = db.Column(db.Float)


class UserDays(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    days = db.Column(db.Integer, default=0)
    month = db.Column(db.String(50))


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    amount = db.Column(db.Float)
    month = db.Column(db.String(50))
    status = db.Column(db.String(20))