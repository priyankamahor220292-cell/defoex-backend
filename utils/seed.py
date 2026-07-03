from extensions import db
from models.user import User
from models.branch import Branch
from models.branch_wallet import BranchWallet, AdminWallet, ADMIN_WALLET_LIMIT
from models.adviser import Adviser
from utils.helpers import generate_adviser_code

ADMIN_LIMIT = 1_00_00_00_000  # ₹100 Crore — superadmin panel limit


def seed_database():
    """Seed default superadmin + head office branch + company owner adviser"""

    branch_id = None

    # Head Office branch
    if not Branch.query.filter_by(branch_code='HQ001').first():
        branch = Branch(
            branch_code    = 'HQ001',
            branch_name    = 'Head Office',
            city           = 'Bhopal',
            state          = 'Madhya Pradesh',
            pincode        = '462001',
            manager_name   = 'Admin Manager',
            manager_email  = 'admin@defoex.com',
            manager_mobile = '9876543210',
        )
        db.session.add(branch)
        db.session.flush()
        branch_id = branch.id

        # Admin wallet — 100 Crore limit
        wallet = BranchWallet(
            branch_id         = branch.id,
            current_balance   = ADMIN_LIMIT,
            cash_wallet       = 0,
            low_balance_threshold = 10_00_000,  # Alert at ₹10 Lakh
        )
        db.session.add(wallet)

    # Superadmin user
    if not User.query.filter_by(username='superadmin').first():
        admin = User(
            username  = 'superadmin',
            email     = 'admin@defoex.com',
            full_name = 'Super Administrator',
            mobile    = '9876543210',
            role      = 'superadmin',
            is_active = True,
        )
        admin.set_password('Defoex@2024')
        db.session.add(admin)

    # Company owner adviser — DEFAD{year}{seq}, e.g. DEFAD202601
    owner = Adviser.query.filter_by(is_company_owner=True).first()
    if not owner:
        owner_code = generate_adviser_code()
        owner = Adviser(
            adviser_code     = owner_code,
            full_name        = 'Company Owner',
            mobile           = '9999999999',
            email            = 'owner@defoex.com',
            rank_id          = 20,
            is_company_owner = True,
            is_active        = True,
        )
        db.session.add(owner)
    elif owner.adviser_code and str(owner.adviser_code).upper().startswith('DFX-'):
        from utils.db_migrations import migrate_legacy_dfx_to_def_ids
        db.session.commit()
        migrate_legacy_dfx_to_def_ids(db)
        owner = Adviser.query.filter_by(is_company_owner=True).first()

    db.session.commit()
    owner = Adviser.query.filter_by(is_company_owner=True).first()
    owner_code = owner.adviser_code if owner else 'DEFAD202601'
    print("✅ Seeded: superadmin / Defoex@2024")
    print(f"   Admin wallet limit: ₹{ADMIN_LIMIT:,} (100 Crore)")
    print(f"   Adviser: {owner_code} (Company Owner)")