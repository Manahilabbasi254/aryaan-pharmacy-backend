from flask import Blueprint, request, jsonify
from app import db
from app.models import Expense
from app.utils import require_role
from flask_jwt_extended import get_jwt_identity
from datetime import datetime
from sqlalchemy import func

expense_bp = Blueprint("expenses", __name__, url_prefix="/api/v1/expenses")

VALID_CATEGORIES = ["rent", "utilities", "salary", "other"]


@expense_bp.route("", methods=["POST"])
@require_role("admin")
def create_expense():
    user_id = get_jwt_identity()
    data = request.get_json()

    category = data.get("category")
    amount = data.get("amount")
    description = data.get("description")
    expense_date = data.get("expense_date")

    if category not in VALID_CATEGORIES:
        return jsonify({"error": f"category must be one of {VALID_CATEGORIES}"}), 400
    if amount is None or amount <= 0:
        return jsonify({"error": "amount must be a positive number"}), 400

    new_expense = Expense(
        category=category,
        amount=amount,
        description=description,
        expense_date=datetime.strptime(expense_date, "%Y-%m-%d").date() if expense_date else datetime.utcnow().date(),
        recorded_by=user_id
    )
    db.session.add(new_expense)
    db.session.commit()

    return jsonify({
        "id": new_expense.id,
        "category": new_expense.category,
        "amount": float(new_expense.amount),
        "expense_date": new_expense.expense_date.isoformat()
    }), 201


@expense_bp.route("", methods=["GET"])
@require_role("admin")
def get_expenses():
    category = request.args.get("category")

    query = Expense.query
    if category:
        query = query.filter_by(category=category)

    expenses = query.order_by(Expense.expense_date.desc()).all()

    return jsonify([{
        "id": e.id,
        "category": e.category,
        "amount": float(e.amount),
        "description": e.description,
        "expense_date": e.expense_date.isoformat()
    } for e in expenses]), 200


@expense_bp.route("/<int:expense_id>", methods=["PUT"])
@require_role("admin")
def update_expense(expense_id):
    expense = Expense.query.get(expense_id)
    if not expense:
        return jsonify({"error": "Expense not found"}), 404

    data = request.get_json()
    if "category" in data:
        if data["category"] not in VALID_CATEGORIES:
            return jsonify({"error": f"category must be one of {VALID_CATEGORIES}"}), 400
        expense.category = data["category"]

    expense.amount = data.get("amount", expense.amount)
    expense.description = data.get("description", expense.description)

    if "expense_date" in data and data["expense_date"]:
        expense.expense_date = datetime.strptime(data["expense_date"], "%Y-%m-%d").date()

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
    totals_by_category = (
        db.session.query(Expense.category, func.sum(Expense.amount))
        .group_by(Expense.category)
        .all()
    )

    grand_total = sum(float(amount) for _, amount in totals_by_category)

    return jsonify({
        "by_category": {category: float(amount) for category, amount in totals_by_category},
        "grand_total": round(grand_total, 2)
    }), 200