"""
Run once to fix member_type column — converts Enum to VARCHAR and updates old values.
Usage: python utils/fix_member_type.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
    with db.engine.connect() as conn:
        # Change column type from enum to varchar
        try:
            conn.execute(text(
                "ALTER TABLE members ALTER COLUMN member_type TYPE VARCHAR(30)"
            ))
            conn.commit()
            print("  OK   Changed member_type to VARCHAR(30)")
        except Exception as e:
            conn.rollback()
            print(f"  SKIP member_type type change: {e}")

        # Update old 'Customer' values to 'Investor'
        result = conn.execute(text(
            "UPDATE members SET member_type = 'Investor' WHERE member_type = 'Customer' OR member_type IS NULL"
        ))
        conn.commit()
        print(f"  OK   Updated {result.rowcount} members from 'Customer' → 'Investor'")

        # Show current distribution
        rows = conn.execute(text(
            "SELECT member_type, COUNT(*) FROM members GROUP BY member_type"
        )).fetchall()
        print("\n  member_type distribution:")
        for r in rows:
            print(f"    {r[0]}: {r[1]}")

    print("\n✅ Done! Restart Flask: python app.py")