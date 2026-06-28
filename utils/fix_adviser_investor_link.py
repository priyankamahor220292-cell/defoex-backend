"""
Add advisers.investor_id and backfill links from mobile / email / name.
Run: python utils/fix_adviser_investor_link.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv

load_dotenv()
from config.settings import Config
from extensions import db, jwt
from flask import Flask
from sqlalchemy import inspect, text

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)
jwt.init_app(app)

with app.app_context():
    print("Linking adviser ↔ investor records...")
    with db.engine.connect() as conn:
        insp = inspect(db.engine)
        cols = [c['name'] for c in insp.get_columns('advisers')]
        if 'investor_id' not in cols:
            conn.execute(text(
                "ALTER TABLE advisers ADD COLUMN investor_id VARCHAR(30)"
            ))
            conn.commit()
            print("  OK   Added advisers.investor_id column")
        else:
            print("  SKIP investor_id column already exists")

    from app import create_app
    app2 = create_app()
    with app2.app_context():
        from models.adviser import Adviser
        from utils.member_lookup import find_member_for_adviser

        linked = 0
        for adviser in Adviser.query.all():
            if adviser.investor_id:
                continue
            member = find_member_for_adviser(adviser)
            if member:
                adviser.investor_id = member.investor_id
                linked += 1
                print(f"  OK   {adviser.adviser_code} → {member.investor_id} ({adviser.full_name})")

        db.session.commit()
        print(f"\n✅ Linked {linked} adviser(s). Restart Flask: python app.py")
