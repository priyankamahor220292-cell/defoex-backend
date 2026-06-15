"""
DefOex — PostgreSQL compatible ID fix
Converts old adviser codes to new DFX-YYYY-NNNNNN format.

Usage:
    cd defoex-backend
    python utils/fix_adviser_codes.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import create_app
from extensions import db
from sqlalchemy import text, inspect

app = create_app()

def run():
    with app.app_context():
        print("=== DefOex Adviser Code Fix (PostgreSQL) ===\n")

        insp = inspect(db.engine)

        # 1. Add roi_percentage column if missing
        inv_cols = [c['name'] for c in insp.get_columns('investments')]
        if 'roi_percentage' not in inv_cols:
            db.session.execute(text(
                "ALTER TABLE investments ADD COLUMN roi_percentage NUMERIC(6,2) DEFAULT NULL"))
            db.session.commit()
            print("  Added investments.roi_percentage")
        else:
            print("  Skip  investments.roi_percentage (exists)")

        # 2. Show current adviser codes
        rows = db.session.execute(
            text("SELECT id, adviser_code, full_name, mobile FROM advisers ORDER BY id")
        ).fetchall()
        print(f"\nCurrent advisers: {len(rows)}")
        for r in rows:
            print(f"  id={r[0]}  code={r[1]}  name={r[2]}")

        # 3. Convert each adviser to new format
        print("\nConverting adviser codes...")
        year    = 2026
        counter = 1

        for r in rows:
            old_code = r[1]
            if old_code.startswith(f"DFX-{year}-"):
                print(f"  SKIP {old_code} (already new format)")
                counter += 1
                continue

            # Find next available slot
            new_code = f"DFX-{year}-{str(counter).zfill(6)}"
            while db.session.execute(
                text("SELECT id FROM advisers WHERE adviser_code = :c"),
                {'c': new_code}
            ).fetchone():
                counter += 1
                new_code = f"DFX-{year}-{str(counter).zfill(6)}"

            # Update advisers
            db.session.execute(
                text("UPDATE advisers SET adviser_code = :new WHERE id = :id"),
                {'new': new_code, 'id': r[0]}
            )
            # Update references
            db.session.execute(
                text("UPDATE members SET adviser_code = :new WHERE adviser_code = :old"),
                {'new': new_code, 'old': old_code}
            )
            try:
                db.session.execute(
                    text("UPDATE investments SET adviser_code = :new WHERE adviser_code = :old"),
                    {'new': new_code, 'old': old_code}
                )
            except Exception:
                pass
            db.session.commit()
            print(f"  OK   {old_code}  →  {new_code}")
            counter += 1

        # 4. Convert old investor IDs
        print("\nConverting investor IDs...")
        members = db.session.execute(
            text("SELECT id, investor_id FROM members WHERE investor_id LIKE 'DFX-INV-%' OR investor_id LIKE 'DFX-ADV-%'")
        ).fetchall()
        print(f"  Found {len(members)} to convert")

        for m_id, old_inv in members:
            parts = old_inv.split('-')
            if len(parts) == 4:
                new_inv = f"DFX-{parts[2]}-{parts[3]}"
            else:
                continue
            exists = db.session.execute(
                text("SELECT id FROM members WHERE investor_id = :i AND id != :mid"),
                {'i': new_inv, 'mid': m_id}
            ).fetchone()
            if exists:
                print(f"  SKIP  {old_inv} → collision")
                continue
            db.session.execute(
                text("UPDATE members SET investor_id = :n WHERE id = :i"),
                {'n': new_inv, 'i': m_id}
            )
            try:
                db.session.execute(
                    text("UPDATE investments  SET investor_id = :n WHERE investor_id = :o"),
                    {'n': new_inv, 'o': old_inv})
                db.session.execute(
                    text("UPDATE installments SET investor_id = :n WHERE investor_id = :o"),
                    {'n': new_inv, 'o': old_inv})
            except Exception:
                pass
            db.session.commit()
            print(f"  OK   investor  {old_inv}  →  {new_inv}")

        # 5. Final state
        print("\n=== Final adviser codes ===")
        final = db.session.execute(
            text("SELECT adviser_code, full_name, mobile FROM advisers ORDER BY adviser_code")
        ).fetchall()
        for r in final:
            print(f"  {r[0]}  —  {r[1]}  ({r[2]})")

        print("\n✅ Done! Restart Flask: python app.py")
        print("Use the codes above in the Promoter ID field when registering investors.")

if __name__ == '__main__':
    run()