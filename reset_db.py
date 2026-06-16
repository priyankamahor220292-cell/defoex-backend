"""
DefOex DB Reset — drops everything and rebuilds fresh.
Usage:  cd defoex-backend && python reset_db.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

from config.settings import Config
from extensions import db, jwt
from flask import Flask
from sqlalchemy import text

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)
jwt.init_app(app)

with app.app_context():
    # Import ALL models
    from models.user          import User
    from models.branch        import Branch
    from models.member        import Member
    from models.adviser       import Adviser
    from models.investment    import Investment, Installment
    from models.branch_wallet import BranchWallet, WalletTransaction, AdminWallet, ADMIN_WALLET_LIMIT
    from models.commission    import Commission
    from models.notification  import Notification

    print(f"DB: {app.config['SQLALCHEMY_DATABASE_URI'][:60]}...")

    # ── Drop everything with CASCADE ──────────────────────────────
    print("Dropping schema...")
    try:
        with db.engine.connect() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
            conn.commit()
        print("  Schema cleared.")
    except Exception as e:
        print(f"  Drop note: {e}")

    # ── Recreate all tables ───────────────────────────────────────
    print("Creating tables...")
    db.create_all()

    # ── Seed ─────────────────────────────────────────────────────
    # Head Office branch
    branch = Branch(
        branch_code='HQ001', branch_name='Head Office',
        city='Bhopal', state='Madhya Pradesh', pincode='462001',
        manager_name='Admin Manager',
        manager_email='admin@defoex.com',
        manager_mobile='9876543210',
    )
    db.session.add(branch)
    db.session.flush()

    db.session.add(BranchWallet(
        branch_id=branch.id, current_balance=0,
        cash_wallet=0, low_balance_threshold=10000
    ))

    # Superadmin
    admin = User(
        username='superadmin', email='admin@defoex.com',
        full_name='Super Administrator', mobile='9876543210',
        role='superadmin', is_active=True,
    )
    admin.set_password('Defoex@2024')
    db.session.add(admin)

    # Company Owner Adviser
    db.session.add(Adviser(
        adviser_code='DFX-2026-000001',
        full_name='Company Owner',
        mobile='9999999999',
        email='owner@defoex.com',
        rank_id=20,
        is_company_owner=True,
        is_active=True,
    ))

    # Admin wallet — ₹100 Crore
    db.session.add(AdminWallet(
        total_limit=ADMIN_WALLET_LIMIT,
        total_distributed=0,
        total_returned=0,
    ))

    db.session.commit()

    # ── Verify ───────────────────────────────────────────────────
    with db.engine.connect() as conn:
        tables = conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        )).fetchall()

    print(f"\n✅ {len(tables)} tables created:")
    for t in tables:
        print(f"  ✓ {t[0]}")

    print("\n  Login:    superadmin / Defoex@2024")
    print("  Adviser:  DFX-2026-000001")
    print(f"  Wallet:   ₹{ADMIN_WALLET_LIMIT:,} (₹100 Crore)")
    print("\nNow run:  python app.py")