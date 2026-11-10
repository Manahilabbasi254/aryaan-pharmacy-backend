from datetime import timedelta
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager
from dotenv import load_dotenv
import os

load_dotenv()

db = SQLAlchemy()
jwt = JWTManager()

def create_app():
    app = Flask(__name__)

    # Allowed website addresses. For production, set FRONTEND_ORIGINS in .env
    # (comma separated), e.g. FRONTEND_ORIGINS=https://www.aryaanpharmacy.org.pk
    origins = os.getenv("FRONTEND_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    CORS(app, origins=[o.strip() for o in origins.split(",") if o.strip()])

    secret_key = os.getenv("SECRET_KEY")
    jwt_secret_key = os.getenv("JWT_SECRET_KEY")
    if not secret_key or not jwt_secret_key:
        raise RuntimeError("SECRET_KEY and JWT_SECRET_KEY must be set in the .env file")

    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = secret_key
    app.config["JWT_SECRET_KEY"] = jwt_secret_key
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=8)

    # Product image uploads (max 3 MB request, files kept in the "uploads" folder)
    app.config["MAX_CONTENT_LENGTH"] = 3 * 1024 * 1024
    app.config["UPLOAD_FOLDER"] = os.path.abspath(os.path.join(app.root_path, os.pardir, "uploads"))
    os.makedirs(os.path.join(app.config["UPLOAD_FOLDER"], "products"), exist_ok=True)

    db.init_app(app)
    jwt.init_app(app)

    # Reject tokens of users who were deactivated or deleted
    @jwt.token_in_blocklist_loader
    def reject_inactive_users(jwt_header, jwt_payload):
        from app.models import User
        try:
            user = db.session.get(User, int(jwt_payload["sub"]))
        except (KeyError, TypeError, ValueError):
            return True
        return user is None or not user.is_active

    @jwt.revoked_token_loader
    def revoked_token_response(jwt_header, jwt_payload):
        return jsonify({"msg": "Your account is no longer active. Please log in again."}), 401

    from app.routes.auth_routes import auth_bp
    from app.routes.category_routes import category_bp
    from app.routes.product_routes import product_bp
    from app.routes.order_routes import order_bp
    from app.routes.notification_routes import notification_bp
    from app.routes.sale_routes import sale_bp
    from app.routes.report_routes import report_bp
    from app.routes.supplier_routes import supplier_bp
    from app.routes.expense_routes import expense_bp
    from app.routes.user_routes import user_bp
    from app.routes.report_export_routes import report_export_bp

    app.register_blueprint(expense_bp)
    app.register_blueprint(supplier_bp)
    app.register_blueprint(report_bp)
    app.register_blueprint(report_export_bp)
    app.register_blueprint(sale_bp)
    app.register_blueprint(notification_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(category_bp)
    app.register_blueprint(product_bp)
    app.register_blueprint(order_bp)

    @app.route("/uploads/<path:filename>")
    def serve_upload(filename):
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    @app.route("/api/v1/ping")
    def ping():
        return {"message": "Aryaan Pharmacy backend is running"}

    return app