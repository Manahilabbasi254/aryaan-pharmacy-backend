from flask import Blueprint, request, jsonify
from app import db
from app.models import Sale, Order
from app.utils import require_role
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
import uuid

sale_bp = Blueprint("sales", __name__, url_prefix="/api/v1/sales")


@sale_bp.route("", methods=["GET"])
@require_role("admin", "pharmacist")
def get_sales():
    sales = Sale.query.all()
    return jsonify([{
        "id": s.id,
        "order_id": s.order_id,
        "invoice_number": s.invoice_number,
        "sale_date": s.sale_date.isoformat(),
        "total_amount": float(s.order.total_amount)
    } for s in sales]), 200


@sale_bp.route("/<int:sale_id>", methods=["GET"])
@jwt_required()
def get_sale(sale_id):
    claims = get_jwt()
    user_id = get_jwt_identity()
    role = claims.get("role")

    sale = Sale.query.get(sale_id)
    if not sale:
        return jsonify({"error": "Sale not found"}), 404

    if role not in ("admin", "pharmacist") and str(sale.order.user_id) != user_id:
        return jsonify({"error": "You do not have permission to view this sale"}), 403

    items = [{
        "product_name": i.product.name,
        "quantity": i.quantity,
        "unit_price": float(i.unit_price),
        "line_total": float(i.unit_price) * i.quantity
    } for i in sale.order.items]

    return jsonify({
        "id": sale.id,
        "invoice_number": sale.invoice_number,
        "sale_date": sale.sale_date.isoformat(),
        "order_id": sale.order_id,
        "total_amount": float(sale.order.total_amount),
        "items": items,
        "transaction": {
            "tax_amount": float(sale.transaction.tax_amount),
            "discount_amount": float(sale.transaction.discount_amount),
            "payment_method": sale.transaction.payment_method,
            "paid_amount": float(sale.transaction.paid_amount),
            "status": sale.transaction.status
        } if sale.transaction else None
    }), 200


def generate_invoice_number():
    return f"INV-{uuid.uuid4().hex[:8].upper()}"