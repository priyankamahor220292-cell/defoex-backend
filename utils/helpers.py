"""
DefOex Unified Code System
==========================
ONE code per person — format: DFX-YYYY-NNNNNN
Example: DFX-2026-000001

This same code is used as:
  - investor_id  in members table
  - adviser_code in advisers table

When someone is BOTH investor and adviser → same code DFX-2026-000001
IRN is separate: DFX-IRN-YYYY-NNNNN (for investment bonds only)
"""
import random
from datetime import date, datetime
from extensions import db
from sqlalchemy import func, text


def _max_num_across_tables(year):
    """Find the highest sequence number used across members + advisers."""
    pattern = f"DFX-{year}-%"
    nums = []
    try:
        from models.member import Member
        from models.adviser import Adviser
        m = db.session.query(func.max(Member.investor_id)).filter(
            Member.investor_id.like(pattern)).scalar()
        a = db.session.query(func.max(Adviser.adviser_code)).filter(
            Adviser.adviser_code.like(pattern)).scalar()
        for v in [m, a]:
            if v:
                try:
                    nums.append(int(v.split('-')[-1]))
                except Exception:
                    pass
    except Exception:
        pass
    return max(nums) if nums else 0


def generate_code():
    """
    Generate next DFX-YYYY-NNNNNN code.
    Checks BOTH members and advisers tables to avoid collision.
    """
    from models.member import Member
    from models.adviser import Adviser
    year = datetime.now().year
    next_num = _max_num_across_tables(year) + 1
    candidate = f"DFX-{year}-{str(next_num).zfill(6)}"
    while (Member.query.filter_by(investor_id=candidate).first() or
           Adviser.query.filter_by(adviser_code=candidate).first()):
        next_num += 1
        candidate = f"DFX-{year}-{str(next_num).zfill(6)}"
    return candidate


# Both investor and adviser use the same generator
generate_investor_id  = generate_code
generate_adviser_code = generate_code


def generate_irn():
    """DFX-IRN-YYYY-NNNNN — investment bond number only"""
    from models.investment import Investment
    year = datetime.now().year
    pattern = f"DFX-IRN-{year}-%"
    try:
        m = db.session.query(func.max(Investment.irn)).filter(
            Investment.irn.like(pattern)).scalar()
        next_num = int(m.split('-')[-1]) + 1 if m else 1
    except Exception:
        next_num = random.randint(100, 9999)
    candidate = f"DFX-IRN-{year}-{str(next_num).zfill(5)}"
    while Investment.query.filter_by(irn=candidate).first():
        next_num += 1
        candidate = f"DFX-IRN-{year}-{str(next_num).zfill(5)}"
    return candidate


def calculate_age(dob):
    if not dob:
        return None
    today = date.today()
    return today.year - dob.year - (
        (today.month, today.day) < (dob.month, dob.day))


def success_response(data=None, message="Success", status_code=200):
    r = {'success': True, 'message': message}
    if data is not None:
        r['data'] = data
    return r, status_code


def error_response(message="Error", status_code=400, errors=None):
    r = {'success': False, 'message': message}
    if errors:
        r['errors'] = errors
    return r, status_code


def paginate_query(query, page, per_page=20):
    p = query.paginate(page=page, per_page=per_page, error_out=False)
    return {
        'items': p.items, 'total': p.total, 'pages': p.pages,
        'current_page': p.page, 'per_page': p.per_page,
        'has_next': p.has_next, 'has_prev': p.has_prev,
    }