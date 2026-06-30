from flask import Blueprint, render_template, request, redirect, session, url_for
from models import User
from services.server_monitor_service import remove_session_activity

bp = Blueprint('auth', __name__)

@bp.route("/", methods=["GET","POST"])
def login():

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            session.clear()
            session["user"] = user.id
            session["role"] = user.role

            destination = (
                url_for("admin.dashboard")
                if user.role in {"admin", "finance"}
                else url_for("admin.user_dashboard")
            )
            return {"status": "success", "redirect": destination}
        else:
            return {"status": "error"}, 401

    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    remove_session_activity(session.get("_visitor_token"))
    session.clear()
    return redirect(url_for("auth.login"))
