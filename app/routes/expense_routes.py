from flask import Blueprint, request, jsonify
from app import db
from app.models import Expense
from app.utils import require_role
from flask_jwt_extended import get_jwt_identity
from datetime import datetime
from decimal import Decimal, InvalidOperation
from sqlalchemy import func

expense_bp = Blueprint("expenses", __name__, url_prefix="/api/v1/expenses")

VALID_CATEGORIES = ["rent", "utilities", "salary", "other"]


def parse_amount(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount <= 0:
        return None
    return amount.quantize(Decimal("0.01"))


def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def apply_filters(query):
    category = request.args.get("category")
    date_from = request.args.get("from")
    date_to = request.args.get("to")
    if category:
        query = query.filter(Expense.category == category)
    if date_from:
        query = query.filter(Expense.expense_date >= parse_date(date_from))
    if date_to:
        query = query.filter(Expense.expense_date <= parse_date(date_to))
    return query


def expense_to_dict(e):
    return {
        "id": e.id,
        "category": e.category,
        "amount": float(e.amount),
        "description": e.description,
        "expense_date": e.expense_date.isoformat()
    }


@expense_bp.route("", methods=["POST"])
@require_role("admin")
def create_expense():
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}

    category = data.get("category")
    amount = parse_amount(data.get("amount"))
    description = (data.get("description") or "").strip() or None
    expense_date = data.get("expense_date")

    if category not in VALID_CATEGORIES:
        return jsonify({"error": f"category must be one of {VALID_CATEGORIES}"}), 400
    if amount is None:
        return jsonify({"error": "amount must be a positive number"}), 400
    try:
        the_date = parse_date(expense_date) if expense_date else datetime.utcnow().date()
    except ValueError:
        return jsonify({"error": "expense_date must be in YYYY-MM-DD format"}), 400

    new_expense = Expense(
        category=category,
        amount=amount,
        description=description,
        expense_date=the_date,
        recorded_by=user_id
    )
    db.session.add(new_expense)
    db.session.commit()

    return jsonify(expense_to_dict(new_expense)), 201


@expense_bp.route("", methods=["GET"])
@require_role("admin")
def get_expenses():
    try:
        query = apply_filters(Expense.query)
    except ValueError:
        return jsonify({"error": "from/to must be in YYYY-MM-DD format"}), 400

    expenses = query.order_by(Expense.expense_date.desc(), Expense.id.desc()).all()
    return jsonify([expense_to_dict(e) for e in expenses]), 200


@expense_bp.route("/<int:expense_id>", methods=["PUT"])
@require_role("admin")
def update_expense(expense_id):
    expense = Expense.query.get(expense_id)
    if not expense:
        return jsonify({"error": "Expense not found"}), 404

    data = request.get_json(silent=True) or {}

    if "category" in data:
        if data["category"] not in VALID_CATEGORIES:
            return jsonify({"error": f"category must be one of {VALID_CATEGORIES}"}), 400
        expense.category = data["category"]

    if "amount" in data:
        amount = parse_amount(data["amount"])
        if amount is None:
            return jsonify({"error": "amount must be a positive number"}), 400
        expense.amount = amount

    if "description" in data:
        expense.description = (data["description"] or "").strip() or None

    if data.get("expense_date"):
        try:
            expense.expense_date = parse_date(data["expense_date"])
        except ValueError:
            return jsonify({"error": "expense_date must be in YYYY-MM-DD format"}), 400

    db.session.commit()

    return jsonify({"message": "Expense updated"}), 200


@expense_bp.route("/<int:expense_id>", methods=["DELETE"])
@require_role("admin")
def delete_expense(expense_id):
    expense = Expense.query.get(expense_id)
    if not expense:
        return jsonify({"error": "Expense not found"}), 404

    db.session.delete(expense)
    db.session.commit()

    return jsonify({"message": "Expense deleted"}), 200


@expense_bp.route("/summary", methods=["GET"])
@require_role("admin")
def expense_summary():
    try:
        query = apply_filters(
            db.session.query(Expense.category, func.sum(Expense.amount))
        )
    except ValueError:
        return jsonify({"error": "from/to must be in YYYY-MM-DD format"}), 400

    totals_by_category = query.group_by(Expense.category).all()
    grand_total = sum(float(amount) for _, amount in totals_by_category)

    return jsonify({
        "by_category": {category: float(amount) for category, amount in totals_by_category},
        "grand_total": round(grand_total, 2)
    }), 200