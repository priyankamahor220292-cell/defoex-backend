"""
Resolve a Member (investor) from any known ID format:
  - DEFIN202601      → investor_id (Member)
  - DEFAD202601      → adviser_code OR adviser login username → linked Member
"""

from datetime import datetime

from extensions import db
from models.member import Member
from models.adviser import Adviser
from models.user import User
from utils.helpers import normalize_mobile, find_member_by_mobile


def _approved_members():
    return Member.query.filter(Member.approval_status == 'Approved')


def _looks_like_mobile(code):
    """True only for 10-digit Indian mobile numbers."""
    digits = normalize_mobile(code)
    return len(digits) == 10 and digits[0] in '6789'


def _pick_best_match(candidates, adviser=None, user=None):
    """Pick one record when multiple name/mobile matches exist."""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    branch_id = None
    if adviser and adviser.branch_id:
        branch_id = adviser.branch_id
    elif user and user.branch_id:
        branch_id = user.branch_id

    if branch_id:
        branch_matches = [c for c in candidates if c.branch_id == branch_id]
        if len(branch_matches) == 1:
            return branch_matches[0]
        if branch_matches:
            candidates = branch_matches

    candidates.sort(
        key=lambda c: c.created_at or datetime.min,
        reverse=True,
    )
    return candidates[0]


def find_adviser_by_code_or_login(code):
    """Find adviser by adviser_code or stored login username."""
    if not code:
        return None
    key = str(code).strip().upper()
    return Adviser.query.filter(
        db.or_(
            db.func.upper(Adviser.adviser_code) == key,
            db.func.upper(Adviser.login_username) == key,
        )
    ).first()


def find_member_for_adviser(adviser):
    """
    Find the approved investor record for an adviser.
    Returns Member or None.
    """
    if not adviser:
        return None

    linked = getattr(adviser, 'investor_id', None)
    if linked:
        member = Member.query.filter(
            db.func.upper(Member.investor_id) == linked.strip().upper(),
            Member.approval_status == 'Approved',
        ).first()
        if member:
            return member

    code = (adviser.adviser_code or '').strip().upper()
    if code:
        member = Member.query.filter(
            db.func.upper(Member.investor_id) == code,
            Member.approval_status == 'Approved',
        ).first()
        if member:
            return member

    if adviser.mobile:
        norm = normalize_mobile(adviser.mobile)
        for member in _approved_members().filter(Member.mobile.isnot(None)).all():
            if normalize_mobile(member.mobile) == norm:
                return member

    if adviser.email:
        email = adviser.email.strip().lower()
        matches = _approved_members().filter(
            db.func.lower(Member.email) == email
        ).all()
        picked = _pick_best_match(matches, adviser=adviser)
        if picked:
            return picked

    if adviser.full_name:
        name = adviser.full_name.strip().lower()
        matches = _approved_members().filter(
            db.func.lower(Member.full_name) == name
        ).all()
        picked = _pick_best_match(matches, adviser=adviser)
        if picked:
            return picked

    return None


def find_adviser_for_user(user):
    """Find the Adviser record linked to a login User (DEFAD username)."""
    if not user:
        return None

    uname = (user.username or '').strip().upper()

    if uname:
        adviser = find_adviser_by_code_or_login(uname)
        if adviser:
            return adviser

    if user.mobile:
        adviser = Adviser.query.filter_by(mobile=user.mobile).first()
        if adviser:
            return adviser
        norm = normalize_mobile(user.mobile)
        for candidate in Adviser.query.filter(Adviser.mobile.isnot(None)).all():
            if normalize_mobile(candidate.mobile) == norm:
                return candidate

    if user.full_name:
        name = user.full_name.strip().lower()
        matches = Adviser.query.filter(
            db.func.lower(Adviser.full_name) == name
        ).all()
        picked = _pick_best_match(matches, user=user)
        if picked:
            return picked

    if user.email:
        email = user.email.strip().lower()
        adviser = Adviser.query.filter(
            db.func.lower(Adviser.email) == email
        ).first()
        if adviser:
            return adviser

        # Login emails are generated as defad202601@defoex.com at approval time
        if uname.startswith('DEFAD') and email == f'{uname.lower()}@defoex.com':
            matches = Adviser.query.filter(
                db.func.lower(Adviser.full_name) == user.full_name.strip().lower()
            ).all() if user.full_name else []
            picked = _pick_best_match(matches, user=user)
            if picked:
                return picked

    return None


