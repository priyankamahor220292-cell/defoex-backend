"""
Reset DefOex database — PostgreSQL compatible.
Usage:  cd defoex-backend && python reset_db.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import Config
from extensions import db, jwt
from flask import Flask
from sqlalchemy import text

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)
jwt.init_app(app)

with app.app_context():
    # Import all models
    from models.user          import User
    from models.branch        import Branch
    from models.member        import Member
    from models.adviser       import Adviser
    from models.investment    import Investment, Installment
    from models.branch_wallet import BranchWallet, WalletTransaction
    from models.commission    import Commission
    from models.notification  import Notification

    print("Dropping all tables with CASCADE...")
    with db.engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.commit()
    print("Schema cleared.")

    print("Creating fresh tables...")
    db.create_all()
    print("Tables created.")

    # Seed
    branch = Branch(
        branch_code='HQ001', branch_name='Head Office',
        city='Bhopal', state='Madhya Pradesh', pincode='462001',
        manager_name='Admin Manager', manager_email='admin@defoex.com',
        manager_mobile='9876543210',
    )
    db.session.add(branch)
    db.session.flush()

    db.session.add(BranchWallet(
        branch_id=branch.id, current_balance=0,
        cash_wallet=0, low_balance_threshold=10000
    ))

    admin = User(
        username='superadmin', email='admin@defoex.com',
        full_name='Super Administrator', mobile='9876543210',
        role='superadmin', is_active=True,
    )
    admin.set_password('Defoex@2024')
    db.session.add(admin)

    db.session.add(Adviser(
        adviser_code='DFX-2026-000001', full_name='Company Owner',
        mobile='9999999999', email='owner@defoex.com',
        rank_id=20, is_company_owner=True, is_active=True,
    ))

    db.session.commit()

    print("\n✅ Database ready!")
    print("   Login:   superadmin / Defoex@2024")
    print("   Adviser: DFX-2026-000001")
    print("\nFlask is already running on port 5001 ✓")