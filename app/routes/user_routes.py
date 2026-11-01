from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity
from app import db
from app.models import User
from app.utils import require_role
import bcrypt

user_bp = Blueprint("users", __name__, url_prefix="/api/v1/users")

ALLOWED_ROLES = ("customer", "pharmacist", "admin")


def user_to_dict(u):
    return {
        "id": u.id,
        "name": u.name,
        "email": u.email,
        "role": u.role,
        "phone": u.phone,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


@user_bp.route("", methods=["GET"])
@require_role("admin")
def list_users():
    users = User.query.order_by(User.id).all()
    return jsonify([user_to_dict(u) for u in users]), 200


@user_bp.route("", methods=["POST"])
@require_role("admin")
def create_user():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    role = data.get("role")
    phone = (data.get("phone") or "").strip() or None

    if not name or not email or not password:
        return jsonify({"error": "name, email and password are required"}), 400
    if "@" not in email or "." not in email.split("@")[-1]:
        return jsonify({"error": "Enter a valid email address"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    if role not in ALLOWED_ROLES:
        return jsonify({"error": "role must be customer, pharmacist or admin"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already registered"}), 409

    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    user = User(
        name=name,
        email=email,
        password_hash=hashed.decode("utf-8"),
        role=role,
        phone=phone,
    )
    db.session.add(user)
    db.session.commit()

    return jsonify({"message": "User created", "user": user_to_dict(user)}), 201


@user_bp.route("/<int:user_id>/role", methods=["PUT"])
@require_role("admin")
def change_role(user_id):
    data = request.get_json() or {}
    role = data.get("role")

    if role not in ALLOWED_ROLES:
        return jsonify({"error": "role must be customer, pharmacist or admin"}), 400

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    if str(user.id) == str(get_jwt_identity()):
        return jsonify({"error": "You cannot change your own role"}), 400

    user.role = role
    db.session.commit()

    return jsonify({"message": "Role updated", "user": user_to_dict(user)}), 200















