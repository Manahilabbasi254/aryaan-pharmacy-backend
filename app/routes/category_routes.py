from flask import Blueprint, request, jsonify

from app import db
from app.models import Category, Product
from app.utils import require_role

category_bp = Blueprint("categories", __name__, url_prefix="/api/v1/categories")


def clean_name(data):
    name = (data.get("name") or "").strip()
    if len(name) < 2 or len(name) > 100:
        return None, "Category name must be 2 to 100 characters"
    return name, None


@category_bp.route("", methods=["GET"])
def get_categories():
    categories = Category.query.order_by(Category.name.asc()).all()
    result = []
    for c in categories:
        result.append({
            "id": c.id,
            "name": c.name,
            "product_count": Product.query.filter_by(category_id=c.id).count(),
        })
    return jsonify(result), 200


@category_bp.route("", methods=["POST"])
@require_role("admin")
def create_category():
    data = request.get_json(silent=True) or {}
    name, error = clean_name(data)
    if error:
        return jsonify({"error": error}), 400

    if Category.query.filter(db.func.lower(Category.name) == name.lower()).first():
        return jsonify({"error": "Category already exists"}), 409

    new_category = Category(name=name)
    db.session.add(new_category)
    db.session.commit()

    return jsonify({"id": new_category.id, "name": new_category.name}), 201


@category_bp.route("/<int:category_id>", methods=["PUT"])
@require_role("admin")
def update_category(category_id):
    category = Category.query.get(category_id)
    if not category:
        return jsonify({"error": "Category not found"}), 404

    data = request.get_json(silent=True) or {}
    name, error = clean_name(data)
    if error:
        return jsonify({"error": error}), 400

    clash = Category.query.filter(
        db.func.lower(Category.name) == name.lower(),
        Category.id != category_id,
    ).first()
    if clash:
        return jsonify({"error": "Another category already has this name"}), 409

    category.name = name
    db.session.commit()
    return jsonify({"id": category.id, "name": category.name}), 200


@category_bp.route("/<int:category_id>", methods=["DELETE"])
@require_role("admin")
def delete_category(category_id):
    category = Category.query.get(category_id)
    if not category:
        return jsonify({"error": "Category not found"}), 404

    if Product.query.filter_by(category_id=category_id).count() > 0:
        return jsonify({"error": "This category still has products. Move or delete them first."}), 409

    db.session.delete(category)
    db.session.commit()
    return jsonify({"message": "Category deleted"}), 200