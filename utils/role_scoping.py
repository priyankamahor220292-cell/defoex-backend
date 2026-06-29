"""Scope queries by logged-in role (branch manager, adviser, member)."""

from flask_jwt_extended import get_jwt_identity, get_jwt
from sqlalchemy import false

from models.user import User
from utils.member_lookup import find_adviser_for_user

ROLES_HIDE_BRANCH = frozenset({'advisor', 'adviser', 'member'})
BRANCH_FIELD_KEYS = frozenset({
    'branch_id', 'branch_name', 'branch_code',
})


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


def should_hide_branch(role=None):
    """Adviser and investor panels must not expose DefOex branch metadata."""
    role = (role or current_role() or '').lower()
    return role in ROLES_HIDE_BRANCH


def strip_branch_fields(data):
    """Recursively remove DefOex branch fields from API payloads."""
    if isinstance(data, dict):
        out = {}
        for key, value in data.items():
            if key in BRANCH_FIELD_KEYS or key == 'branch':
                continue
            if key == 'wallet' and should_hide_branch():
                continue
            out[key] = strip_branch_fields(value)
        return out
    if isinstance(data, list):
        return [strip_branch_fields(item) for item in data]
    return data


def sanitize_response(data, role=None):
    """Strip branch metadata when the caller is an adviser or investor."""
    if should_hide_branch(role):
        return strip_branch_fields(data)
    return data


def user_public_dict(user):
    """Role-aware user payload for login / profile."""
    from utils.helpers import branch_manager_display_name

    full_name = user.full_name
    if user.role == 'branchmanager':
        full_name = branch_manager_display_name(full_name)
    payload = {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'full_name': full_name,
        'mobile': user.mobile,
        'role': user.role,
        'is_active': user.is_active,
        'created_at': user.created_at.isoformat() if user.created_at else None,
    }
    role = (user.role or '').lower()
    if role == 'branchmanager':
        payload['branch_id'] = user.branch_id
    elif role == 'superadmin':
        payload['branch_id'] = user.branch_id
    return payload


def branch_access_error(branch_id):
    """
    Return an error message if the current user may not access this branch,
    or None if access is allowed.
    """
    claims = get_jwt() or {}
    role = (claims.get('role') or '').lower()

    if role == 'superadmin':
        return None

    if role == 'branchmanager':
        user_branch = claims.get('branch_id')
        if user_branch is not None and int(user_branch) == int(branch_id):
            return None
        return 'Access denied: you can only view your own branch'

    if role in ROLES_HIDE_BRANCH:
        return 'Unauthorized'

    return 'Unauthorized'
