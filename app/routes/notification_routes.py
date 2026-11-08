from flask import Blueprint, jsonify

from app import db
from app.alerts import sync_alerts
from app.models import Notification
from app.utils import require_role

notification_bp = Blueprint("notifications", __name__, url_prefix="/api/v1/notifications")


@notification_bp.route("/generate", methods=["POST"])
@require_role("admin", "pharmacist")
def generate_notifications():
    created, resolved = sync_alerts()
    return jsonify({"message": f"{created} new alert(s), {resolved} resolved"}), 200


@notification_bp.route("", methods=["GET"])
@require_role("admin", "pharmacist")
def get_notifications():
    sync_alerts()
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