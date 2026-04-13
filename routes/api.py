from flask import Blueprint

bp = Blueprint('api', __name__)

@bp.route("/api")
def api_home():
    return {"status": "API running"}