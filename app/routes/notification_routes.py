from flask import Blueprint, jsonify
from app import db
from app.models import Notification, Product
from app.utils import require_role
from datetime import datetime, timedelta

notification_bp = Blueprint("notifications", __name__, url_prefix="/api/v1/notifications")

LOW_STOCK_THRESHOLD = 20
EXPIRY_WARNING_DAYS = 30


@notification_bp.route("/generate", methods=["POST"])
@require_role("admin", "pharmacist")
def generate_notifications():
    created_count = 0

    low_stock_products = Product.query.filter(Product.stock_qty < LOW_STOCK_THRESHOLD).all()
    for product in low_stock_products:
        existing = Notification.query.filter_by(
            product_id=product.id, type="low_stock", is_read=False
        ).first()
        if not existing:
            db.session.add(Notification(
                type="low_stock",
                product_id=product.id,
                message=f"Low stock alert: '{product.name}' has only {product.stock_qty} units left."
            ))
            created_count += 1

    expiry_cutoff = datetime.utcnow().date() + timedelta(days=EXPIRY_WARNING_DAYS)
    expiring_products = Product.query.filter(
        Product.expiry_date != None,
        Product.expiry_date <= expiry_cutoff
    ).all()
    for product in expiring_products:
        existing = Notification.query.filter_by(
            product_id=product.id, type="expiry", is_read=False
        ).first()
        if not existing:
            db.session.add(Notification(
                type="expiry",
                product_id=product.id,
                message=f"Expiry alert: '{product.name}' expires on {product.expiry_date.isoformat()}."
            ))
            created_count += 1

    db.session.commit()

    return jsonify({"message": f"{created_count} new notification(s) generated"}), 200


@notification_bp.route("", methods=["GET"])
@require_role("admin", "pharmacist")
def get_notifications():
    notifications = Notification.query.order_by(Notification.created_at.desc()).all()
    return jsonify([{
        "id": n.id,
        "type": n.type,
        "product_id": n.product_id,
        "message": n.message,
        "is_read": n.is_read,
        "created_at": n.created_at.isoformat()
    } for n in notifications]), 200


@notification_bp.route("/<int:notification_id>/read", methods=["PUT"])
@require_role("admin", "pharmacist")
def mark_as_read(notification_id):
    notification = Notification.query.get(notification_id)
    if not notification:
        return jsonify({"error": "Notification not found"}), 404

    notification.is_read = True
    db.session.commit()

    return jsonify({"message": "Notification marked as read"}), 200