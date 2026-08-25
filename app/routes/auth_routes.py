from flask import Blueprint, request, jsonify
from app import db
from app.models import User
from flask_jwt_extended import create_access_token, get_jwt, jwt_required
import bcrypt

auth_bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")

@auth_bp.route("/register", methods=["POST"])
def register():
    
    data = request.get_json()

    name = data.get("name")
    email = data.get("email")
    password = data.get("password")
    role = data.get("role", "customer")

    if not name or not email or not password:
        return jsonify({"error": "name, email, and password are required"}), 400

    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        return jsonify({"error": "Email already registered"}), 409

    hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())

    new_user = User(
        name=name,
        email=email,
        password_hash=hashed_password.decode("utf-8"),
        role=role
    )
    from flask_jwt_extended import create_access_token

@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json()

    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    user = User.query.filter_by(email=email).first()

    if not user or not bcrypt.checkpw(password.encode("utf-8"), user.password_hash.encode("utf-8")):
        return jsonify({"error": "Invalid email or password"}), 401

    access_token = create_access_token(
        identity=str(user.id),
        additional_claims={"role": user.role, "name": user.name}
    )
    from flask_jwt_extended import jwt_required, get_jwt

@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def me():
    claims = get_jwt()
    return jsonify({
        "message": "You are authenticated",
        "role": claims.get("role"),
        "name": claims.get("name")
    }), 200

    return jsonify({
        "message": "Login successful",
        "access_token": access_token,
        "user": {"id": user.id, "name": user.name, "email": user.email, "role": user.role}
    }), 200

    db.session.add(new_user)
    db.session.commit()

    return jsonify({
        "message": "User registered successfully",
        "user": {"id": new_user.id, "name": new_user.name, "email": new_user.email, "role": new_user.role}
    }), 201