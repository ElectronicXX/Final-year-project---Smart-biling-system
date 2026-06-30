from functools import wraps
import secrets

from flask import jsonify, redirect, request, session, url_for


def generate_csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_urlsafe(32)
    return session["_csrf_token"]


def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "user" not in session:
                if request.path.startswith("/api/"):
                    return jsonify(error="authentication required"), 401
                return redirect(url_for("auth.login"))

            if session.get("role") not in roles:
                if request.path.startswith("/api/"):
                    return jsonify(error="forbidden"), 403

                endpoint = (
                    "admin.dashboard"
                    if session.get("role") in {"admin", "finance"}
                    else "admin.user_dashboard"
                )
                return redirect(url_for(endpoint))

            return view(*args, **kwargs)

        return wrapped

    return decorator


def role_required(role):
    return roles_required(role)


admin_required = roles_required("admin")
finance_required = roles_required("admin", "finance")
resident_required = roles_required("user", "guest")
user_required = roles_required("user")
