"""
Branch-Isolated Schema Manager
================================
Each branch gets its own set of tables:
  GWL001_advisers
  GWL001_members
  GWL001_investments
  GWL001_installments
  GWL001_commissions

When a branch is created → auto-create its tables.
When branch logs in → all queries run against their tables only.
"""
from sqlalchemy import text, inspect
from extensions import db


BRANCH_TABLE_SQL = """
-- Advisers
CREATE TABLE IF NOT EXISTS "{bc}_advisers" (
    id                  SERIAL PRIMARY KEY,
    adviser_code        VARCHAR(30) UNIQUE NOT NULL,
    full_name           VARCHAR(200) NOT NULL,
    father_name         VARCHAR(200),
    mobile              VARCHAR(15),
    email               VARCHAR(120),
    rank_id             INTEGER DEFAULT 1,
    rank_name           VARCHAR(30) DEFAULT 'SR',
    parent_adviser_code VARCHAR(30),
    is_active           BOOLEAN DEFAULT FALSE,
    is_blacklisted      BOOLEAN DEFAULT FALSE,
    is_company_owner    BOOLEAN DEFAULT FALSE,
    username            VARCHAR(50),
    password_hash       VARCHAR(200),
    created_at          TIMESTAMP DEFAULT NOW()
);

-- Members (Investors)
CREATE TABLE IF NOT EXISTS "{bc}_members" (
    id                      SERIAL PRIMARY KEY,
    investor_id             VARCHAR(30) UNIQUE NOT NULL,
    adviser_code            VARCHAR(30),
    full_name               VARCHAR(200) NOT NULL,
    father_spouse_name      VARCHAR(200),
    mobile                  VARCHAR(15),
    phone_office            VARCHAR(15),
    email                   VARCHAR(120),
    date_of_birth           DATE,
    gender                  VARCHAR(10) DEFAULT 'Male',
    marital_status          VARCHAR(20),
    nationality             VARCHAR(50) DEFAULT 'Indian',
    corr_address            TEXT,
    corr_city               VARCHAR(100),
    corr_state              VARCHAR(100),
    corr_pincode            VARCHAR(10),
    perm_address            TEXT,
    perm_city               VARCHAR(100),
    perm_state              VARCHAR(100),
    perm_pincode            VARCHAR(10),
    aadhar_number           VARCHAR(20),
    pan_number              VARCHAR(15),
    voter_id                VARCHAR(20),
    driving_license         VARCHAR(20),
    nominee_name            VARCHAR(200),
    nominee_age             INTEGER,
    nominee_relationship    VARCHAR(50),
    nominee_address         TEXT,
    bank_name               VARCHAR(200),
    account_number          VARCHAR(30),
    ifsc_code               VARCHAR(15),
    upi_id                  VARCHAR(50),
    occupation              VARCHAR(100),
    annual_income           NUMERIC(14,2),
    member_type             VARCHAR(30) DEFAULT 'Investor',
    member_fees             NUMERIC(10,2) DEFAULT 650,
    promoter_fees           NUMERIC(10,2) DEFAULT 0,
    payment_mode            VARCHAR(20) DEFAULT 'Cash',
    date_of_joining         DATE DEFAULT CURRENT_DATE,
    approval_status         VARCHAR(20) DEFAULT 'Pending',
    approved_at             TIMESTAMP,
    login_username          VARCHAR(50),
    login_password          VARCHAR(200),
    is_blacklisted          BOOLEAN DEFAULT FALSE,
    created_at              TIMESTAMP DEFAULT NOW()
);

-- Investments
CREATE TABLE IF NOT EXISTS "{bc}_investments" (
    id                      SERIAL PRIMARY KEY,
    irn                     VARCHAR(30) UNIQUE NOT NULL,
    investor_id             VARCHAR(30) NOT NULL,
    adviser_code            VARCHAR(30),
    plan_type               VARCHAR(10) DEFAULT 'MIS',
    plan_tenure             VARCHAR(5),
    plan_name               VARCHAR(50),
    monthly_amount          NUMERIC(14,2),
    total_installments      INTEGER,
    installments_paid       INTEGER DEFAULT 0,
    total_investment_amount NUMERIC(14,2),
    total_maturity_amount   NUMERIC(14,2),
    roi_percentage          NUMERIC(6,2),
    roi_display             VARCHAR(20),
    payment_mode            VARCHAR(20) DEFAULT 'Cash',
    investment_date         DATE DEFAULT CURRENT_DATE,
    first_due_date          DATE,
    approval_status         VARCHAR(20) DEFAULT 'Pending',
    approved_at             TIMESTAMP,
    created_at              TIMESTAMP DEFAULT NOW()
);

-- Installments
CREATE TABLE IF NOT EXISTS "{bc}_installments" (
    id                  SERIAL PRIMARY KEY,
    investment_id       INTEGER NOT NULL,
    installment_number  INTEGER NOT NULL,
    due_date            DATE,
    amount              NUMERIC(14,2),
    status              VARCHAR(20) DEFAULT 'Pending',
    paid_date           DATE,
    penalty_paid        NUMERIC(10,2) DEFAULT 0,
    created_at          TIMESTAMP DEFAULT NOW()
);

-- Commissions
CREATE TABLE IF NOT EXISTS "{bc}_commissions" (
    id                  SERIAL PRIMARY KEY,
    investment_id       INTEGER,
    adviser_code        VARCHAR(30),
    adviser_rank        VARCHAR(30),
    plan_type           VARCHAR(10),
    plan_tenure         VARCHAR(5),
    investment_amount   NUMERIC(14,2),
    commission_rate     NUMERIC(6,2),
    commission_amount   NUMERIC(14,2),
    status              VARCHAR(20) DEFAULT 'Pending',
    created_at          TIMESTAMP DEFAULT NOW()
);
"""