def link_adviser_investor(adviser, commit=False):
    """Persist adviser.investor_id when a unique member match exists."""
    if not adviser or getattr(adviser, 'investor_id', None):
        return find_member_for_adviser(adviser) if adviser else None

    member = find_member_for_adviser(adviser)
    if member:
        adviser.investor_id = member.investor_id
        if commit:
            db.session.commit()
    return member


def _adviser_member_error(adviser, code):
    """Build a helpful error when adviser exists but investor profile is missing."""
    hint = ''
    same_name = _approved_members().filter(
        db.func.lower(Member.full_name) == adviser.full_name.strip().lower()
    ).all() if adviser.full_name else []
    if same_name:
        ids = ', '.join(m.investor_id for m in same_name[:3])
        hint = f' Try investor ID: {ids}.'

    pending = None
    if adviser.mobile:
        pending = Member.query.filter(
            Member.mobile == adviser.mobile,
            Member.approval_status == 'Pending',
        ).first()
    if pending:
        return (
            f'"{code}" is adviser {adviser.full_name}. Investor registration '
            f'({pending.investor_id}) is pending approval.{hint}'
        )

    return (
        f'"{code}" is adviser {adviser.full_name}, but no approved investor '
        f'profile is linked yet.{hint} Register them as an investor first.'
    )


def resolve_member_from_code(raw_code):
    """
    Resolve an approved Member from investor ID, adviser code, or DEFAD username.
    Returns (member, None) or (None, error_message).
    """
    if not raw_code or not str(raw_code).strip():
        return None, 'Investor ID / Adviser ID / Login ID is required'

    code = str(raw_code).strip().upper()
    user = None
    adviser = None

    member = Member.query.filter(
        db.func.upper(Member.investor_id) == code
    ).first()
    if not member and _looks_like_mobile(code):
        member = find_member_by_mobile(code)
    if member:
        return _ensure_approved(member, code)

    adviser = find_adviser_by_code_or_login(code)

    if not adviser:
        user = User.query.filter(db.func.upper(User.username) == code).first()
        if user:
            adviser = find_adviser_for_user(user)

    if adviser:
        member = find_member_for_adviser(adviser)
        if member:
            try:
                link_adviser_investor(adviser, commit=True)
            except Exception:
                db.session.rollback()
            return _ensure_approved(member, code)
        return None, _adviser_member_error(adviser, code)

    if user:
        return None, (
            f'Login ID "{code}" belongs to {user.full_name or "a user"}, '
            f'but no adviser or approved investor record is linked. '
            f'Register them as an investor first or use their Investor ID.'
        )

    return None, not_found_message(code)


def _ensure_approved(member, code):
    status = (member.approval_status or '').lower().strip()
    if status != 'approved':
        return None, (
            f'Member "{code}" is not approved yet '
            f'(current status: {member.approval_status or "unknown"}). '
            f'Please approve the member first before creating a plan.'
        )
    return member, None


def find_adviser_identity(raw_code):
    """
    Find an Adviser (and optional login User) from any ID format.
    Does not require an approved Member.
    """
    if not raw_code or not str(raw_code).strip():
        return None, None

    code = str(raw_code).strip().upper()
    adviser = find_adviser_by_code_or_login(code)
    user = None

    if not adviser:
        user = User.query.filter(db.func.upper(User.username) == code).first()
        if user:
            adviser = find_adviser_for_user(user)

    return adviser, user


