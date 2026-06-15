"""
DefOex ID Migration
===================
Converts all old-format IDs to the new unified format.

OLD formats:          NEW format:
DFX-INV-2026-000001  →  DFX-2026-000001   (investor)
DFX-ADV-2026-000001  →  DFX-2026-000001   (adviser — same code if same person)

Run once:
    cd defoex-backend
    python utils/migrate_ids.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import create_app
from extensions import db
from sqlalchemy import text

app = create_app()

def widen_columns():
    cols = [
        'ALTER TABLE members       MODIFY COLUMN investor_id   VARCHAR(30) NOT NULL',
        'ALTER TABLE advisers      MODIFY COLUMN adviser_code  VARCHAR(30) NOT NULL',
        'ALTER TABLE investments   MODIFY COLUMN irn           VARCHAR(30) NOT NULL',
        'ALTER TABLE investments   MODIFY COLUMN investor_id   VARCHAR(30)',
        'ALTER TABLE investments   MODIFY COLUMN adviser_code  VARCHAR(30)',
        'ALTER TABLE installments  MODIFY COLUMN investor_id   VARCHAR(30)',
    ]
    for sql in cols:
        try:
            db.session.execute(text(sql))
            db.session.commit()
            print(f'  OK   {sql[15:70]}')
        except Exception as e:
            db.session.rollback()
            print(f'  skip {sql[15:70]}')

    # Add roi_percentage column if missing
    try:
        db.session.execute(text(
            'ALTER TABLE investments ADD COLUMN roi_percentage DECIMAL(6,2) DEFAULT NULL'))
        db.session.commit()
        print('  OK   investments.roi_percentage added')
    except Exception:
        db.session.rollback()
        print('  skip investments.roi_percentage already exists')


def convert_ids():
    """Convert DFX-INV-/DFX-ADV- prefixes to plain DFX- format."""

    # ── Investors ──────────────────────────────────────────────────
    rows = db.session.execute(
        text("SELECT id, investor_id FROM members WHERE investor_id LIKE 'DFX-INV-%' OR investor_id LIKE 'DFX-ADV-%'")
    ).fetchall()
    print(f'\nInvestors to convert: {len(rows)}')

    for row_id, old_id in rows:
        # New format: remove -INV- or -ADV- part
        parts = old_id.split('-')   # ['DFX','INV','2026','000001']  or ['DFX','2026','000001']
        if len(parts) == 4:         # DFX-INV-2026-000001 or DFX-ADV-2026-000001
            new_id = f"DFX-{parts[2]}-{parts[3]}"
        else:
            continue                # already in correct format

        # Check collision
        exists = db.session.execute(
            text("SELECT id FROM members WHERE investor_id = :id AND id != :rid"),
            {'id': new_id, 'rid': row_id}
        ).fetchone()
        if exists:
            print(f'  COLLISION {old_id} → {new_id} — skipping')
            continue

        # Update all tables
        db.session.execute(text("UPDATE members SET investor_id = :n WHERE id = :i"),
                           {'n': new_id, 'i': row_id})
        db.session.execute(text("UPDATE investments SET investor_id = :n WHERE investor_id = :o"),
                           {'n': new_id, 'o': old_id})
        db.session.execute(text("UPDATE installments SET investor_id = :n WHERE investor_id = :o"),
                           {'n': new_id, 'o': old_id})
        db.session.commit()
        print(f'  OK   investor  {old_id}  →  {new_id}')

    # ── Advisers ───────────────────────────────────────────────────
    rows = db.session.execute(
        text("SELECT id, adviser_code FROM advisers WHERE adviser_code LIKE 'DFX-ADV-%' OR adviser_code LIKE 'DFX-INV-%'")
    ).fetchall()
    print(f'\nAdvisers to convert: {len(rows)}')

    for row_id, old_code in rows:
        parts = old_code.split('-')
        if len(parts) == 4:
            new_code = f"DFX-{parts[2]}-{parts[3]}"
        else:
            continue

        exists = db.session.execute(
            text("SELECT id FROM advisers WHERE adviser_code = :c AND id != :rid"),
            {'c': new_code, 'rid': row_id}
        ).fetchone()
        if exists:
            print(f'  COLLISION {old_code} → {new_code} — skipping')
            continue

        db.session.execute(text("UPDATE advisers SET adviser_code = :n WHERE id = :i"),
                           {'n': new_code, 'i': row_id})
        # Update references in members (adviser_code field)
        db.session.execute(text("UPDATE members SET adviser_code = :n WHERE adviser_code = :o"),
                           {'n': new_code, 'o': old_code})
        # Update investments
        db.session.execute(text("UPDATE investments SET adviser_code = :n WHERE adviser_code = :o"),
                           {'n': new_code, 'o': old_code})
        db.session.commit()
        print(f'  OK   adviser   {old_code}  →  {new_code}')


def check_shared_ids():
    """Report which people have the same code as investor and adviser."""
    rows = db.session.execute(text("""
        SELECT m.investor_id, m.full_name, a.adviser_code, a.full_name
        FROM members m
        JOIN advisers a ON a.adviser_code = m.investor_id
    """)).fetchall()
    print(f'\nPeople with shared investor+adviser code: {len(rows)}')
    for r in rows:
        print(f'  ✓  {r[0]}  Investor: {r[1]}  /  Adviser: {r[3]}')


if __name__ == '__main__':
    with app.app_context():
        print('=== DefOex ID Migration ===\n')
        print('Step 1: Widening columns...')
        widen_columns()
        print('\nStep 2: Converting IDs...')
        convert_ids()
        print('\nStep 3: Checking shared codes...')
        check_shared_ids()
        print('\n✅ Done. Restart Flask: python app.py\n')
        print('ID format after migration:')
        print('  Investor ID  : DFX-2026-000001')
        print('  Adviser Code : DFX-2026-000001  ← SAME if same person')
        print('  IRN          : DFX-IRN-2026-00001  ← always different')