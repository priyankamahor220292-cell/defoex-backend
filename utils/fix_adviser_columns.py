"""
Add missing adviser columns.
Run: python utils/fix_adviser_columns.py
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
    insp = inspect(db.engine)
    cols = [c['name'] for c in insp.get_columns('advisers')]
    with db.engine.connect() as conn:
        if 'is_blacklisted' not in cols:
            conn.execute(text("ALTER TABLE advisers ADD COLUMN is_blacklisted BOOLEAN DEFAULT FALSE"))
            print("  OK   Added advisers.is_blacklisted")
        else:
            print("  SKIP advisers.is_blacklisted")
        if 'father_name' not in cols:
            conn.execute(text("ALTER TABLE advisers ADD COLUMN father_name VARCHAR(120)"))
            print("  OK   Added advisers.father_name")
        else:
            print("  SKIP advisers.father_name")
        conn.commit()
    print("\n✅ Done! Restart Flask: python app.py")