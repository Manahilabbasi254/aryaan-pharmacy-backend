from flask import Blueprint, request, jsonify
from app import db
from app.models import Order, OrderItem, Product
from app.utils import require_role
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

order_bp = Blueprint("orders", __name__, url_prefix="/api/v1/orders")


@order_bp.route("", methods=["POST"])
@jwt_required()
def create_order():
    claims = get_jwt()
    user_id = get_jwt_identity()
    role = claims.get("role")

    data = request.get_json()
    items = data.get("items")

    if not items or not isinstance(items, list) or len(items) == 0:
        return jsonify({"error": "items must be a non-empty list"}), 400

    order_type = "online" if role == "customer" else "walk-in"

    total_amount = 0
    validated_items = []

    for item in items:
        product_id = item.get("product_id")
        quantity = item.get("quantity")

        if not product_id or not quantity or quantity <= 0:
            return jsonify({"error": "Each item needs a valid product_id and quantity"}), 400

        product = Product.query.get(product_id)
        if not product:
            return jsonify({"error": f"Product {product_id} not found"}), 404

        if product.stock_qty < quantity:
            return jsonify({
                "error": f"Insufficient stock for '{product.name}'. Available: {product.stock_qty}, requested: {quantity}"
            }), 409

        line_total = float(product.price) * quantity
        total_amount += line_total

        validated_items.append({
            "product": product,
            "quantity": quantity,
            "unit_price": product.price
        })

    new_order = Order(
        user_id=user_id,
        order_type=order_type,
        status="pending",
        total_amount=total_amount
    )
    db.session.add(new_order)
    db.session.flush()

    for entry in validated_items:
        order_item = OrderItem(
            order_id=new_order.id,
            product_id=entry["product"].id,
            quantity=entry["quantity"],
            unit_price=entry["unit_price"]
        )
        db.session.add(order_item)

        entry["product"].stock_qty -= entry["quantity"]

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

    data = request.get_json()
    new_status = data.get("status")

    valid_statuses = ["pending", "processing", "fulfilled", "cancelled"]
    if new_status not in valid_statuses:
        return jsonify({"error": f"status must be one of {valid_statuses}"}), 400

    order.status = new_status
    db.session.commit()

    return jsonify({"message": "Order status updated", "id": order.id, "status": order.status}), 200