"""Scope queries by logged-in role (branch manager, adviser, member)."""

from flask_jwt_extended import get_jwt_identity, get_jwt
from sqlalchemy import false

from models.user import User
from utils.member_lookup import find_adviser_for_user


def current_user():
    identity = get_jwt_identity()
    if identity is None:
        return None
    try:
        return User.query.get(int(identity))
    except (TypeError, ValueError):
        return User.query.filter_by(username=str(identity).strip()).first()


def current_role():
    return ((get_jwt() or {}).get('role') or '').lower()


def current_adviser():
    role = current_role()
    if role not in ('advisor', 'adviser'):
        return None
    user = current_user()
    if not user:
        return None
    return find_adviser_for_user(user)


def scope_members(query):
    """Limit Member query to branch (BM) or direct adviser code (adviser)."""
    claims = get_jwt() or {}
    role = current_role()

    if role == 'branchmanager' and claims.get('branch_id'):
        return query.filter_by(branch_id=claims['branch_id'])

    if role in ('advisor', 'adviser'):
        adviser = current_adviser()
        if not adviser:
            return query.filter(false())
        return query.filter_by(adviser_code=adviser.adviser_code)

    return query


def scope_investments(query):
    """Limit Investment query to branch (BM) or adviser code (adviser)."""
    claims = get_jwt() or {}
    role = current_role()

    if role == 'branchmanager' and claims.get('branch_id'):
        return query.filter_by(branch_id=claims['branch_id'])

    if role in ('advisor', 'adviser'):
        adviser = current_adviser()
        if not adviser:
            return query.filter(false())
        return query.filter_by(adviser_code=adviser.adviser_code)

    return query


def scope_commissions(query):
    """Limit Commission query to branch advisers (BM) or own code (adviser)."""
    from models.adviser import Adviser
    from models.commission import Commission

    claims = get_jwt() or {}
    role = current_role()

    if role == 'branchmanager' and claims.get('branch_id'):
        branch_codes = [
            a.adviser_code for a in Adviser.query.filter_by(
                branch_id=claims['branch_id'],
                is_active=True,
                is_company_owner=False,
            ).all()
        ]
        if not branch_codes:
            return query.filter(false())
        return query.filter(Commission.adviser_code.in_(branch_codes))

    if role in ('advisor', 'adviser'):
        adviser = current_adviser()
        if not adviser:
            return query.filter(false())
        return query.filter_by(adviser_code=adviser.adviser_code)

    owner = Adviser.query.filter_by(is_company_owner=True).first()
    if owner:
        query = query.filter(Commission.adviser_code != owner.adviser_code)
    return query
