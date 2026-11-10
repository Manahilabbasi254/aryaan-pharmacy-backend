import csv
import io
from datetime import datetime, timedelta

from flask import Blueprint, Response
from app.models import Sale, Product, Expense
from app.routes.report_routes import get_days, period_bounds, PK_OFFSET, LOW_STOCK_THRESHOLD
from app.utils import require_role

report_export_bp = Blueprint("report_exports", __name__, url_prefix="/api/v1/reports/export")


def safe(value):
    """Stop spreadsheet formula tricks: text starting with = + - @ is made plain text."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def csv_response(filename, header, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    for row in rows:
        writer.writerow([safe(v) for v in row])
    # utf-8-sig so Excel opens it correctly
    data = buffer.getvalue().encode("utf-8-sig")
    return Response(
        data,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@report_export_bp.route("/sales", methods=["GET"])
@require_role("admin", "pharmacist")
def export_sales():
    days = get_days()
    _, start_utc, today_pk = period_bounds(days)

    sales = (
        Sale.query.filter(Sale.sale_date >= start_utc)
        .order_by(Sale.sale_date.asc())
        .all()
    )

    rows = []
    for s in sales:
        order = s.order
        t = s.transaction
        rows.append([
            s.invoice_number,
            (s.sale_date + PK_OFFSET).strftime("%Y-%m-%d %H:%M"),
            order.id,
            order.order_type,
            order.status,
            order.user.name if order.user else "",
            sum(i.quantity for i in order.items),
            float(order.total_amount),
            float(t.discount_amount or 0) if t else 0,
            float(t.tax_amount or 0) if t else 0,
            float(t.paid_amount) if t else 0,
            (t.payment_method or "") if t else "",
        ])

    return csv_response(
        f"sales-last-{days}-days-{today_pk.isoformat()}.csv",
        ["Invoice", "Date (PKT)", "Order #", "Type", "Status", "Customer",
         "Items", "Order total", "Discount", "Tax", "Paid", "Payment method"],
        rows,
    )


@report_export_bp.route("/inventory", methods=["GET"])
@require_role("admin", "pharmacist")
def export_inventory():
    today_pk = (datetime.utcnow() + PK_OFFSET).date()
    soon = today_pk + timedelta(days=30)

    rows = []
    for p in Product.query.order_by(Product.name.asc()).all():
        if p.stock_qty == 0:
            status = "Out of stock"
        elif p.stock_qty < LOW_STOCK_THRESHOLD:
            status = "Low stock"
        else:
            status = "OK"
        if p.expiry_date and p.expiry_date < today_pk:
            status += " / Expired"
        elif p.expiry_date and p.expiry_date <= soon:
            status += " / Expiring soon"
        rows.append([
            p.id,
            p.name,
            p.category.name if p.category else "",
            float(p.price),
            p.stock_qty,
            p.expiry_date.isoformat() if p.expiry_date else "",
            status,
        ])

    return csv_response(
        f"inventory-{today_pk.isoformat()}.csv",
        ["ID", "Product", "Category", "Price", "Stock", "Expiry date", "Status"],
        rows,
    )


@report_export_bp.route("/expenses", methods=["GET"])
@require_role("admin")
def export_expenses():
    days = get_days()
    start_date, _, today_pk = period_bounds(days)

    expenses = (
        Expense.query.filter(Expense.expense_date >= start_date, Expense.expense_date <= today_pk)
        .order_by(Expense.expense_date.asc())
        .all()
    )
    rows = [
        [e.id, e.expense_date.isoformat(), e.category, float(e.amount), e.description or ""]
        for e in expenses
    ]
    rows.append(["", "", "TOTAL", round(sum(float(e.amount) for e in expenses), 2), ""])

    return csv_response(
        f"expenses-last-{days}-days-{today_pk.isoformat()}.csv",
        ["ID", "Date", "Category", "Amount", "Description"],
        rows,
    )