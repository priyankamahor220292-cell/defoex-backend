"""
utils/helpers.py — Defoex InfraTech

ID Formats:
  Investor ID     : DEFIN202601   (DEFIN + year + 2-digit seq)
  Adviser ID      : DEFAD202601   (DEFAD + year + 2-digit seq)
  Investment Plan : 9-MISINV202601  (branch_id-MISINV + year + 2-digit seq)
                     9-SISINV202601  (branch_id-SISINV + year + 2-digit seq)
"""

from datetime import date
import re
from extensions import db
from utils.datetime_utils import now_ist, today_ist


# ── Investor ID: DEFIN202601 ──────────────────────────────────────────────────
def generate_investor_id():
    from models.member import Member
    year   = now_ist().year
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
    year   = now_ist().year
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

    year = now_ist().year
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
        year = now_ist().year
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


def find_member_by_mobile(mobile, exclude_member_id=None):
    from models.member import Member
    norm = normalize_mobile(mobile)
    if not norm:
        return None
    for member in Member.query.filter(Member.mobile.isnot(None)).all():
        if exclude_member_id and member.id == exclude_member_id:
            continue
        if normalize_mobile(member.mobile) == norm:
            return member
    return None


def find_adviser_by_mobile(mobile, exclude_adviser_id=None):
    from models.adviser import Adviser
    norm = normalize_mobile(mobile)
    if not norm:
        return None
    for adviser in Adviser.query.filter(Adviser.mobile.isnot(None)).all():
        if exclude_adviser_id and adviser.id == exclude_adviser_id:
            continue
        if normalize_mobile(adviser.mobile) == norm:
            return adviser
    return None


def find_branch_manager_user_by_mobile(mobile, exclude_user_id=None):
    """Find a branch manager portal user by normalized mobile."""
    from models.user import User
    norm = normalize_mobile(mobile)
    if not norm:
        return None
    q = User.query.filter(User.role == 'branchmanager', User.mobile.isnot(None))
    if exclude_user_id:
        q = q.filter(User.id != exclude_user_id)
    for user in q.all():
        if normalize_mobile(user.mobile) == norm:
            return user
    return None


def find_branch_by_manager_mobile(mobile, exclude_branch_id=None):
    """Find a branch whose manager_mobile matches (normalized)."""
    from models.branch import Branch
    norm = normalize_mobile(mobile)
    if not norm:
        return None
    q = Branch.query.filter(Branch.manager_mobile.isnot(None))
    if exclude_branch_id:
        q = q.filter(Branch.id != exclude_branch_id)
    for branch in q.all():
        if normalize_mobile(branch.manager_mobile) == norm:
            return branch
    return None


def _branch_manager_mobile_conflict(mobile, exclude_user_id=None, exclude_branch_id=None):
    """Shared branch-manager uniqueness checks. Returns error message or None."""
    existing_user = find_branch_manager_user_by_mobile(mobile, exclude_user_id=exclude_user_id)
    if existing_user:
        label = existing_user.full_name or existing_user.username or f'ID {existing_user.id}'
        return f'Mobile number already registered to branch manager {label}'

    existing_branch = find_branch_by_manager_mobile(mobile, exclude_branch_id=exclude_branch_id)
    if existing_branch:
        return (
            f'Mobile number already used for branch '
            f'{existing_branch.branch_name} ({existing_branch.branch_code})'
        )
    return None


def validate_investor_mobile(mobile, exclude_member_id=None):
    """
    Investor mobiles must be unique among investors, advisers, and branch managers.
    Returns None if valid, else an error message.
    """
    norm = normalize_mobile(mobile)
    if not norm:
        return 'Mobile number is required'
    if len(norm) != 10:
        return 'Valid 10-digit mobile number is required'

    existing = find_member_by_mobile(mobile, exclude_member_id=exclude_member_id)
    if existing:
        return f'Mobile number already registered as investor {existing.investor_id}'

    adviser = find_adviser_by_mobile(mobile)
    if adviser:
        return f'Mobile number already registered as adviser {adviser.adviser_code}'

    return _branch_manager_mobile_conflict(mobile)


def validate_adviser_mobile(
    mobile,
    exclude_adviser_id=None,
    exclude_member_id=None,
    allow_approved_investor=False,
    exclude_user_id=None,
    exclude_branch_id=None,
):
    """
    Adviser mobiles must be unique among advisers and branch managers.
    Approved investors may reuse their mobile when promoted to adviser.
    Returns None if valid, else an error message.
    """
    norm = normalize_mobile(mobile)
    if not norm:
        return 'Mobile number is required'
    if len(norm) != 10:
        return 'Valid 10-digit mobile number is required'

    existing = find_adviser_by_mobile(mobile, exclude_adviser_id=exclude_adviser_id)
    if existing:
        return f'Mobile number already registered as adviser {existing.adviser_code}'

    member = find_member_by_mobile(mobile, exclude_member_id=exclude_member_id)
    if member:
        if allow_approved_investor and member.approval_status == 'Approved':
            pass
        elif member.approval_status == 'Pending':
            return f'Mobile number already registered as pending investor {member.investor_id}'
        else:
            return f'Mobile number already registered as investor {member.investor_id}'

    return _branch_manager_mobile_conflict(
        mobile,
        exclude_user_id=exclude_user_id,
        exclude_branch_id=exclude_branch_id,
    )


def validate_branch_manager_mobile(mobile, exclude_user_id=None, exclude_branch_id=None):
    """
    Branch manager mobiles must be unique across branch manager users
    and branch.manager_mobile fields.
    Returns None if valid, else an error message.
    """
    norm = normalize_mobile(mobile)
    if not norm:
        return 'Mobile number is required for branch managers'
    if len(norm) != 10:
        return 'Valid 10-digit mobile number is required'

    existing = find_adviser_by_mobile(mobile)
    if existing:
        return f'Mobile number already registered as adviser {existing.adviser_code}'

    existing = find_member_by_mobile(mobile)
    if existing:
        return f'Mobile number already registered as investor {existing.investor_id}'

    return _branch_manager_mobile_conflict(
        mobile,
        exclude_user_id=exclude_user_id,
        exclude_branch_id=exclude_branch_id,
    )


def calculate_age(dob):
    if not dob:
        return None
    today = today_ist()
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