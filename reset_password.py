from app import create_app
from extensions import db
from models.user import User

print("Script started")

app = create_app()

with app.app_context():
    user = User.query.filter_by(username="superadmin").first()

    if user:
        user.set_password("admin123")
        db.session.commit()
        print("Password reset successful")
    else:
        print("User not found")