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

        if 'login_username' not in cols:
            conn.execute(text(
                "ALTER TABLE advisers ADD COLUMN login_username VARCHAR(50)"
            ))
            conn.commit()
            print("  OK   Added advisers.login_username column")
        else:
            print("  SKIP login_username column already exists")

    from app import create_app
    app2 = create_app()
    with app2.app_context():
        from models.adviser import Adviser
        from utils.member_lookup import find_member_for_adviser, find_adviser_for_user
        from models.user import User

        linked = 0
        for adviser in Adviser.query.all():
            if adviser.investor_id:
                continue
            member = find_member_for_adviser(adviser)
            if member:
                adviser.investor_id = member.investor_id
                linked += 1
                print(f"  OK   {adviser.adviser_code} → {member.investor_id} ({adviser.full_name})")

        login_linked = 0
        for user in User.query.filter(User.role.in_(('advisor', 'adviser'))).all():
            if not user.username:
                continue
            adviser = Adviser.query.filter(
                db.func.upper(Adviser.login_username) == user.username.strip().upper()
            ).first()
            if adviser:
                continue
            adviser = find_adviser_for_user(user)
            if adviser and not adviser.login_username:
                adviser.login_username = user.username.strip().upper()
                login_linked += 1
                print(f"  OK   login {user.username} → {adviser.adviser_code}")

        db.session.commit()
        print(f"\n✅ Linked {linked} adviser(s), {login_linked} login username(s). Restart Flask: python app.py")
