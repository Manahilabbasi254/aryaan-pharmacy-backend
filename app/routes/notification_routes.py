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
    resolved_count = 0
    today = datetime.utcnow().date()
    expiry_cutoff = today + timedelta(days=EXPIRY_WARNING_DAYS)

    # 1) Close old unread alerts whose problem no longer exists
    open_alerts = Notification.query.filter_by(is_read=False).all()
    for n in open_alerts:
        product = Product.query.get(n.product_id) if n.product_id else None
        if product is None:
            n.is_read = True
            resolved_count += 1
            continue
        if n.type == "low_stock":
            if product.stock_qty >= LOW_STOCK_THRESHOLD:
                n.is_read = True
                resolved_count += 1
            else:
                n.message = f"Low stock alert: '{product.name}' has only {product.stock_qty} units left."
        elif n.type == "expiry":
            if product.expiry_date is None or product.expiry_date > expiry_cutoff:
                n.is_read = True
                resolved_count += 1

    # 2) Create alerts for current problems (no duplicates)
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

    expiring_products = Product.query.filter(
        Product.expiry_date != None,
        Product.expiry_date <= expiry_cutoff
    ).all()
    for product in expiring_products:
        existing = Notification.query.filter_by(
            product_id=product.id, type="expiry", is_read=False
        ).first()
        if not existing:
            if product.expiry_date < today:
                text = f"Expired: '{product.name}' expired on {product.expiry_date.isoformat()}."
            else:
                text = f"Expiry alert: '{product.name}' expires on {product.expiry_date.isoformat()}."
            db.session.add(Notification(
                type="expiry",
                product_id=product.id,
                message=text
            ))
            created_count += 1

    db.session.commit()

    return jsonify({
        "message": f"{created_count} new alert(s), {resolved_count} resolved"
    }), 200


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