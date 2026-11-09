from decimal import Decimal, InvalidOperation

from flask import Blueprint, request, jsonify
from sqlalchemy.exc import IntegrityError

from app import db
from app.alerts import sync_alerts
from app.models import Supplier, PurchaseOrder, PurchaseOrderItem, Product
from app.utils import require_role

supplier_bp = Blueprint("suppliers", __name__, url_prefix="/api/v1/suppliers")


def clean_supplier(data, partial=False):
    values = {}
    if not partial or "name" in data:
        name = (data.get("name") or "").strip()
        if len(name) < 2 or len(name) > 100:
            return None, "Supplier name must be 2 to 100 characters"
        values["name"] = name
    if "contact_info" in data:
        contact = (data.get("contact_info") or "").strip()
        if len(contact) > 200:
            return None, "Contact info is too long (max 200 characters)"
        values["contact_info"] = contact or None
    return values, None


def purchase_order_to_dict(po):
    items = []
    total = Decimal("0.00")
    for i in po.items:
        line_total = Decimal(str(i.unit_cost)) * i.quantity
        total += line_total
        items.append({
            "product_id": i.product_id,
            "product_name": i.product.name,
            "quantity": i.quantity,
            "unit_cost": float(i.unit_cost),
            "line_total": float(line_total),
        })
    return {
        "id": po.id,
        "supplier_id": po.supplier_id,
        "supplier_name": po.supplier.name,
        "status": po.status,
        "order_date": po.order_date.isoformat(),
        "items": items,
        "total_cost": float(total),
    }


@supplier_bp.route("", methods=["GET"])
@require_role("admin", "pharmacist")
def get_suppliers():
    suppliers = Supplier.query.order_by(Supplier.name.asc()).all()
    return jsonify([{"id": s.id, "name": s.name, "contact_info": s.contact_info} for s in suppliers]), 200


@supplier_bp.route("", methods=["POST"])
@require_role("admin")
def create_supplier():
    data = request.get_json(silent=True) or {}
    values, error = clean_supplier(data)
    if error:
        return jsonify({"error": error}), 400

    if Supplier.query.filter(db.func.lower(Supplier.name) == values["name"].lower()).first():
        return jsonify({"error": "A supplier with this name already exists"}), 409

    new_supplier = Supplier(name=values["name"], contact_info=values.get("contact_info"))
    db.session.add(new_supplier)
    db.session.commit()

    return jsonify({"id": new_supplier.id, "name": new_supplier.name}), 201


@supplier_bp.route("/<int:supplier_id>", methods=["PUT"])
@require_role("admin")
def update_supplier(supplier_id):
    supplier = Supplier.query.get(supplier_id)
    if not supplier:
        return jsonify({"error": "Supplier not found"}), 404

    data = request.get_json(silent=True) or {}
    values, error = clean_supplier(data, partial=True)
    if error:
        return jsonify({"error": error}), 400

    if "name" in values:
        clash = Supplier.query.filter(
            db.func.lower(Supplier.name) == values["name"].lower(),
            Supplier.id != supplier_id,
        ).first()
        if clash:
            return jsonify({"error": "Another supplier already has this name"}), 409

    for key, value in values.items():
        setattr(supplier, key, value)
    db.session.commit()

    return jsonify({"message": "Supplier updated"}), 200


@supplier_bp.route("/<int:supplier_id>", methods=["DELETE"])
@require_role("admin")
def delete_supplier(supplier_id):
    supplier = Supplier.query.get(supplier_id)
    if not supplier:
        return jsonify({"error": "Supplier not found"}), 404

    try:
        db.session.delete(supplier)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "This supplier has purchase orders, so it cannot be deleted."}), 409

    return jsonify({"message": "Supplier deleted"}), 200


@supplier_bp.route("/purchase-orders", methods=["POST"])
@require_role("admin", "pharmacist")
def create_purchase_order():
    data = request.get_json(silent=True) or {}
    supplier_id = data.get("supplier_id")
    items = data.get("items")

    if not supplier_id or not isinstance(items, list) or len(items) == 0:
        return jsonify({"error": "supplier_id and a non-empty items list are required"}), 400

    supplier = Supplier.query.get(supplier_id)
    if not supplier:
        return jsonify({"error": "Supplier not found"}), 404

    # Validate every line before creating anything
    clean_items = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            return jsonify({"error": "Each item needs product_id, quantity, and unit_cost"}), 400

        product_id = item.get("product_id")
        quantity = item.get("quantity")
        if (
            not isinstance(product_id, int) or isinstance(product_id, bool)
            or not isinstance(quantity, int) or isinstance(quantity, bool)
            or quantity <= 0 or quantity > 1000000
        ):
            return jsonify({"error": "Each item needs a valid product and a quantity above 0"}), 400

        try:
            unit_cost = Decimal(str(item.get("unit_cost")))
        except (InvalidOperation, TypeError):
            return jsonify({"error": "Unit cost must be a number"}), 400
        if not unit_cost.is_finite() or unit_cost <= 0 or unit_cost > Decimal("10000000"):
            return jsonify({"error": "Unit cost must be greater than 0"}), 400

        if product_id in seen:
            return jsonify({"error": "The same product is listed twice. Combine it into one line."}), 400
        seen.add(product_id)

        if not Product.query.get(product_id):
            return jsonify({"error": f"Product {product_id} not found"}), 404

        clean_items.append((product_id, quantity, unit_cost.quantize(Decimal("0.01"))))

    new_po = PurchaseOrder(supplier_id=supplier_id, status="pending")
    db.session.add(new_po)
    db.session.flush()

    for product_id, quantity, unit_cost in clean_items:
        db.session.add(PurchaseOrderItem(
            purchase_order_id=new_po.id,
            product_id=product_id,
            quantity=quantity,
            unit_cost=unit_cost,
        ))

    db.session.commit()

    return jsonify({"message": "Purchase order created", "purchase_order_id": new_po.id}), 201


@supplier_bp.route("/purchase-orders", methods=["GET"])
@require_role("admin", "pharmacist")
def get_purchase_orders():
    purchase_orders = PurchaseOrder.query.order_by(PurchaseOrder.order_date.desc()).all()
    return jsonify([purchase_order_to_dict(po) for po in purchase_orders]), 200


@supplier_bp.route("/purchase-orders/<int:po_id>/receive", methods=["PUT"])
@require_role("admin", "pharmacist")
def receive_purchase_order(po_id):
    # Lock the purchase order so a double click cannot add the stock twice
    po = PurchaseOrder.query.filter_by(id=po_id).with_for_update().first()
    if not po:
        return jsonify({"error": "Purchase order not found"}), 404

    if po.status == "received":
        return jsonify({"error": "This purchase order has already been received"}), 409

    for item in sorted(po.items, key=lambda i: i.product_id):
        product = Product.query.filter_by(id=item.product_id).with_for_update().first()
        if product:
            product.stock_qty += item.quantity

    po.status = "received"
    db.session.commit()
    sync_alerts()

    return jsonify({"message": "Purchase order received, stock updated", "id": po.id}), 200