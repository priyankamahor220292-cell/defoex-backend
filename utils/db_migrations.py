"""Lightweight startup migrations for production-safe schema updates."""

from sqlalchemy import inspect, or_, text


def _is_legacy_dfx_code(code):
    """True for old DFX-* adviser/investor IDs (not IRN bonds)."""
    if not code:
        return False
    c = str(code).strip().upper()
    if c.startswith('DFX-IRN'):
        return False
    return c.startswith('DFX-')


def _next_def_code(prefix, year, taken):
    """Next available DEFIN/DEFAD code for the given year."""
    seq = 1
    while True:
        candidate = f'{prefix}{year}{str(seq).zfill(2)}'
        if candidate.upper() not in taken:
            taken.add(candidate.upper())
            return candidate
        seq += 1


def _rename_adviser_code(conn, old_code, new_code):
    """Update adviser_code and all references after legacy → DEFAD migration."""
    old_u, new_u = old_code.upper(), new_code.upper()
    params = {'old': old_code, 'new': new_code, 'old_u': old_u, 'new_u': new_u}
    conn.execute(text(
        'UPDATE advisers SET adviser_code = :new WHERE adviser_code = :old'
    ), params)
    conn.execute(text(
        'UPDATE advisers SET parent_adviser_code = :new WHERE parent_adviser_code = :old'
    ), params)
    conn.execute(text(
        'UPDATE members SET adviser_code = :new WHERE adviser_code = :old'
    ), params)
    conn.execute(text(
        'UPDATE investments SET adviser_code = :new WHERE adviser_code = :old'
    ), params)
    try:
        conn.execute(text(
            'UPDATE commissions SET adviser_code = :new WHERE adviser_code = :old'
        ), params)
    except Exception:
        pass
    conn.execute(text(
        'UPDATE advisers SET login_username = :new_u '
        'WHERE UPPER(login_username) = :old_u'
    ), params)
    conn.execute(text(
        "UPDATE users SET username = :new_u "
        "WHERE UPPER(username) = :old_u AND role IN ('advisor', 'adviser')"
    ), params)


def _rename_investor_id(conn, old_id, new_id):
    """Update investor_id and all references after legacy → DEFIN migration."""
    old_u, new_u = old_id.upper(), new_id.upper()
    params = {'old': old_id, 'new': new_id, 'old_u': old_u, 'new_u': new_u}
    conn.execute(text(
        'UPDATE members SET investor_id = :new WHERE investor_id = :old'
    ), params)
    conn.execute(text(
        'UPDATE advisers SET investor_id = :new WHERE investor_id = :old'
    ), params)
    conn.execute(text(
        'UPDATE investments SET investor_id = :new WHERE investor_id = :old'
    ), params)
    try:
        conn.execute(text(
            'UPDATE installments SET investor_id = :new WHERE investor_id = :old'
        ), params)
    except Exception:
        pass
    conn.execute(text(
        "UPDATE users SET username = :new_u "
        "WHERE UPPER(username) = :old_u AND role = 'member'"
    ), params)


def migrate_legacy_dfx_to_def_ids(db):
    """
    Convert legacy DFX-* adviser/investor IDs to DEFAD*/DEFIN* on startup.
    Safe to run every boot — no-op when nothing legacy remains.
    """
    try:
        from models.adviser import Adviser
        from models.member import Member
        from utils.datetime_utils import now_ist

        year = now_ist().year
        adviser_renames = []
        investor_renames = []

        defad_taken = {
            (a.adviser_code or '').upper()
            for a in Adviser.query.filter(
                Adviser.adviser_code.like(f'DEFAD{year}%')
            ).all()
        }
        legacy_advisers = Adviser.query.filter(
            or_(
                Adviser.adviser_code.like('DFX-%'),
                Adviser.adviser_code.like('DFX-ADV-%'),
                Adviser.adviser_code.like('DFX-INV-%'),
            )
        ).order_by(Adviser.id.asc()).all()

        for adv in legacy_advisers:
            old = adv.adviser_code
            new = _next_def_code('DEFAD', year, defad_taken)
            adviser_renames.append((old, new))

        defin_taken = {
            (m.investor_id or '').upper()
            for m in Member.query.filter(
                Member.investor_id.like(f'DEFIN{year}%')
            ).all()
        }
        legacy_members = Member.query.filter(
            or_(
                Member.investor_id.like('DFX-%'),
                Member.investor_id.like('DFX-INV-%'),
                Member.investor_id.like('DFX-ADV-%'),
            )
        ).order_by(Member.id.asc()).all()

        for member in legacy_members:
            old = member.investor_id
            if _is_legacy_dfx_code(old):
                new = _next_def_code('DEFIN', year, defin_taken)
                investor_renames.append((old, new))

        if not adviser_renames and not investor_renames:
            return

        with db.engine.connect() as conn:
            for old, new in adviser_renames:
                _rename_adviser_code(conn, old, new)
                print(f'  OK   adviser  {old} → {new}')
            for old, new in investor_renames:
                _rename_investor_id(conn, old, new)
                print(f'  OK   investor {old} → {new}')
            conn.commit()

        db.session.expire_all()
        print(
            f'  OK   Migrated {len(adviser_renames)} adviser(s), '
            f'{len(investor_renames)} investor(s) to DEFAD/DEFIN format'
        )
    except Exception as e:
        db.session.rollback()
        print(f'  NOTE legacy DFX→DEF migration: {e}')


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


def ensure_approval_timestamp_columns(db):
    """Add approved_at / approved_by on members and investments if missing."""
    specs = [
        ('members', 'approved_at', 'TIMESTAMP'),
        ('members', 'approved_by', 'INTEGER'),
        ('investments', 'approved_at', 'TIMESTAMP'),
        ('investments', 'approved_by', 'INTEGER'),
    ]
    try:
        insp = inspect(db.engine)
        for table, column, col_type in specs:
            try:
                cols = [c['name'] for c in insp.get_columns(table)]
            except Exception:
                continue
            if column in cols:
                continue
            with db.engine.connect() as conn:
                conn.execute(text(
                    f'ALTER TABLE {table} ADD COLUMN {column} {col_type}'
                ))
                conn.commit()
            print(f'  OK   Added {table}.{column}')
    except Exception as e:
        print(f'  NOTE approval timestamp migration: {e}')
