"""Approve investor registration and generate DEFIN login credentials."""

import secrets
from datetime import datetime

from extensions import db
from models.user import User
from models.adviser import Adviser
from utils.branch_wallet_ops import deduct_branch_wallet


def _unique_defin_username():
    year = datetime.utcnow().year
    seq = User.query.count() + 1
    username = f'DEFIN{year}{str(seq).zfill(2)}'
    while User.query.filter_by(username=username).first():
        seq += 1
        username = f'DEFIN{year}{str(seq).zfill(2)}'
    return username


def _deduct_member_fee(member, approved_by_id):
    """Investor registration fee ₹10 — branch limit ↓, cash wallet ↑."""
    fees = float(member.member_fees or 10)
    branch_id = member.branch_id
    if not branch_id and member.adviser_code:
        adv = Adviser.query.filter_by(adviser_code=member.adviser_code).first()
        if adv:
            branch_id = adv.branch_id
            member.branch_id = branch_id

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
        member.approval_status = 'Approved'
        member.approved_by = int(approved_by_id) if approved_by_id else None
        member.approved_at = datetime.utcnow()
        fee_result, wallet_err = _deduct_member_fee(member, approved_by_id)
        if wallet_err:
            db.session.rollback()
            return None, wallet_err
        _link_adviser_investor(member)
        db.session.commit()
        return {
            'username': existing_user.username,
            'password': None,
            'already_has_user': True,
            'wallet': fee_result,
            'message': f'Approved — existing login: {existing_user.username}',
        }, None

    username = _unique_defin_username()
    password = secrets.token_hex(5)
    email = member.email or f'{username.lower()}@defoex.com'
    if User.query.filter_by(email=email).first():
        email = f'{username.lower()}@defoex.com'

    inv_user = User(
        username=username,
        email=email,
        full_name=member.full_name,
        mobile=member.mobile,
        role='member',
        branch_id=member.branch_id,
        is_active=True,
    )
    inv_user.set_password(password)

    member.approval_status = 'Approved'
    member.approved_by = int(approved_by_id) if approved_by_id else None
    member.approved_at = datetime.utcnow()

    db.session.add(inv_user)
    db.session.flush()

    fee_result, wallet_err = _deduct_member_fee(member, approved_by_id)
    if wallet_err:
        db.session.rollback()
        return None, wallet_err

    _link_adviser_investor(member)
    db.session.commit()

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
