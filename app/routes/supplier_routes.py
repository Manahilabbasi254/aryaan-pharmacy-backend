from flask import Blueprint, request, jsonify
from app import db
from app.models import Supplier, PurchaseOrder, PurchaseOrderItem, Product
from app.utils import require_role

supplier_bp = Blueprint("suppliers", __name__, url_prefix="/api/v1/suppliers")


@supplier_bp.route("", methods=["GET"])
@require_role("admin", "pharmacist")
def get_suppliers():
    suppliers = Supplier.query.all()
    return jsonify([{"id": s.id, "name": s.name, "contact_info": s.contact_info} for s in suppliers]), 200


@supplier_bp.route("", methods=["POST"])
@require_role("admin")
def create_supplier():
    data = request.get_json()
    name = data.get("name")
    contact_info = data.get("contact_info")

    if not name:
        return jsonify({"error": "name is required"}), 400

    new_supplier = Supplier(name=name, contact_info=contact_info)
    db.session.add(new_supplier)
    db.session.commit()

    return jsonify({"id": new_supplier.id, "name": new_supplier.name}), 201


@supplier_bp.route("/<int:supplier_id>", methods=["PUT"])
@require_role("admin")
def update_supplier(supplier_id):
    supplier = Supplier.query.get(supplier_id)
    if not supplier:
        return jsonify({"error": "Supplier not found"}), 404

    data = request.get_json()
    supplier.name = data.get("name", supplier.name)
    supplier.contact_info = data.get("contact_info", supplier.contact_info)
    db.session.commit()

    return jsonify({"message": "Supplier updated"}), 200


@supplier_bp.route("/<int:supplier_id>", methods=["DELETE"])
@require_role("admin")
def delete_supplier(supplier_id):
    supplier = Supplier.query.get(supplier_id)
    if not supplier:
        return jsonify({"error": "Supplier not found"}), 404

    db.session.delete(supplier)
    db.session.commit()

    return jsonify({"message": "Supplier deleted"}), 200


@supplier_bp.route("/purchase-orders", methods=["POST"])
@require_role("admin", "pharmacist")
def create_purchase_order():
    data = request.get_json()
    supplier_id = data.get("supplier_id")
    items = data.get("items")

    if not supplier_id or not items or not isinstance(items, list) or len(items) == 0:
        return jsonify({"error": "supplier_id and a non-empty items list are required"}), 400

    supplier = Supplier.query.get(supplier_id)
    if not supplier:
        return jsonify({"error": "Supplier not found"}), 404

    new_po = PurchaseOrder(supplier_id=supplier_id, status="pending")
    db.session.add(new_po)
    db.session.flush()

    for item in items:
        product_id = item.get("product_id")
        quantity = item.get("quantity")
        unit_cost = item.get("unit_cost")

        if not product_id or not quantity or unit_cost is None:
            return jsonify({"error": "Each item needs product_id, quantity, and unit_cost"}), 400

        product = Product.query.get(product_id)
        if not product:
            return jsonify({"error": f"Product {product_id} not found"}), 404

        db.session.add(PurchaseOrderItem(
            purchase_order_id=new_po.id,
            product_id=product_id,
            quantity=quantity,
            unit_cost=unit_cost
        ))

    db.session.commit()

    return jsonify({"message": "Purchase order created", "purchase_order_id": new_po.id}), 201


@supplier_bp.route("/purchase-orders", methods=["GET"])
@require_role("admin", "pharmacist")
def get_purchase_orders():
    purchase_orders = PurchaseOrder.query.all()
    return jsonify([{
        "id": po.id,
        "supplier_id": po.supplier_id,
        "supplier_name": po.supplier.name,
        "status": po.status,
        "order_date": po.order_date.isoformat()
    } for po in purchase_orders]), 200


@supplier_bp.route("/purchase-orders/<int:po_id>/receive", methods=["PUT"])
@require_role("admin", "pharmacist")
def receive_purchase_order(po_id):
    po = PurchaseOrder.query.get(po_id)
    if not po:
        return jsonify({"error": "Purchase order not found"}), 404

    if po.status == "received":
        return jsonify({"error": "This purchase order has already been received"}), 409

    for item in po.items:
        item.product.stock_qty += item.quantity

    po.status = "received"
    db.session.commit()

    return jsonify({"message": "Purchase order received, stock updated", "id": po.id}), 200