def _adviser_by_mobile(mobile):
    """Find active adviser matching a mobile number."""
    if not mobile:
        return None
    norm = normalize_mobile(mobile)
    if len(norm) != 10:
        return None
    for candidate in Adviser.query.filter(
        Adviser.is_active == True,
        Adviser.mobile.isnot(None),
    ).all():
        if normalize_mobile(candidate.mobile) == norm:
            return candidate
    return None


def find_promoter_adviser(raw_code):
    """
    Resolve promoter adviser for downline registration.
    Accepts adviser code (DFX/DEFAD), login username, or linked investor ID (DEFIN).
    Returns (adviser, error_message).
    """
    if not raw_code or not str(raw_code).strip():
        return None, 'Please enter a Promoter Adviser ID'

    code = str(raw_code).strip().upper()

    if 'DFX-IRN-' in code:
        return None, (
            'That is an Investment Bond number, not an adviser code. '
            'Use an Adviser ID such as DEFAD202601.'
        )

    adviser, _user = find_adviser_identity(code)
    if not adviser and not code.startswith('DFX-ADV-') and code.startswith('DFX-'):
        adviser, _user = find_adviser_identity('DFX-ADV-' + code.replace('DFX-', '', 1))

    if not adviser:
        adviser = Adviser.query.filter(
            db.func.upper(Adviser.investor_id) == code,
        ).first()

    if not adviser and code.startswith('DEFIN'):
        member = Member.query.filter(
            db.func.upper(Member.investor_id) == code,
        ).first()
        if member:
            adviser = _adviser_by_mobile(member.mobile)
            if not adviser:
                return None, (
                    f'"{code}" is an Investor ID ({member.full_name or "investor"}), '
                    f'not an Adviser ID. Enter the promoter\'s Adviser code '
                    f'(e.g. DEFAD202601).'
                )

    if not adviser:
        hints = defad_id_suggestions()
        msg = f'Promoter Adviser ID "{code}" not found.'
        sample = Adviser.query.filter_by(is_active=True).order_by(Adviser.id.desc()).limit(5).all()
        if sample:
            msg += ' Active adviser codes: ' + ', '.join(a.adviser_code for a in sample) + '.'
        elif hints:
            msg += f' Available DEFAD IDs: {", ".join(hints)}.'
        return None, msg

    if getattr(adviser, 'is_blacklisted', False):
        return None, f'Adviser {adviser.full_name} ({adviser.adviser_code}) is blacklisted.'

    if not adviser.is_active:
        return None, (
            f'Adviser {adviser.full_name} ({adviser.adviser_code}) is pending approval. '
            f'Approve the adviser first before registering downline.'
        )

    return adviser, None


def defad_id_suggestions(limit=5):
    """Recent DEFAD login / adviser IDs in this database (for error hints)."""
    codes = set()
    for row in User.query.filter(User.username.ilike('DEFAD%')).order_by(User.id.desc()).limit(20):
        codes.add(row.username.upper())
    for row in Adviser.query.filter(Adviser.login_username.isnot(None)).order_by(Adviser.id.desc()).limit(20):
        if row.login_username:
            codes.add(row.login_username.upper())
    for row in Adviser.query.filter(Adviser.adviser_code.ilike('DEFAD%')).order_by(Adviser.id.desc()).limit(20):
        codes.add(row.adviser_code.upper())
    return sorted(codes, reverse=True)[:limit]


def not_found_message(code):
    """Helpful message when an ID is missing from the current database."""
    hints = defad_id_suggestions()
    msg = (
        f'No investor or adviser found for "{code}" in this database. '
        f'If this ID was created on the live server, it is not in your local DB — '
        f'create/register the person here first, or use their Investor ID.'
    )
    if hints:
        msg += f' Available DEFAD IDs here: {", ".join(hints)}.'
    approved = _approved_members().order_by(Member.id.desc()).limit(5).all()
    if approved:
        inv_ids = ', '.join(m.investor_id for m in approved)
        msg += f' Approved investors: {inv_ids}.'
    return msg
