import re

from flask import Blueprint, request, jsonify
from app import db
from app.models import User
from app.rate_limit import seconds_until_allowed, record_failure, clear_failures
from flask_jwt_extended import create_access_token, jwt_required, get_jwt, get_jwt_identity
import bcrypt

auth_bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")

PHONE_PATTERN = re.compile(r"^[0-9+\-\s()]{7,20}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def user_payload(u):
    return {"id": u.id, "name": u.name, "email": u.email, "role": u.role, "phone": u.phone}


@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    role = "customer"

    if not name or not email or not password:
        return jsonify({"error": "name, email, and password are required"}), 400

    if len(name) < 2 or len(name) > 100:
        return jsonify({"error": "Name must be between 2 and 100 characters"}), 400
    if len(email) > 120 or not EMAIL_PATTERN.match(email):
        return jsonify({"error": "Enter a valid email address"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    if len(password.encode("utf-8")) > 72:
        return jsonify({"error": "Password is too long (maximum 72 characters)"}), 400

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

    db.session.add(new_user)
    db.session.commit()

    return jsonify({
        "message": "User registered successfully",
        "user": {"id": new_user.id, "name": new_user.name, "email": new_user.email, "role": new_user.role}
    }), 201


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}

    email = (data.get("email") or "").strip()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    ip = request.remote_addr or "unknown"

    # 429 (not 401) on purpose: the frontend logs the user out on any 401
    wait = seconds_until_allowed(ip, email)
    if wait > 0:
        minutes = max(1, (wait + 59) // 60)
        return jsonify({
            "error": f"Too many failed attempts. Please try again in {minutes} minute(s)."
        }), 429

    user = User.query.filter_by(email=email).first()

    if not user or not bcrypt.checkpw(password.encode("utf-8"), user.password_hash.encode("utf-8")):
        record_failure(ip, email)
        return jsonify({"error": "Invalid email or password"}), 401

    if not user.is_active:
        return jsonify({"error": "This account has been deactivated. Please contact the pharmacy admin."}), 403

    clear_failures(ip, email)

    access_token = create_access_token(
        identity=str(user.id),
        additional_claims={"role": user.role, "name": user.name}
    )

    return jsonify({
        "message": "Login successful",
        "access_token": access_token,
        "user": {"id": user.id, "name": user.name, "email": user.email, "role": user.role}
    }), 200


@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def me():
    claims = get_jwt()
    return jsonify({
        "message": "You are authenticated",
        "role": claims.get("role"),
        "name": claims.get("name")
    }), 200


@auth_bp.route("/profile", methods=["GET"])
@jwt_required()
def get_profile():
    user = db.session.get(User, int(get_jwt_identity()))
    if not user:
        return jsonify({"error": "User not found"}), 404
    return jsonify(user_payload(user)), 200


@auth_bp.route("/profile", methods=["PUT"])
@jwt_required()
def update_profile():
    user = db.session.get(User, int(get_jwt_identity()))
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()

    if len(name) < 2 or len(name) > 100:
        return jsonify({"error": "Name must be between 2 and 100 characters"}), 400
    if phone and not PHONE_PATTERN.match(phone):
        return jsonify({"error": "Enter a valid phone number (digits, +, - and spaces only)"}), 400

    user.name = name
    user.phone = phone or None
    db.session.commit()

    return jsonify({"message": "Profile updated", "user": user_payload(user)}), 200


@auth_bp.route("/password", methods=["PUT"])
@jwt_required()
def change_password():
    user = db.session.get(User, int(get_jwt_identity()))
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json(silent=True) or {}
    current_password = data.get("current_password") or ""
    new_password = data.get("new_password") or ""

    # 400 (not 401) on purpose: the frontend logs the user out on any 401
    if not bcrypt.checkpw(current_password.encode("utf-8"), user.password_hash.encode("utf-8")):
        return jsonify({"error": "Current password is incorrect"}), 400
    if len(new_password) < 6:
        return jsonify({"error": "New password must be at least 6 characters"}), 400
    if len(new_password.encode("utf-8")) > 72:
        return jsonify({"error": "New password is too long (maximum 72 characters)"}), 400
    if new_password == current_password:
        return jsonify({"error": "New password must be different from the current one"}), 400

    hashed = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt())
    user.password_hash = hashed.decode("utf-8")
    db.session.commit()

    return jsonify({"message": "Password changed"}), 200