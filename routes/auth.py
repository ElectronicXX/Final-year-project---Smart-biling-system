from flask import Blueprint, render_template, request, redirect, session
from models import User

bp = Blueprint('auth', __name__)

@bp.route("/", methods=["GET","POST"])
def login():

    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        user = User.query.filter_by(email=email, password=password).first()

        if user:
            session["user"] = user.id
            session["role"] = user.role

            return {"status": "success"}
        else:
            return {"status": "error"}

    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/")