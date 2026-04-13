from flask import Flask, redirect, request, session
from db import db
from extensions import mail
import logging
app = Flask(__name__)

app.config['SECRET_KEY'] = 'secret123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USERNAME'] = 'smartbilingsb@gmail.com'
app.config['MAIL_PASSWORD'] = 'chkxkydvngbtgkzs'
app.config['MAIL_USE_TLS'] = True

mail.init_app(app)
db.init_app(app)   
app.config['MAIL_DEFAULT_SENDER'] = 'smartbilingsb@gmail.com'

from routes import auth, admin, api

app.register_blueprint(auth.bp)
app.register_blueprint(admin.bp)
app.register_blueprint(api.bp)

@app.before_request
def protect_routes():
    protected = ["/dashboard", "/users", "/billing"]

    if request.path in protected:
        if session.get("role") != "admin":
            return redirect("/user_dashboard")
        
class IgnoreAPI(logging.Filter):
    def filter(self, record):
        return '/api/' not in record.getMessage()

log = logging.getLogger('werkzeug')
log.addFilter(IgnoreAPI())

if __name__ == "__main__":
    app.run(debug=True)