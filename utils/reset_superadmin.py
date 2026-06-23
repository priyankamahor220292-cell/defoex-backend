"""Reset superadmin password. Run: python utils/reset_superadmin.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()
from config.settings import Config
from extensions import db, jwt
from flask import Flask

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app); jwt.init_app(app)

with app.app_context():
    from models.user import User
    print("\n=== All Users ===")
    users = User.query.all()
    for u in users:
        print(f"  id={u.id} username={u.username} role={u.role} active={u.is_active}")
    
    # Reset superadmin password
    admin = User.query.filter_by(username='superadmin').first()
    if admin:
        admin.set_password('Defoex@2024')
        db.session.commit()
        print(f"\n✅ superadmin password reset to: Defoex@2024")
    else:
        # Create superadmin
        admin = User(
            username='superadmin', email='admin@defoex.com',
            full_name='Super Administrator', mobile='9999999998',
            role='superadmin', is_active=True
        )
        admin.set_password('Defoex@2024')
        db.session.add(admin)
        db.session.commit()
        print(f"\n✅ superadmin created! Password: Defoex@2024")
    
    print("\n   Login: superadmin / Defoex@2024") 