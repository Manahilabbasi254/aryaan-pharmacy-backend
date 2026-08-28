from flask import Blueprint, request, jsonify
from app import db
from app.models import Category
from app.utils import require_role

category_bp = Blueprint("categories", __name__, url_prefix="/api/v1/categories")

@category_bp.route("", methods=["GET"])
def get_categories():
    categories = Category.query.all()
    return jsonify([{"id": c.id, "name": c.name} for c in categories]), 200


@category_bp.route("", methods=["POST"])
@require_role("admin")
def create_category():
    data = request.get_json()
    name = data.get("name")

    if not name:
        return jsonify({"error": "name is required"}), 400

    if Category.query.filter_by(name=name).first():
        return jsonify({"error": "Category already exists"}), 409

    new_category = Category(name=name)
    db.session.add(new_category)
    db.session.commit()

    return jsonify({"id": new_category.id, "name": new_category.name}), 201