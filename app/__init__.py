from flask import Flask
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
    CORS(app)

    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
    app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY")

    db.init_app(app)
    jwt.init_app(app)

    from app.routes.auth_routes import auth_bp
    from app.routes.category_routes import category_bp
    from app.routes.product_routes import product_bp
    from app.routes.order_routes import order_bp
    from app.routes.notification_routes import notification_bp

    from app.routes.sale_routes import sale_bp
# ... with your other blueprint imports
    from app.routes.report_routes import report_bp
    from app.routes.supplier_routes import supplier_bp
    from app.routes.expense_routes import expense_bp
    app.register_blueprint(expense_bp)
    app.register_blueprint(supplier_bp)
    app.register_blueprint(report_bp) 
    app.register_blueprint(sale_bp)
    app.register_blueprint(notification_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(category_bp)
    app.register_blueprint(product_bp)
    app.register_blueprint(order_bp)

    @app.route("/api/v1/ping")
    def ping():
        return {"message": "Aryaan Pharmacy backend is running"}

    return app