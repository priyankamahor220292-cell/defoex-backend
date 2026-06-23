"""
Fix commissions table — convert Enum columns to VARCHAR.
Run: python utils/fix_commission_table.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv; load_dotenv()
from config.settings import Config
from extensions import db, jwt
from flask import Flask
from sqlalchemy import text, inspect

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)
jwt.init_app(app)

with app.app_context():
    print("Fixing commissions table...")
    with db.engine.connect() as conn:

        # Convert status column from Enum to VARCHAR
        try:
            conn.execute(text(
                "ALTER TABLE commissions ALTER COLUMN status TYPE VARCHAR(20)"
            ))
            conn.commit()
            print("  OK   status column → VARCHAR(20)")
        except Exception as e:
            conn.rollback()
            print(f"  NOTE {e}")

        # Add commission_type if missing
        insp = inspect(db.engine)
        cols = [c['name'] for c in insp.get_columns('commissions')]

        if 'commission_type' not in cols:
            conn.execute(text(
                "ALTER TABLE commissions ADD COLUMN commission_type VARCHAR(20) DEFAULT 'Direct'"
            ))
            conn.commit()
            print("  OK   Added commission_type column")
        else:
            print("  SKIP commission_type already exists")

        if 'paid_at' not in cols:
            conn.execute(text(
                "ALTER TABLE commissions ADD COLUMN paid_at TIMESTAMP"
            ))
            conn.commit()
            print("  OK   Added paid_at column")
        else:
            print("  SKIP paid_at already exists")

        # Drop the old enum type if it exists
        try:
            conn.execute(text("DROP TYPE IF EXISTS commission_status_enum CASCADE"))
            conn.commit()
            print("  OK   Dropped commission_status_enum type")
        except Exception:
            pass

    print("\n✅ Done! Restart Flask: python app.py")