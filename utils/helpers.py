"""
utils/helpers.py — DefOex IntraTech

ID Formats:
  Investor ID     : DEFIN202601   (DEFIN + year + 2-digit seq)
  Adviser ID      : DEFAD202601   (DEFAD + year + 2-digit seq)
  Investment Plan : 9-MISINV202601  (branch_id-MISINV + year + 2-digit seq)
                     9-SISINV202601  (branch_id-SISINV + year + 2-digit seq)
"""

from datetime import date, datetime
import re
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


# ── Investment Plan ID: 9-MISINV202601 / 9-SISINV202601 ───────────────────────
def generate_investment_plan_id(branch_id, plan_type):
    """
    Generate branch-scoped investment plan ID.
    MIS → {branch_id}-MISINV{year}{seq}  e.g. 9-MISINV202601
    SIS → {branch_id}-SISINV{year}{seq}  e.g. 9-SISINV202601
    """
    from models.investment import Investment

    plan = (plan_type or 'MIS').strip().upper()
    if plan not in ('MIS', 'SIS'):
        plan = 'MIS'

    year = datetime.now().year
    branch = int(branch_id) if branch_id is not None else 0
    prefix = f'{branch}-{plan}INV{year}'

    existing = Investment.query.filter(Investment.irn.like(f'{prefix}%')).count()
    seq = existing + 1
    candidate = f'{prefix}{str(seq).zfill(2)}'
    while Investment.query.filter_by(irn=candidate).first():
        seq += 1
        candidate = f'{prefix}{str(seq).zfill(2)}'
    return candidate


def generate_irn(branch_id=None, plan_type='MIS'):
    """Backward-compatible alias — prefer generate_investment_plan_id."""
    if branch_id is None:
        from models.investment import Investment
        year = datetime.now().year
        prefix = f'INV{year}'
        existing = Investment.query.filter(Investment.irn.like(f'{prefix}%')).count()
        seq = existing + 1
        candidate = f'{prefix}{str(seq).zfill(4)}'
        while Investment.query.filter_by(irn=candidate).first():
            seq += 1
            candidate = f'{prefix}{str(seq).zfill(4)}'
        return candidate
    return generate_investment_plan_id(branch_id, plan_type)


# ── Age from DOB ──────────────────────────────────────────────────────────────
def normalize_mobile(mobile):
    """Return last 10 digits for consistent mobile comparison."""
    if not mobile:
        return ''
    digits = re.sub(r'\D', '', str(mobile))
    return digits[-10:] if len(digits) >= 10 else digits


def find_member_by_mobile(mobile):
    from models.member import Member
    norm = normalize_mobile(mobile)
    if not norm:
        return None
    for member in Member.query.filter(Member.mobile.isnot(None)).all():
        if normalize_mobile(member.mobile) == norm:
            return member
    return None


def find_adviser_by_mobile(mobile):
    from models.adviser import Adviser
    norm = normalize_mobile(mobile)
    if not norm:
        return None
    for adviser in Adviser.query.filter(Adviser.mobile.isnot(None)).all():
        if normalize_mobile(adviser.mobile) == norm:
            return adviser
    return None
def calculate_age(dob):
    if not dob:
        return None
    today = date.today()
    age = today.year - dob.year
    if (today.month, today.day) < (dob.month, dob.day):
        age -= 1
    return age if age >= 0 else None


def branch_manager_display_name(name):
    """Display prefix for branch manager names (not stored in DB)."""
    if not name:
        return name
    text = str(name).strip()
    if text.lower().startswith('hello '):
        return text if text.startswith('Hello ') else f'Hello {text[6:]}'
    return f'Hello {text}'


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