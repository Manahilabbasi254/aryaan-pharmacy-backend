from datetime import date
from decimal import Decimal, InvalidOperation

from flask import Blueprint, request, jsonify
from app import db
from app.models import Order, OrderItem, Product, Sale, Transaction
from app.utils import require_role
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from app.routes.sale_routes import generate_invoice_number
from app.alerts import sync_alerts

order_bp = Blueprint("orders", __name__, url_prefix="/api/v1/orders")

# Which status changes are allowed. Fulfilled and cancelled are final.
ALLOWED_TRANSITIONS = {
    "pending": ["processing", "fulfilled", "cancelled"],
    "processing": ["fulfilled", "cancelled"],
    "fulfilled": [],
    "cancelled": [],
}


def to_money(value, field):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field} must be a number")
    if not amount.is_finite():
        raise ValueError(f"{field} must be a number")
    if amount < 0:
        raise ValueError(f"{field} cannot be negative")
    return amount.quantize(Decimal("0.01"))


@order_bp.route("", methods=["POST"])
@jwt_required()
def create_order():
    claims = get_jwt()
    user_id = get_jwt_identity()
    role = claims.get("role")

    data = request.get_json() or {}
    items = data.get("items")

    if not items or not isinstance(items, list) or len(items) == 0:
        return jsonify({"error": "items must be a non-empty list"}), 400

    order_type = "online" if role == "customer" else "walk-in"

    # Step 1: check the shape of every line and add up quantity per product
    lines = []
    requested = {}
    for item in items:
        if not isinstance(item, dict):
            return jsonify({"error": "Each item needs a valid product_id and quantity"}), 400

        product_id = item.get("product_id")
        quantity = item.get("quantity")

        if (
            not isinstance(product_id, int)
            or isinstance(product_id, bool)
            or not isinstance(quantity, int)
            or isinstance(quantity, bool)
            or quantity <= 0
        ):
            return jsonify({"error": "Each item needs a valid product_id and quantity"}), 400

        lines.append((product_id, quantity))
        requested[product_id] = requested.get(product_id, 0) + quantity

    # Step 2: lock each product row so two orders cannot take the same last item
    products = {}
    for product_id in sorted(requested):
        product = Product.query.filter_by(id=product_id).with_for_update().first()
        if not product:
            return jsonify({"error": f"Product {product_id} not found"}), 404

        if product.expiry_date and product.expiry_date < date.today():
            return jsonify({"error": f"'{product.name}' has expired and cannot be ordered"}), 409

        if product.stock_qty < requested[product_id]:
            return jsonify({
                "error": f"Insufficient stock for '{product.name}'. Available: {product.stock_qty}, requested: {requested[product_id]}"
            }), 409

        products[product_id] = product

    # Step 3: work out the total with exact decimals
    total_amount = Decimal("0.00")
    for product_id, quantity in lines:
        total_amount += Decimal(str(products[product_id].price)) * quantity

    new_order = Order(
        user_id=user_id,
        order_type=order_type,
        status="pending",
        total_amount=total_amount
    )
    db.session.add(new_order)