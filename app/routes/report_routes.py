from flask import Blueprint, jsonify, request
from app import db
from app.models import Sale, Transaction, Order, Product, OrderItem
from app.utils import require_role
from sqlalchemy import func
from datetime import datetime, timedelta

report_bp = Blueprint("reports", __name__, url_prefix="/api/v1/reports")


@report_bp.route("/sales-performance", methods=["GET"])
@require_role("admin", "pharmacist")
def sales_performance():
    days = int(request.args.get("days", 30))
    cutoff = datetime.utcnow() - timedelta(days=days)

    sales = Sale.query.filter(Sale.sale_date >= cutoff).all()

    total_sales = len(sales)
    total_revenue = sum(float(s.transaction.paid_amount) for s in sales if s.transaction)

    best_sellers = (
        db.session.query(
            Product.name,
            func.sum(OrderItem.quantity).label("total_sold")
        )
        .join(OrderItem, OrderItem.product_id == Product.id)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Sale, Sale.order_id == Order.id)
        .filter(Sale.sale_date >= cutoff)
        .group_by(Product.name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(5)
        .all()
    )

    return jsonify({
        "period_days": days,
        "total_sales": total_sales,
        "total_revenue": round(total_revenue, 2),
        "top_selling_products": [{"name": name, "quantity_sold": int(qty)} for name, qty in best_sellers]
    }), 200


@report_bp.route("/inventory-health", methods=["GET"])
@require_role("admin", "pharmacist")
def inventory_health():
    total_products = Product.query.count()
    low_stock_count = Product.query.filter(Product.stock_qty < 20).count()

    expiry_cutoff = datetime.utcnow().date() + timedelta(days=30)
    expiring_soon_count = Product.query.filter(
        Product.expiry_date != None,
        Product.expiry_date <= expiry_cutoff
    ).count()

    out_of_stock_count = Product.query.filter(Product.stock_qty == 0).count()

    return jsonify({
        "total_products": total_products,
        "low_stock_count": low_stock_count,
        "out_of_stock_count": out_of_stock_count,
        "expiring_within_30_days": expiring_soon_count
    }), 200


@report_bp.route("/transactions", methods=["GET"])
@require_role("admin", "pharmacist")
def transaction_report():
    days = int(request.args.get("days", 30))
    cutoff = datetime.utcnow() - timedelta(days=days)

    transactions = (
        db.session.query(Transaction)
        .join(Sale, Sale.id == Transaction.sale_id)
        .filter(Sale.sale_date >= cutoff)
        .all()
    )

    total_tax = sum(float(t.tax_amount) for t in transactions)
    total_discount = sum(float(t.discount_amount) for t in transactions)
    total_paid = sum(float(t.paid_amount) for t in transactions)

    by_payment_method = {}
    for t in transactions:
        method = t.payment_method or "unspecified"
        by_payment_method[method] = by_payment_method.get(method, 0) + float(t.paid_amount)

    return jsonify({
        "period_days": days,
        "transaction_count": len(transactions),
        "total_tax_collected": round(total_tax, 2),
        "total_discount_given": round(total_discount, 2),
        "total_paid_amount": round(total_paid, 2),
        "breakdown_by_payment_method": {k: round(v, 2) for k, v in by_payment_method.items()}
    }), 200