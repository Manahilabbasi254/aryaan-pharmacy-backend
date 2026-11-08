from datetime import datetime, timedelta

from app import db
from app.models import Notification, Product

LOW_STOCK_THRESHOLD = 20
EXPIRY_WARNING_DAYS = 30


def sync_alerts():
    """Create alerts for current stock/expiry problems and close alerts whose
    problem is gone. Returns (created, resolved). Never raises: a failure here
    must not break the order or product change that triggered it."""
    try:
        created = 0
        resolved = 0
        today = datetime.utcnow().date()
        expiry_cutoff = today + timedelta(days=EXPIRY_WARNING_DAYS)

        # 1) Close open alerts whose problem no longer exists
        for n in Notification.query.filter_by(is_read=False).all():
            product = Product.query.get(n.product_id) if n.product_id else None
            if product is None:
                n.is_read = True
                resolved += 1
                continue
            if n.type == "low_stock":
                if product.stock_qty >= LOW_STOCK_THRESHOLD:
                    n.is_read = True
                    resolved += 1
                else:
                    n.message = f"Low stock alert: '{product.name}' has only {product.stock_qty} units left."
            elif n.type == "expiry":
                if product.expiry_date is None or product.expiry_date > expiry_cutoff:
                    n.is_read = True
                    resolved += 1

        # 2) Create alerts for current problems (no duplicates)
        for product in Product.query.filter(Product.stock_qty < LOW_STOCK_THRESHOLD).all():
            exists = Notification.query.filter_by(
                product_id=product.id, type="low_stock", is_read=False
            ).first()
            if not exists:
                db.session.add(Notification(
                    type="low_stock",
                    product_id=product.id,
                    message=f"Low stock alert: '{product.name}' has only {product.stock_qty} units left.",
                ))
                created += 1

        for product in Product.query.filter(
            Product.expiry_date != None, Product.expiry_date <= expiry_cutoff
        ).all():
            exists = Notification.query.filter_by(
                product_id=product.id, type="expiry", is_read=False
            ).first()
            if not exists:
                if product.expiry_date < today:
                    text = f"Expired: '{product.name}' expired on {product.expiry_date.isoformat()}."
                else:
                    text = f"Expiry alert: '{product.name}' expires on {product.expiry_date.isoformat()}."
                db.session.add(Notification(type="expiry", product_id=product.id, message=text))
                created += 1

        db.session.commit()
        return created, resolved
    except Exception:
        db.session.rollback()
        return 0, 0