"""Approve investor registration and generate DEFIN login credentials."""

import secrets

from extensions import db
from utils.datetime_utils import now_ist
from models.user import User
from models.adviser import Adviser
from utils.member_lookup import find_adviser_by_code_or_login
from utils.branch_wallet_ops import deduct_branch_wallet
from sqlalchemy.exc import IntegrityError


def _investor_username(member):
    """Login username matches investor ID (e.g. DEFIN202634)."""
    return (member.investor_id or '').strip().upper()


def _resolve_member_branch(member):
    """Ensure member.branch_id is set from adviser when missing."""
    if member.branch_id:
        return member.branch_id
    if not member.adviser_code:
        return None
    adv = find_adviser_by_code_or_login(member.adviser_code)
    if adv and adv.branch_id:
        member.branch_id = adv.branch_id
        return adv.branch_id
    return None


def _unique_member_email(username, preferred=None):
    """Pick a unique email for the new member login user."""
    candidates = []
    if preferred and str(preferred).strip():
        candidates.append(str(preferred).strip().lower())
    candidates.append(f'{username.lower()}@defoex.com')
    candidates.append(f'{username.lower()}.member@defoex.com')
    for email in candidates:
        if not User.query.filter(db.func.lower(User.email) == email.lower()).first():
            return email
    return f'{username.lower()}.{secrets.token_hex(3)}@defoex.com'


def _deduct_member_fee(member, approved_by_id):
    """Investor registration fee ₹10 — branch limit ↓, cash wallet ↑."""
    fees = float(member.member_fees or 10)
    branch_id = _resolve_member_branch(member)

    if not branch_id or fees <= 0:
        return {'amount': fees, 'skipped': True}, None

    return deduct_branch_wallet(
        branch_id,
        fees,
        f'Investor registration fee — {member.full_name} ({member.investor_id})',
        reference_id=f'INVESTOR-{member.investor_id}',
        created_by=approved_by_id,
    )


def finalize_investor_registration(member, approved_by_id):
    """
    Mark member approved, create member User, deduct ₹10 branch fee.
    Returns (credentials_dict, error_message).
    """
    if (member.approval_status or '').lower() == 'approved':
        existing = User.query.filter_by(mobile=member.mobile, role='member').first()
        if existing:
            return {
                'username': existing.username,
                'password': None,
                'already_approved': True,
                'message': f'Investor already approved. Username: {existing.username}',
            }, None
        return None, 'Investor already approved but login user not found'

    existing_user = User.query.filter_by(mobile=member.mobile).first()
    if existing_user:
        username = _investor_username(member)
        if username and existing_user.username.upper() != username:
            taken = User.query.filter(
                db.func.upper(User.username) == username
            ).filter(User.id != existing_user.id).first()
            if taken:
                return None, f'Login username {username} is already assigned to another user'
            existing_user.username = username

        member.approval_status = 'Approved'
        member.approved_by = int(approved_by_id) if approved_by_id else None
        member.approved_at = now_ist()
        _resolve_member_branch(member)
        try:
            fee_result, wallet_err = _deduct_member_fee(member, approved_by_id)
            if wallet_err:
                db.session.rollback()
                return None, wallet_err
            _link_adviser_investor(member)
            db.session.commit()
        except Exception as ex:
            db.session.rollback()
            return None, f'Approval failed: {str(ex)}'
        return {
            'username': existing_user.username,
            'password': None,
            'already_has_user': True,
            'wallet': fee_result,
            'message': f'Approved — login username: {existing_user.username}',
        }, None

    username = _investor_username(member)
    if not username:
        return None, 'Investor ID is missing — cannot create login'

    taken = User.query.filter(
        db.func.upper(User.username) == username
    ).first()
    if taken and taken.mobile != member.mobile:
        return None, f'Login username {username} is already assigned to another user'

    password = secrets.token_hex(5)
    email = _unique_member_email(username, member.email)
    branch_id = _resolve_member_branch(member)

    inv_user = User(
        username=username,
        email=email,
        full_name=member.full_name,
        mobile=member.mobile,
        role='member',
        branch_id=branch_id,
        is_active=True,
    )
    inv_user.set_password(password)

    member.approval_status = 'Approved'
    member.approved_by = int(approved_by_id) if approved_by_id else None
    member.approved_at = now_ist()

    try:
        db.session.add(inv_user)
        db.session.flush()

        fee_result, wallet_err = _deduct_member_fee(member, approved_by_id)
        if wallet_err:
            db.session.rollback()
            return None, wallet_err

        _link_adviser_investor(member)
        db.session.commit()
    except IntegrityError as ex:
        db.session.rollback()
        return None, f'Could not create login user: {str(ex.orig) if ex.orig else str(ex)}'
    except Exception as ex:
        db.session.rollback()
        return None, f'Approval failed: {str(ex)}'

    return {
        'username': username,
        'password': password,
        'wallet': fee_result,
        'message': (
            f'Congratulations Investor Created! Username: {username} Password: {password}'
        ),
    }, None


def _link_adviser_investor(member):
    adviser = Adviser.query.filter_by(mobile=member.mobile).first()
    if not adviser and member.email:
        adviser = Adviser.query.filter(
            db.func.lower(Adviser.email) == member.email.strip().lower()
        ).first()
    if adviser and not getattr(adviser, 'investor_id', None):
        adviser.investor_id = member.investor_id
