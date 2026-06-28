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
