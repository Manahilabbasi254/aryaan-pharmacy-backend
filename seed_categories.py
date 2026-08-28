from app import create_app, db
from app.models import Category

app = create_app()

categories = ["Medicines", "Medical Supplies", "Supplements", "Cosmetics", "Medical Equipment"]

with app.app_context():
    for name in categories:
        if not Category.query.filter_by(name=name).first():
            db.session.add(Category(name=name))
    db.session.commit()
    print("Categories seeded successfully.")