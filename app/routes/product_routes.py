from flask import Blueprint, request, jsonify
from app import db
from app.models import Product
from app.utils import require_role
from datetime import datetime

product_bp = Blueprint("products", __name__, url_prefix="/api/v1/products")


@product_bp.route("", methods=["GET"])
def get_products():
    search = request.args.get("search", "")
    category_id = request.args.get("category_id")

    query = Product.query
    if search:
        query = query.filter(Product.name.ilike(f"%{search}%"))
    if category_id:
        query = query.filter_by(category_id=category_id)

    products = query.all()
    return jsonify([{
        "id": p.id,
        "name": p.name,
        "category_id": p.category_id,
        "category_name": p.category.name,
        "price": float(p.price),
        "stock_qty": p.stock_qty,
        "expiry_date": p.expiry_date.isoformat() if p.expiry_date else None,
        "description": p.description
    } for p in products]), 200


@product_bp.route("/<int:product_id>", methods=["GET"])
def get_product(product_id):
    product = Product.query.get(product_id)
    if not product:
        return jsonify({"error": "Product not found"}), 404

    return jsonify({
        "id": product.id,
        "name": product.name,
        "category_id": product.category_id,
        "category_name": product.category.name,
        "price": float(product.price),
        "stock_qty": product.stock_qty,
        "expiry_date": product.expiry_date.isoformat() if product.expiry_date else None,
        "description": product.description
    }), 200


@product_bp.route("", methods=["POST"])
@require_role("admin", "pharmacist")
def create_product():
    data = request.get_json()

    name = data.get("name")
    category_id = data.get("category_id")
    price = data.get("price")
    stock_qty = data.get("stock_qty", 0)
    expiry_date = data.get("expiry_date")
    description = data.get("description")

    if not name or not category_id or price is None:
        return jsonify({"error": "name, category_id, and price are required"}), 400

    new_product = Product(
        name=name,
        category_id=category_id,
        price=price,
        stock_qty=stock_qty,
        expiry_date=datetime.strptime(expiry_date, "%Y-%m-%d").date() if expiry_date else None,
        description=description
    )

    db.session.add(new_product)
    db.session.commit()

    return jsonify({"id": new_product.id, "name": new_product.name, "stock_qty": new_product.stock_qty}), 201


@product_bp.route("/<int:product_id>", methods=["PUT"])
@require_role("admin", "pharmacist")
def update_product(product_id):
    product = Product.query.get(product_id)
    if not product:
        return jsonify({"error": "Product not found"}), 404

    data = request.get_json()

    product.name = data.get("name", product.name)
    product.category_id = data.get("category_id", product.category_id)
    product.price = data.get("price", product.price)
    product.stock_qty = data.get("stock_qty", product.stock_qty)
    product.description = data.get("description", product.description)

    if "expiry_date" in data and data["expiry_date"]:
        product.expiry_date = datetime.strptime(data["expiry_date"], "%Y-%m-%d").date()

    db.session.commit()

    return jsonify({"message": "Product updated", "id": product.id}), 200


@product_bp.route("/<int:product_id>", methods=["DELETE"])
@require_role("admin")
def delete_product(product_id):
    product = Product.query.get(product_id)
    if not product:
        return jsonify({"error": "Product not found"}), 404

    db.session.delete(product)
    db.session.commit()

    return jsonify({"message": "Product deleted"}), 200