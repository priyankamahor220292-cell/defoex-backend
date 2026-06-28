"""
utils/helpers.py — DefOex IntraTech

ID Formats:
  Investor ID     : DEFIN202601   (DEFIN + year + 2-digit seq)
  Adviser ID      : DEFAD202601   (DEFAD + year + 2-digit seq)
  Investment Plan : INV20260001   (INV   + year + 4-digit seq)
"""

from datetime import date, datetime
from extensions import db


# ── Investor ID: DEFIN202601 ──────────────────────────────────────────────────
def generate_investor_id():
    from models.member import Member
    year   = datetime.now().year
    prefix = f'DEFIN{year}'
    existing = Member.query.filter(Member.investor_id.like(f'{prefix}%')).count()
    seq = existing + 1
    candidate = f'{prefix}{str(seq).zfill(2)}'
    while Member.query.filter_by(investor_id=candidate).first():
        seq += 1
        candidate = f'{prefix}{str(seq).zfill(2)}'
    return candidate


# ── Adviser ID: DEFAD202601 ───────────────────────────────────────────────────
def generate_adviser_code():
    from models.adviser import Adviser
    year   = datetime.now().year
    prefix = f'DEFAD{year}'
    existing = Adviser.query.filter(Adviser.adviser_code.like(f'{prefix}%')).count()
    seq = existing + 1
    candidate = f'{prefix}{str(seq).zfill(2)}'
    while Adviser.query.filter_by(adviser_code=candidate).first():
        seq += 1
        candidate = f'{prefix}{str(seq).zfill(2)}'
    return candidate


# ── Investment Plan No: INV20260001 ──────────────────────────────────────────
def generate_irn():
    from models.investment import Investment
    year   = datetime.now().year
    prefix = f'INV{year}'
    existing = Investment.query.filter(Investment.irn.like(f'{prefix}%')).count()
    seq = existing + 1
    candidate = f'{prefix}{str(seq).zfill(4)}'
    while Investment.query.filter_by(irn=candidate).first():
        seq += 1
        candidate = f'{prefix}{str(seq).zfill(4)}'
    return candidate


# ── Age from DOB ──────────────────────────────────────────────────────────────
def calculate_age(dob):
    if not dob:
        return None
    today = date.today()
    age = today.year - dob.year
    if (today.month, today.day) < (dob.month, dob.day):
        age -= 1
    return age if age >= 0 else None


# ── Response helpers ──────────────────────────────────────────────────────────
def success_response(data=None, message='Success', status_code=200):
    response = {'success': True, 'message': message}
    if data is not None:
        response['data'] = data
    return response, status_code


def error_response(message='Error', status_code=400, errors=None):
    response = {'success': False, 'message': message}
    if errors:
        response['errors'] = errors
    return response, status_code


# ── Pagination ────────────────────────────────────────────────────────────────
def paginate_query(query, page, per_page=20):
    paginated = query.paginate(page=page, per_page=per_page, error_out=False)
    return {
        'items':        paginated.items,
        'total':        paginated.total,
        'pages':        paginated.pages,
        'current_page': paginated.page,
        'per_page':     paginated.per_page,
        'has_next':     paginated.has_next,
        'has_prev':     paginated.has_prev,
    }