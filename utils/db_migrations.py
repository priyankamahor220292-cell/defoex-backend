"""Lightweight startup migrations for production-safe schema updates."""

from sqlalchemy import inspect, text


def ensure_adviser_investor_id_column(db):
    """Add advisers.investor_id if missing (safe to run every startup)."""
    try:
        insp = inspect(db.engine)
        cols = [c['name'] for c in insp.get_columns('advisers')]
        if 'investor_id' in cols:
            return
        with db.engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE advisers ADD COLUMN investor_id VARCHAR(30)"
            ))
            conn.commit()
        print("  OK   Added advisers.investor_id column")
    except Exception as e:
        print(f"  NOTE adviser.investor_id migration: {e}")


def backfill_adviser_investor_links(db):
    """Link adviser records to investor records when codes differ."""
    try:
        from models.adviser import Adviser
        from utils.member_lookup import find_member_for_adviser

        linked = 0
        for adviser in Adviser.query.all():
            if getattr(adviser, 'investor_id', None):
                continue
            member = find_member_for_adviser(adviser)
            if member:
                adviser.investor_id = member.investor_id
                linked += 1
        if linked:
            db.session.commit()
            print(f"  OK   Linked {linked} adviser ↔ investor record(s)")
    except Exception as e:
        db.session.rollback()
        print(f"  NOTE adviser link backfill: {e}")


def ensure_adviser_login_username_column(db):
    """Add advisers.login_username if missing (links DEFAD login to adviser row)."""
    try:
        insp = inspect(db.engine)
        cols = [c['name'] for c in insp.get_columns('advisers')]
        if 'login_username' in cols:
            return
        with db.engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE advisers ADD COLUMN login_username VARCHAR(50)"
            ))
            conn.commit()
        print("  OK   Added advisers.login_username column")
    except Exception as e:
        print(f"  NOTE adviser.login_username migration: {e}")


def backfill_adviser_login_usernames(db):
    """Set login_username on advisers from matching advisor User accounts."""
    try:
        from models.adviser import Adviser
        from models.user import User
        from utils.member_lookup import find_adviser_for_user

        updated = 0
        for user in User.query.filter(User.role.in_(('advisor', 'adviser'))).all():
            if not user.username:
                continue
            adviser = Adviser.query.filter(
                db.func.upper(Adviser.login_username) == user.username.strip().upper()
            ).first()
            if adviser:
                continue
            adviser = find_adviser_for_user(user)
            if adviser and not getattr(adviser, 'login_username', None):
                adviser.login_username = user.username.strip().upper()
                updated += 1

        if updated:
            db.session.commit()
            print(f"  OK   Backfilled login_username on {updated} adviser(s)")
    except Exception as e:
        db.session.rollback()
        print(f"  NOTE adviser login_username backfill: {e}")
