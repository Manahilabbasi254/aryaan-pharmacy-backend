from datetime import date
from decimal import Decimal, InvalidOperation

from flask import Blueprint, request, jsonify
from app import db
from app.models import Order, OrderItem, Product, Sale, Transaction
from app.utils import require_role
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from app.routes.sale_routes import generate_invoice_number

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
    db.session.flush()

    for product_id, quantity in lines:
        product = products[product_id]
        db.session.add(OrderItem(
            order_id=new_order.id,
            product_id=product.id,
            quantity=quantity,
            unit_price=product.price
        ))
        product.stock_qty -= quantity

    db.session.commit()

    return jsonify({
        "message": "Order created successfully",
        "order_id": new_order.id,
        "order_type": new_order.order_type,
        "total_amount": float(new_order.total_amount),
        "status": new_order.status
    }), 201


@order_bp.route("", methods=["GET"])
@jwt_required()
def get_orders():
    claims = get_jwt()
    user_id = get_jwt_identity()
    role = claims.get("role")

    if role in ("admin", "pharmacist"):
        orders = Order.query.all()
    else:
        orders = Order.query.filter_by(user_id=user_id).all()

    return jsonify([{
        "id": o.id,
        "order_type": o.order_type,
        "status": o.status,
        "total_amount": float(o.total_amount),
        "created_at": o.created_at.isoformat()
    } for o in orders]), 200


@order_bp.route("/<int:order_id>", methods=["GET"])
@jwt_required()
def get_order(order_id):
    claims = get_jwt()
    user_id = get_jwt_identity()
    role = claims.get("role")

    order = Order.query.get(order_id)
    if not order:
        return jsonify({"error": "Order not found"}), 404

    if role not in ("admin", "pharmacist") and str(order.user_id) != user_id:
        return jsonify({"error": "You do not have permission to view this order"}), 403

    items = [{
        "product_id": i.product_id,
        "product_name": i.product.name,
        "quantity": i.quantity,
        "unit_price": float(i.unit_price)
    } for i in order.items]

    return jsonify({
        "id": order.id,
        "order_type": order.order_type,
        "status": order.status,
        "total_amount": float(order.total_amount),
        "created_at": order.created_at.isoformat(),
        "items": items
    }), 200


@order_bp.route("/<int:order_id>/status", methods=["PUT"])
@require_role("admin", "pharmacist")
def update_order_status(order_id):
    order = Order.query.get(order_id)
    if not order:
        return jsonify({"error": "Order not found"}), 404

    data = request.get_json() or {}
    new_status = data.get("status")

    valid_statuses = ["pending", "processing", "fulfilled", "cancelled"]
    if new_status not in valid_statuses:
        return jsonify({"error": f"status must be one of {valid_statuses}"}), 400

    if new_status == order.status:
        return jsonify({"error": f"Order is already {order.status}"}), 409

    if new_status not in ALLOWED_TRANSITIONS[order.status]:
        return jsonify({
            "error": f"An order that is {order.status} cannot be changed to {new_status}"
        }), 409

    # Check the money fields first, before changing anything
    tax_amount = Decimal("0.00")
    discount_amount = Decimal("0.00")
    final_amount = None
    if new_status == "fulfilled" and not order.sale:
        try:
            tax_amount = to_money(data.get("tax_amount", 0), "tax_amount")
            discount_amount = to_money(data.get("discount_amount", 0), "discount_amount")
        except ValueError as err:
            return jsonify({"error": str(err)}), 400

        final_amount = Decimal(str(order.total_amount)) + tax_amount - discount_amount
        if final_amount < 0:
            return jsonify({"error": "discount_amount cannot be more than the order total plus tax"}), 400

    # Cancelling gives the stock back
    if new_status == "cancelled":
        for item in sorted(order.items, key=lambda i: i.product_id):
            product = Product.query.filter_by(id=item.product_id).with_for_update().first()
            if product:
                product.stock_qty += item.quantity

    order.status = new_status

    if final_amount is not None:
        payment_method = data.get("payment_method", "cash")

        new_sale = Sale(
            order_id=order.id,
            invoice_number=generate_invoice_number()
        )
        db.session.add(new_sale)
        db.session.flush()

        new_transaction = Transaction(
            sale_id=new_sale.id,
            tax_amount=tax_amount,
            discount_amount=discount_amount,
            payment_method=payment_method,
            paid_amount=final_amount,
            status="completed"
        )
        db.session.add(new_transaction)

    db.session.commit()

    response = {"message": "Order status updated", "id": order.id, "status": order.status}

    if new_status == "fulfilled" and order.sale:
        response["invoice_number"] = order.sale.invoice_number

    return jsonify(response), 200