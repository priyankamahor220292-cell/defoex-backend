"""Lightweight startup migrations for production-safe schema updates."""

from sqlalchemy import inspect, text


def _column_udt_name(conn, table, column):
    """Return PostgreSQL udt_name for a column (e.g. member_approval_status_enum)."""
    row = conn.execute(
        text("""
            SELECT udt_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :table
              AND column_name = :column
        """),
        {'table': table, 'column': column},
    ).fetchone()
    return row[0] if row else None


def ensure_member_approval_status_varchar(db):
    """Convert members.approval_status enum → VARCHAR for SQLAlchemy String column."""
    try:
        with db.engine.connect() as conn:
            udt = _column_udt_name(conn, 'members', 'approval_status')
            if not udt or udt in ('varchar', 'character varying'):
                return
            conn.execute(text(
                "ALTER TABLE members "
                "ALTER COLUMN approval_status TYPE VARCHAR(20) "
                "USING approval_status::text"
            ))
            conn.commit()
            print("  OK   members.approval_status → VARCHAR(20)")
            try:
                conn.execute(text(
                    f"DROP TYPE IF EXISTS {udt} CASCADE"
                ))
                conn.commit()
            except Exception:
                conn.rollback()
    except Exception as e:
        print(f"  NOTE members.approval_status migration: {e}")


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


def ensure_adviser_registration_data_column(db):
    """Add advisers.registration_data for full registration form payload."""
    try:
        insp = inspect(db.engine)
        cols = [c['name'] for c in insp.get_columns('advisers')]
        if 'registration_data' in cols:
            return
        with db.engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE advisers ADD COLUMN registration_data TEXT"
            ))
            conn.commit()
        print("  OK   Added advisers.registration_data column")
    except Exception as e:
        print(f"  NOTE adviser.registration_data migration: {e}")


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
