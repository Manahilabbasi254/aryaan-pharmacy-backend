import os
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, request, jsonify, current_app
from sqlalchemy.exc import IntegrityError

from app import db
from app.alerts import sync_alerts
from app.models import Product, Category
from app.utils import require_role

product_bp = Blueprint("products", __name__, url_prefix="/api/v1/products")


def detect_image_type(data):
    """Check the real file bytes (not the file name). Returns jpg/png/webp or None."""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def delete_image_file(image_url):
    """Remove an uploaded file that belongs to this app (never anything else)."""
    if not image_url or not image_url.startswith("/uploads/products/"):
        return
    name = os.path.basename(image_url)
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], "products", name)
    try:
        os.remove(path)
    except OSError:
        pass


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
        "image_url": p.image_url,
    }


def clean_fields(data, partial=False):
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
    search = request.args.get("search", "").strip()
    category_id = request.args.get("category_id")
    sort = request.args.get("sort", "name")
    in_stock = request.args.get("in_stock")

    query = Product.query
    if search:
        query = query.filter(Product.name.ilike(f"%{search}%"))
    if category_id:
        query = query.filter_by(category_id=category_id)
    if in_stock == "1":
        query = query.filter(Product.stock_qty > 0)

    if sort == "price_asc":
        query = query.order_by(Product.price.asc(), Product.name.asc())
    elif sort == "price_desc":
        query = query.order_by(Product.price.desc(), Product.name.asc())
    elif sort == "newest":
        query = query.order_by(Product.id.desc())
    else:
        query = query.order_by(Product.name.asc())

    # Optional paging: /products?page=1&per_page=12 returns {items, total, page, pages}.
    # Without "page" the old plain list is returned, so existing screens keep working.
    if request.args.get("page"):
        try:
            page = max(int(request.args.get("page", 1)), 1)
            per_page = min(max(int(request.args.get("per_page", 12)), 1), 100)
        except ValueError:
            return jsonify({"error": "page and per_page must be numbers"}), 400
        total = query.count()
        items = query.offset((page - 1) * per_page).limit(per_page).all()
        return jsonify({
            "items": [product_to_dict(p) for p in items],
            "total": total,
            "page": page,
            "pages": max((total + per_page - 1) // per_page, 1),
        }), 200

    return jsonify([product_to_dict(p) for p in query.all()]), 200


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


@product_bp.route("/<int:product_id>/image", methods=["POST"])
@require_role("admin", "pharmacist")
def upload_product_image(product_id):
    product = Product.query.get(product_id)
    if not product:
        return jsonify({"error": "Product not found"}), 404

    file = request.files.get("image")
    if not file or not file.filename:
        return jsonify({"error": "Please choose an image file"}), 400

    data = file.read()
    if len(data) == 0:
        return jsonify({"error": "The file is empty"}), 400
    if len(data) > 2 * 1024 * 1024:
        return jsonify({"error": "Image is too large (maximum 2 MB)"}), 400

    ext = detect_image_type(data)
    if not ext:
        return jsonify({"error": "Only JPG, PNG or WEBP images are allowed"}), 400

    filename = f"product-{product.id}-{uuid.uuid4().hex[:12]}.{ext}"
    folder = os.path.join(current_app.config["UPLOAD_FOLDER"], "products")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, filename), "wb") as out:
        out.write(data)

    old_url = product.image_url
    product.image_url = f"/uploads/products/{filename}"
    db.session.commit()
    delete_image_file(old_url)

    return jsonify({"message": "Image uploaded", "image_url": product.image_url}), 200


@product_bp.route("/<int:product_id>/image", methods=["DELETE"])
@require_role("admin", "pharmacist")
def remove_product_image(product_id):
    product = Product.query.get(product_id)
    if not product:
        return jsonify({"error": "Product not found"}), 404

    old_url = product.image_url
    product.image_url = None
    db.session.commit()
    delete_image_file(old_url)

    return jsonify({"message": "Image removed"}), 200


@product_bp.route("/<int:product_id>", methods=["DELETE"])
@require_role("admin")
def delete_product(product_id):
    product = Product.query.get(product_id)
    if not product:
        return jsonify({"error": "Product not found"}), 404

    old_url = product.image_url
    try:
        db.session.delete(product)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            "error": "This product is part of past orders or sales, so it cannot be deleted. "
                     "Set its stock to 0 instead."
        }), 409

    delete_image_file(old_url)
    sync_alerts()
    return jsonify({"message": "Product deleted"}), 200