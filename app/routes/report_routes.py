from flask import Blueprint, jsonify, request
from app import db
from app.models import Sale, Transaction, Order, Product, OrderItem, Expense
from app.utils import require_role
from sqlalchemy import func
from datetime import datetime, timedelta, time

report_bp = Blueprint("reports", __name__, url_prefix="/api/v1/reports")

PK_OFFSET = timedelta(hours=5)  # Asia/Karachi
LOW_STOCK_THRESHOLD = 20
EXPIRY_WARNING_DAYS = 30


def get_days():
    try:
        days = int(request.args.get("days", 30))
    except (TypeError, ValueError):
        days = 30
    return max(1, min(days, 365))


def period_bounds(days):
    """Returns (first local date, UTC start datetime, today's local date)."""
    today_pk = (datetime.utcnow() + PK_OFFSET).date()
    start_date = today_pk - timedelta(days=days - 1)
    start_utc = datetime.combine(start_date, time.min) - PK_OFFSET
    return start_date, start_utc, today_pk


@report_bp.route("/sales-performance", methods=["GET"])
@require_role("admin", "pharmacist")
def sales_performance():
    days = get_days()
    start_date, start_utc, today_pk = period_bounds(days)

    sales = Sale.query.filter(Sale.sale_date >= start_utc).all()

    daily = {}
    for i in range(days):
        d = start_date + timedelta(days=i)
        daily[d] = {"date": d.isoformat(), "revenue": 0.0, "count": 0}

    total_revenue = 0.0
    for s in sales:
        if not s.transaction:
            continue
        paid = float(s.transaction.paid_amount)
        total_revenue += paid
        local_day = (s.sale_date + PK_OFFSET).date()
        if local_day in daily:
            daily[local_day]["revenue"] += paid
            daily[local_day]["count"] += 1

    best_sellers = (
        db.session.query(
            Product.name,
            func.sum(OrderItem.quantity).label("total_sold")
        )
        .join(OrderItem, OrderItem.product_id == Product.id)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Sale, Sale.order_id == Order.id)
        .filter(Sale.sale_date >= start_utc)
        .group_by(Product.name)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(5)
        .all()
    )

    return jsonify({
        "period_days": days,
        "total_sales": len(sales),
        "total_revenue": round(total_revenue, 2),
        "daily": [
            {"date": v["date"], "revenue": round(v["revenue"], 2), "count": v["count"]}
            for v in daily.values()
        ],
        "top_selling_products": [
            {"name": name, "quantity_sold": int(qty)} for name, qty in best_sellers
        ]
    }), 200


@report_bp.route("/inventory-health", methods=["GET"])
@require_role("admin", "pharmacist")
def inventory_health():
    today_pk = (datetime.utcnow() + PK_OFFSET).date()
    expiry_cutoff = today_pk + timedelta(days=EXPIRY_WARNING_DAYS)

    total_products = Product.query.count()
    out_of_stock_count = Product.query.filter(Product.stock_qty == 0).count()

    low_stock = (
        Product.query.filter(Product.stock_qty < LOW_STOCK_THRESHOLD)
        .order_by(Product.stock_qty.asc())
        .limit(50)
        .all()
    )
    expiring = (
        Product.query.filter(
            Product.expiry_date != None,
            Product.expiry_date <= expiry_cutoff
        )
        .order_by(Product.expiry_date.asc())
        .limit(50)
        .all()
    )

    return jsonify({
        "total_products": total_products,
        "low_stock_count": len(low_stock),
        "out_of_stock_count": out_of_stock_count,
        "expiring_within_30_days": len(expiring),
        "low_stock_items": [
            {"id": p.id, "name": p.name, "stock_qty": p.stock_qty} for p in low_stock
        ],
        "expiring_items": [
            {
                "id": p.id,
                "name": p.name,
                "stock_qty": p.stock_qty,
                "expiry_date": p.expiry_date.isoformat(),
                "status": "expired" if p.expiry_date < today_pk else "expiring"
            }
            for p in expiring
        ]
    }), 200


@report_bp.route("/transactions", methods=["GET"])
@require_role("admin", "pharmacist")
def transaction_report():
    days = get_days()
    _, start_utc, _ = period_bounds(days)

    transactions = (
        db.session.query(Transaction)
        .join(Sale, Sale.id == Transaction.sale_id)
        .filter(Sale.sale_date >= start_utc)
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


@report_bp.route("/profit", methods=["GET"])
@require_role("admin")
def profit_report():
    days = get_days()
    start_date, start_utc, today_pk = period_bounds(days)

    transactions = (
        db.session.query(Transaction)
        .join(Sale, Sale.id == Transaction.sale_id)
        .filter(Sale.sale_date >= start_utc)
        .all()
    )
    revenue = sum(float(t.paid_amount) for t in transactions)

    expenses = (
        db.session.query(func.coalesce(func.sum(Expense.amount), 0))
        .filter(Expense.expense_date >= start_date, Expense.expense_date <= today_pk)
        .scalar()
    )
    expenses = float(expenses)

    return jsonify({
        "period_days": days,
        "revenue": round(revenue, 2),
        "expenses": round(expenses, 2),
        "net": round(revenue - expenses, 2)
    }), 200