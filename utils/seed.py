from extensions import db
from models.user import User
from models.branch import Branch
from models.branch_wallet import BranchWallet
from models.adviser import Adviser

def seed_database():
    """Seed initial data"""
    # Create default branch
    if not Branch.query.filter_by(branch_code='HQ001').first():
        branch = Branch(
            branch_code='HQ001',
            branch_name='Head Office - Bhopal',
            city='Bhopal',
            state='Madhya Pradesh',
            pincode='462001',
            manager_name='Admin Manager',
            manager_email='admin@defoex.com',
            manager_mobile='9876543210'
        )
        db.session.add(branch)
        db.session.flush()

        # Create wallet for branch
        wallet = BranchWallet(branch_id=branch.id, current_balance=1000000, cash_wallet=0)
        db.session.add(wallet)

    # Create superadmin user
    if not User.query.filter_by(username='superadmin').first():
        admin = User(
            username='superadmin',
            email='admin@defoex.com',
            full_name='Super Administrator',
            role='superadmin',
            mobile='9876543210'
        )
        admin.set_password('Defoex@2024')
        db.session.add(admin)

    # Create company owner adviser (Rank 20 = House 8)
    if not Adviser.query.filter_by(adviser_code='ADV-OWNER-001').first():
        owner = Adviser(
            adviser_code='ADV-OWNER-001',
            full_name='Company Owner',
            mobile='9999999999',
            email='owner@defoex.com',
            rank_id=20,
            is_company_owner=True
        )
        db.session.add(owner)

    db.session.commit()
    print("Database seeded successfully!")

if __name__ == '__main__':
    from app import create_app
    app = create_app()
    with app.app_context():
        seed_database()
