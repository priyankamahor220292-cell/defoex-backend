"""
Commission Processor
=====================
Called when an investment plan is approved.
Uses raw SQL to avoid PostgreSQL Enum type issues.
"""
from utils.commission_engine import calculate_all_commissions
from models.adviser import Adviser
from extensions import db
from sqlalchemy import text
import traceback


def build_adviser_chain(adviser_code, max_depth=20):
    chain   = []
    seen    = set()
    current = Adviser.query.filter_by(adviser_code=adviser_code, is_active=True).first()
    while current and len(chain) < max_depth:
        if current.adviser_code in seen:
            break
        seen.add(current.adviser_code)
        chain.append({
            'adviser_code':     current.adviser_code,
            'full_name':        current.full_name,
            'rank_id':          current.rank_id or 1,
            'is_company_owner': current.is_company_owner,
        })
        if current.is_company_owner or not current.parent_adviser_code:
            break
        parent  = Adviser.query.filter_by(
            adviser_code=current.parent_adviser_code, is_active=True
        ).first()
        current = parent
    return chain


def process_investment_commissions(investment):
    try:
        adviser_code = getattr(investment, 'adviser_code', None)
        if not adviser_code:
            return []

        chain = build_adviser_chain(adviser_code)
        if not chain:
            return []

        inv_dict = {
            'plan_type':               getattr(investment, 'plan_type', 'MIS'),
            'plan_tenure':             getattr(investment, 'plan_tenure', '3Y'),
            'monthly_amount':          float(getattr(investment, 'monthly_amount', 0) or 0),
            'total_investment_amount': float(getattr(investment, 'total_investment_amount', 0) or 0),
        }

        records = calculate_all_commissions(inv_dict, chain)
        saved   = []

        for r in records:
            if r['commission_amount'] <= 0:
                continue
            inv_id = getattr(investment, 'id', None)
            try:
                # Use raw SQL — avoids commission_status_enum entirely
                db.session.execute(text("""
                    INSERT INTO commissions
                    (investment_id, adviser_code, adviser_rank,
                     plan_type, plan_tenure, investment_amount,
                     commission_rate, commission_amount,
                     commission_type, status, created_at)
                    VALUES
                    (:iid, :acode, :arank,
                     :ptype, :ptenure, :iamt,
                     :crate, :camt,
                     :ctype, 'Pending', NOW())
                """), {
                    'iid':    inv_id,
                    'acode':  r['adviser_code'],
                    'arank':  r['adviser_rank'],
                    'ptype':  r['plan_type'],
                    'ptenure':r['plan_tenure'],
                    'iamt':   r['base_amount'],
                    'crate':  r['commission_rate'],
                    'camt':   r['commission_amount'],
                    'ctype':  r['commission_type'],
                })
                saved.append(r)
                print(f"  Commission: {r['adviser_code']} ({r['adviser_rank']}) "
                      f"— {r['commission_type']} {r['commission_rate']}% "
                      f"= ₹{r['commission_amount']:,.2f}")
            except Exception as row_err:
                print(f"  Commission row error: {row_err}")
                # Try to fix the column type on the fly
                try:
                    with db.engine.connect() as fix_conn:
                        fix_conn.execute(text(
                            "ALTER TABLE commissions ALTER COLUMN status TYPE VARCHAR(20)"
                        ))
                        fix_conn.execute(text(
                            "DROP TYPE IF EXISTS commission_status_enum CASCADE"
                        ))
                        fix_conn.commit()
                    print("  Auto-fixed commission_status_enum → VARCHAR")
                    # Retry
                    db.session.execute(text("""
                        INSERT INTO commissions
                        (investment_id, adviser_code, adviser_rank,
                         plan_type, plan_tenure, investment_amount,
                         commission_rate, commission_amount,
                         commission_type, status, created_at)
                        VALUES
                        (:iid, :acode, :arank,
                         :ptype, :ptenure, :iamt,
                         :crate, :camt,
                         :ctype, 'Pending', NOW())
                    """), {
                        'iid':    inv_id,
                        'acode':  r['adviser_code'],
                        'arank':  r['adviser_rank'],
                        'ptype':  r['plan_type'],
                        'ptenure':r['plan_tenure'],
                        'iamt':   r['base_amount'],
                        'crate':  r['commission_rate'],
                        'camt':   r['commission_amount'],
                        'ctype':  r['commission_type'],
                    })
                    saved.append(r)
                    print(f"  Commission retry OK: {r['adviser_code']}")
                except Exception as retry_err:
                    print(f"  Commission retry failed: {retry_err}")

        return saved

    except Exception as e:
        print(f"  Commission ERROR: {e}")
        print(traceback.format_exc())
        return []