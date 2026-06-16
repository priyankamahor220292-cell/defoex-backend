"""
Fix wallet_transactions table — adds missing columns.
Run: python utils/fix_wallet_table.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from config.settings import Config
from extensions import db, jwt
from flask import Flask
from sqlalchemy import text, inspect

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)
jwt.init_app(app)

with app.app_context():
    print("Fixing wallet_transactions table...")
    with db.engine.connect() as conn:

        # Drop and recreate wallet_transactions with correct schema
        conn.execute(text("DROP TABLE IF EXISTS wallet_transactions CASCADE"))
        conn.execute(text("""
            CREATE TABLE wallet_transactions (
                id               SERIAL PRIMARY KEY,
                branch_id        INTEGER NOT NULL REFERENCES branches(id),
                transaction_type VARCHAR(20) NOT NULL,
                amount           NUMERIC(18,2) NOT NULL,
                description      VARCHAR(255),
                reference_id     VARCHAR(50),
                balance_after    NUMERIC(18,2),
                cash_wallet_after NUMERIC(18,2),
                created_by       INTEGER REFERENCES users(id),
                created_at       TIMESTAMP DEFAULT NOW()
            )
        """))

        # Also create admin_wallet if missing
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS admin_wallet (
                id                    SERIAL PRIMARY KEY,
                total_limit           NUMERIC(18,2) DEFAULT 10000000000,
                total_distributed     NUMERIC(18,2) DEFAULT 0,
                total_returned        NUMERIC(18,2) DEFAULT 0,
                low_balance_threshold NUMERIC(18,2) DEFAULT 100000000,
                updated_at            TIMESTAMP DEFAULT NOW(),
                created_at            TIMESTAMP DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            INSERT INTO admin_wallet (total_limit, total_distributed, total_returned)
            SELECT 10000000000, 0, 0
            WHERE NOT EXISTS (SELECT 1 FROM admin_wallet)
        """))

        # Add missing columns to branch_wallets
        conn.execute(text("""
            ALTER TABLE branch_wallets
            ADD COLUMN IF NOT EXISTS total_topped_up NUMERIC(18,2) DEFAULT 0
        """))
        conn.execute(text("""
            ALTER TABLE branch_wallets
            ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()
        """))

        # Add roi_percentage to investments if missing
        conn.execute(text("""
            ALTER TABLE investments
            ADD COLUMN IF NOT EXISTS roi_percentage NUMERIC(6,2) DEFAULT NULL
        """))

        conn.commit()

    print("\n=== Tables after fix ===")
    insp = inspect(db.engine)
    for t in ['wallet_transactions', 'admin_wallet', 'branch_wallets']:
        cols = [c['name'] for c in insp.get_columns(t)]
        print(f"  {t}: {', '.join(cols)}")

    print("\n✅ Done! Restart Flask: python app.py")