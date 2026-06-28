"""
Resolve a Member (investor) from any known ID format:
  - DFX-2026-000005  → investor_id (Member)
  - DFX-2026-000002  → adviser_code (Adviser) → linked Member
  - DEFAD202605      → login username (User) → Adviser → Member
"""

from extensions import db
from models.member import Member
from models.adviser import Adviser
from models.user import User


def _approved_members():
    return Member.query.filter(Member.approval_status == 'Approved')


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
        member = _approved_members().filter_by(mobile=adviser.mobile).first()
        if member:
            return member

    if adviser.email:
        email = adviser.email.strip().lower()
        matches = _approved_members().filter(
            db.func.lower(Member.email) == email
        ).all()
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            if adviser.mobile:
                mobile_match = next(
                    (m for m in matches if m.mobile == adviser.mobile), None
                )
                if mobile_match:
                    return mobile_match
            if adviser.branch_id:
                branch_matches = [
                    m for m in matches if m.branch_id == adviser.branch_id
                ]
                if len(branch_matches) == 1:
                    return branch_matches[0]
            matches.sort(
                key=lambda m: m.created_at or __import__('datetime').datetime.min,
                reverse=True,
            )
            return matches[0]

    if adviser.full_name:
        name = adviser.full_name.strip().lower()
        matches = _approved_members().filter(
            db.func.lower(Member.full_name) == name
        ).all()
        if len(matches) == 1:
            return matches[0]

    return None


def find_adviser_for_user(user):
    """Find the Adviser record linked to a login User (DEFAD username)."""
    if not user:
        return None

    if user.mobile:
        adviser = Adviser.query.filter_by(mobile=user.mobile).first()
        if adviser:
            return adviser

    if user.full_name:
        adviser = Adviser.query.filter(
            db.func.lower(Adviser.full_name) == user.full_name.strip().lower()
        ).first()
        if adviser:
            return adviser

    if user.email:
        email = user.email.strip().lower()
        adviser = Adviser.query.filter(
            db.func.lower(Adviser.email) == email
        ).first()
        if adviser:
            return adviser

    return None


def link_adviser_investor(adviser, commit=False):
    """Persist adviser.investor_id when a unique member match exists."""
    if not adviser or getattr(adviser, 'investor_id', None):
        return None

    member = find_member_for_adviser(adviser)
    if member:
        adviser.investor_id = member.investor_id
        if commit:
            db.session.commit()
    return member


def resolve_member_from_code(raw_code):
    """
    Resolve an approved Member from investor ID, adviser code, or DEFAD username.
    Returns (member, None) or (None, error_message).
    """
    if not raw_code or not str(raw_code).strip():
        return None, 'Investor ID / Adviser ID / Login ID is required'

    code = str(raw_code).strip().upper()

    member = Member.query.filter(
        db.func.upper(Member.investor_id) == code
    ).first()
    if member:
        return _ensure_approved(member, code)

    user = User.query.filter(db.func.upper(User.username) == code).first()
    if user:
        adviser = find_adviser_for_user(user)
        if adviser:
            member = find_member_for_adviser(adviser)
            if member:
                link_adviser_investor(adviser)
                return _ensure_approved(member, code)
        return None, (
            f'Login ID "{code}" belongs to {user.full_name or "a user"}, '
            f'but no approved investor record is linked. '
            f'Register them as an investor first or use their Investor ID.'
        )

    adviser = Adviser.query.filter(
        db.func.upper(Adviser.adviser_code) == code
    ).first()
    if adviser:
        member = find_member_for_adviser(adviser)
        if member:
            link_adviser_investor(adviser)
            return _ensure_approved(member, code)
        return None, (
            f'"{code}" is adviser {adviser.full_name}, but no approved investor '
            f'profile is linked yet. Register them as an investor first.'
        )

    return None, f'No investor or adviser found for "{code}"'


def _ensure_approved(member, code):
    status = (member.approval_status or '').lower().strip()
    if status != 'approved':
        return None, (
            f'Member "{code}" is not approved yet '
            f'(current status: {member.approval_status or "unknown"}). '
            f'Please approve the member first before creating a plan.'
        )
    return member, None
