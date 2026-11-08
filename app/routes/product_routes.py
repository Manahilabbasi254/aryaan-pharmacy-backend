from datetime import datetime, date
from decimal import Decimal, InvalidOperation

from flask import Blueprint, request, jsonify
from sqlalchemy.exc import IntegrityError

from app import db
from app.alerts import sync_alerts
from app.models import Product, Category
from app.utils import require_role

product_bp = Blueprint("products", __name__, url_prefix="/api/v1/products")


def product_to_dict(p):
    return {
        "id": p.id,
        "name": p.name,
        "category_id": p.category_id,
        "category_name": p.category.name,
        "price": float(p.price),
        "stock_qty": p.stock_qty,
        "expiry_date": p.expiry_date.isoformat() if p.expiry_date else None,
        "description": p.description,
    }


def clean_fields(data, partial=False, current=None):
    """Validate input. Returns (values, error_message)."""
    values = {}

    if not partial or "name" in data:
        name = (data.get("name") or "").strip()
        if len(name) < 2 or len(name) > 150:
            return None, "Name must be 2 to 150 characters"
        values["name"] = name

    if not partial or "category_id" in data:
        try:
            category_id = int(data.get("category_id"))
        except (TypeError, ValueError):
            return None, "Please select a valid category"
        if not Category.query.get(category_id):
            return None, "Category not found"
        values["category_id"] = category_id

    if not partial or "price" in data:
        try:
            price = Decimal(str(data.get("price")))
        except (InvalidOperation, TypeError):
            return None, "Price must be a number"
        if price <= 0 or price > Decimal("10000000"):
            return None, "Price must be greater than 0"
        values["price"] = price.quantize(Decimal("0.01"))

    if not partial or "stock_qty" in data:
        raw = data.get("stock_qty", 0)
        try:
            stock = int(raw)
        except (TypeError, ValueError):
            return None, "Stock must be a whole number"
        if stock < 0 or stock > 1000000:
            return None, "Stock cannot be negative"
        values["stock_qty"] = stock

    if "expiry_date" in data:
        raw = data.get("expiry_date")
        if raw:
            try:
                values["expiry_date"] = datetime.strptime(raw, "%Y-%m-%d").date()
            except ValueError:
                return None, "Expiry date must be in YYYY-MM-DD format"
        else:
            values["expiry_date"] = None

    if "description" in data:
        desc = (data.get("description") or "").strip()
        if len(desc) > 500:
            return None, "Description is too long (max 500 characters)"
        values["description"] = desc or None

    return values, None


@product_bp.route("", methods=["GET"])
def get_products():
    search = request.args.get("search", "")
    category_id = request.args.get("category_id")

    query = Product.query
    if search:
        query = query.filter(Product.name.ilike(f"%{search}%"))
    if category_id:
        query = query.filter_by(category_id=category_id)

    products = query.order_by(Product.name.asc()).all()
    return jsonify([product_to_dict(p) for p in products]), 200


@product_bp.route("/<int:product_id>", methods=["GET"])
def get_product(product_id):
    product = Product.query.get(product_id)
    if not product:
        return jsonify({"error": "Product not found"}), 404
    return jsonify(product_to_dict(product)), 200


@product_bp.route("", methods=["POST"])
@require_role("admin", "pharmacist")
def create_product():
    data = request.get_json(silent=True) or {}
    values, error = clean_fields(data)
    if error:
        return jsonify({"error": error}), 400

    new_product = Product(
        name=values["name"],
        category_id=values["category_id"],
        price=values["price"],
        stock_qty=values["stock_qty"],
        expiry_date=values.get("expiry_date"),
        description=values.get("description"),
    )
    db.session.add(new_product)
    db.session.commit()
    sync_alerts()

    return jsonify({"id": new_product.id, "name": new_product.name, "stock_qty": new_product.stock_qty}), 201


@product_bp.route("/<int:product_id>", methods=["PUT"])
@require_role("admin", "pharmacist")
def update_product(product_id):
    product = Product.query.get(product_id)
    if not product:
        return jsonify({"error": "Product not found"}), 404

    data = request.get_json(silent=True) or {}
    values, error = clean_fields(data, partial=True)
    if error:
        return jsonify({"error": error}), 400

    for key, value in values.items():
        setattr(product, key, value)

    db.session.commit()
    sync_alerts()

    return jsonify({"message": "Product updated", "id": product_id}), 200


@product_bp.route("/<int:product_id>", methods=["DELETE"])
@require_role("admin")
def delete_product(product_id):
    product = Product.query.get(product_id)
    if not product:
        return jsonify({"error": "Product not found"}), 404

    try:
        db.session.delete(product)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            "error": "This product is part of past orders or sales, so it cannot be deleted. "
                     "Set its stock to 0 instead."
        }), 409

    sync_alerts()
    return jsonify({"message": "Product deleted"}), 200