def create_branch_tables(branch_code):
    """Create all tables for a new branch."""
    bc = branch_code.upper().replace('-', '_')
    sql = BRANCH_TABLE_SQL.replace('{bc}', bc)
    with db.engine.connect() as conn:
        for stmt in sql.split(';'):
            stmt = stmt.strip()
            if stmt:
                try:
                    conn.execute(text(stmt))
                except Exception as e:
                    print(f"  WARN [{bc}] {e}")
        conn.commit()
    print(f"  ✅ Tables created for branch: {bc}")
    return bc


def get_branch_table(branch_code, table_type):
    """
    Get the branch-specific table name.
    table_type: 'advisers' | 'members' | 'investments' | 'installments' | 'commissions'
    """
    bc = branch_code.upper().replace('-', '_')
    return f"{bc}_{table_type}"


def branch_tables_exist(branch_code):
    """Check if branch tables already exist."""
    bc = branch_code.upper().replace('-', '_')
    insp = inspect(db.engine)
    existing = insp.get_table_names()
    return f"{bc}_advisers" in existing


def list_branch_tables(branch_code):
    """List all tables for a branch."""
    bc = branch_code.upper().replace('-', '_')
    insp = inspect(db.engine)
    return [t for t in insp.get_table_names() if t.startswith(f"{bc}_")]


def migrate_existing_data_to_branch(branch_code):
    """
    One-time migration: copy existing data for a branch into its dedicated tables.
    """
    bc = branch_code.upper().replace('-', '_')
    from models.branch import Branch
    branch = Branch.query.filter_by(branch_code=branch_code).first()
    if not branch:
        return

    with db.engine.connect() as conn:
        # Migrate advisers
        try:
            conn.execute(text(f"""
                INSERT INTO "{bc}_advisers"
                (adviser_code, full_name, father_name, mobile, email,
                 rank_id, rank_name, parent_adviser_code,
                 is_active, is_blacklisted, is_company_owner, created_at)
                SELECT adviser_code, full_name, father_name, mobile, email,
                       rank_id, COALESCE(rank_name,'SR'), parent_adviser_code,
                       is_active, COALESCE(is_blacklisted,FALSE), is_company_owner, created_at
                FROM advisers
                WHERE branch_id = {branch.id}
                  AND is_company_owner = FALSE
                ON CONFLICT (adviser_code) DO NOTHING
            """))
        except Exception as e:
            print(f"  WARN migrating advisers: {e}")

        # Migrate members
        try:
            conn.execute(text(f"""
                INSERT INTO "{bc}_members"
                (investor_id, adviser_code, full_name, father_spouse_name, mobile, email,
                 date_of_birth, gender, marital_status,
                 corr_address, corr_city, corr_state, corr_pincode,
                 aadhar_number, pan_number, nominee_name, nominee_age, nominee_relationship,
                 bank_name, account_number, ifsc_code,
                 member_type, member_fees, promoter_fees, payment_mode,
                 date_of_joining, approval_status, created_at)
                SELECT investor_id, adviser_code, full_name, father_spouse_name, mobile, email,
                       date_of_birth, gender, marital_status,
                       corr_address, corr_city, corr_state, corr_pincode,
                       aadhar_number, pan_number, nominee_name, nominee_age, nominee_relationship,
                       bank_name, account_number, ifsc_code,
                       COALESCE(member_type,'Investor'), COALESCE(member_fees,650),
                       COALESCE(promoter_fees,0), COALESCE(payment_mode,'Cash'),
                       date_of_joining, approval_status, created_at
                FROM members
                WHERE branch_id = {branch.id}
                ON CONFLICT (investor_id) DO NOTHING
            """))
        except Exception as e:
            print(f"  WARN migrating members: {e}")

        # Migrate investments
        try:
            conn.execute(text(f"""
                INSERT INTO "{bc}_investments"
                (irn, investor_id, adviser_code, plan_type, plan_tenure, plan_name,
                 monthly_amount, total_installments, installments_paid,
                 total_investment_amount, total_maturity_amount,
                 roi_display, payment_mode, investment_date,
                 approval_status, created_at)
                SELECT irn, investor_id, adviser_code, plan_type, plan_tenure, plan_name,
                       monthly_amount, total_installments, COALESCE(installments_paid,0),
                       total_investment_amount, total_maturity_amount,
                       roi_display, payment_mode, investment_date,
                       approval_status, created_at
                FROM investments
                WHERE branch_id = {branch.id}
                ON CONFLICT (irn) DO NOTHING
            """))
        except Exception as e:
            print(f"  WARN migrating investments: {e}")

        conn.commit()
    print(f"  ✅ Data migrated to branch tables: {bc}")