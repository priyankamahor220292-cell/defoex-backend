from extensions import db
from models.user import User
from models.branch import Branch
from models.branch_wallet import BranchWallet
from models.adviser import Adviser


def seed_database():
    """Seed default superadmin + head office branch + company owner adviser"""

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
        wallet = BranchWallet(
            branch_id=branch.id, current_balance=0,
            cash_wallet=0, low_balance_threshold=10000
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

    # Company owner adviser — uses new unified ID format
    if not Adviser.query.filter_by(adviser_code='DFX-2026-000001').first():
        owner = Adviser(
            adviser_code     = 'DFX-2026-000001',
            full_name        = 'Company Owner',
            mobile           = '9999999999',
            email            = 'owner@defoex.com',
            rank_id          = 20,
            is_company_owner = True,
            is_active        = True,
        )
        db.session.add(owner)

    db.session.commit()
    print("✅ Database seeded: superadmin / Defoex@2024")
    print("   Adviser code: DFX-2026-000001 (Company Owner)")