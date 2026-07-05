from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
import secrets
from models.user import User
from models.adviser import Adviser
from models.notification import Notification
from models.member import Member
from models.investment import Investment
from models.branch_wallet import WalletTransaction
from extensions import db
from utils.helpers import success_response, error_response

users_bp = Blueprint('users', __name__, url_prefix='/api/users')

PORTAL_CRUD_ROLES = frozenset({'advisor', 'member', 'branchmanager'})


def _require_superadmin():
    claims = get_jwt()
    if claims.get('role') != 'superadmin':
        return jsonify(error_response('Unauthorized', 403)[0]), 403
    return None


def _sync_adviser_login(user, old_username=None):
    """Keep adviser.login_username aligned when an advisor portal user is updated."""
    if user.role != 'advisor':
        return
    username = (user.username or '').strip().upper()
    if not username:
        return

    adviser = None
    if old_username:
        adviser = Adviser.query.filter(
            db.func.upper(Adviser.login_username) == old_username.strip().upper()
        ).first()
    if not adviser and user.mobile:
        adviser = Adviser.query.filter_by(mobile=user.mobile).first()
    if not adviser:
        adviser = Adviser.query.filter(
            db.func.upper(Adviser.adviser_code) == username
        ).first()

    if adviser:
        adviser.login_username = username
        if user.full_name:
            adviser.full_name = user.full_name
        if user.email:
            adviser.email = user.email
        if user.mobile:
            adviser.mobile = user.mobile
        if user.branch_id:
            adviser.branch_id = user.branch_id


def _sync_member_profile(user):
    """Keep linked investor profile aligned when a member portal user is updated."""
    if user.role != 'member':
        return

    username = (user.username or '').strip().upper()
    member = None
    if username:
        member = Member.query.filter(
            db.func.upper(Member.investor_id) == username
        ).first()
    if not member and user.mobile:
        member = Member.query.filter_by(mobile=user.mobile).first()

    if member:
        if user.full_name:
            member.full_name = user.full_name
        if user.email:
            member.email = user.email
        if user.mobile:
            member.mobile = user.mobile
        if user.branch_id:
            member.branch_id = user.branch_id


@users_bp.route('/', methods=['GET'])
@jwt_required()
def list_users():
    denied = _require_superadmin()
    if denied:
        return denied

    role = (request.args.get('role') or '').strip().lower()
    q = User.query
    if role in PORTAL_CRUD_ROLES:
        q = q.filter_by(role=role)
    users = q.order_by(User.id.desc()).all()
    return jsonify(success_response([u.to_dict() for u in users])[0]), 200


@users_bp.route('/<int:user_id>', methods=['GET'])
@jwt_required()
def get_user(user_id):
    denied = _require_superadmin()
    if denied:
        return denied
    user = User.query.get_or_404(user_id)
    return jsonify(success_response(user.to_dict())[0]), 200


@users_bp.route('/', methods=['POST'])
@jwt_required()
def create_user():
    denied = _require_superadmin()
    if denied:
        return denied

    data = request.get_json() or {}
    role = (data.get('role') or '').strip().lower()
    username = (data.get('username') or '').strip()
    email = (data.get('email') or '').strip()

    if not username or not email or not data.get('full_name') or not data.get('password'):
        return jsonify(error_response('Username, email, password, and full name are required')[0]), 400

    if role not in PORTAL_CRUD_ROLES.union({'superadmin', 'branchmanager'}):
        return jsonify(error_response('Invalid role')[0]), 400

    if User.query.filter(db.func.lower(User.username) == username.lower()).first():
        return jsonify(error_response('Username already exists')[0]), 409
    if User.query.filter(db.func.lower(User.email) == email.lower()).first():
        return jsonify(error_response('Email already exists')[0]), 409

    if role == 'branchmanager' and not data.get('branch_id'):
        return jsonify(error_response('Branch is required for branch manager accounts')[0]), 400

    user = User(
        username=username,
        email=email,
        full_name=data['full_name'],
        mobile=data.get('mobile'),
        role=role,
        branch_id=data.get('branch_id'),
    )
    user.set_password(data['password'])
    db.session.add(user)
    db.session.flush()

    if role == 'advisor':
        _sync_adviser_login(user)
    elif role == 'member':
        _sync_member_profile(user)

    db.session.commit()
    payload = user.to_dict()
    payload['password'] = data['password']
    return jsonify(success_response(payload, 'User created')[0]), 201


@users_bp.route('/<int:user_id>', methods=['PUT'])
@jwt_required()
def update_user(user_id):
    denied = _require_superadmin()
    if denied:
        return denied

    user = User.query.get_or_404(user_id)
    data = request.get_json() or {}
    old_username = user.username

    editable_fields = {'full_name', 'email', 'mobile', 'branch_id', 'username'}
    wants_profile_edit = any(field in data for field in editable_fields)

    if wants_profile_edit and user.role not in PORTAL_CRUD_ROLES:
        return jsonify(error_response(
            'Only branch manager, advisor, and investor accounts can be edited here'
        )[0]), 400

    if user.role == 'branchmanager' and 'branch_id' in data and not data.get('branch_id'):
        return jsonify(error_response('Branch is required for branch manager accounts')[0]), 400

    if 'username' in data:
        username = (data.get('username') or '').strip()
        if not username:
            return jsonify(error_response('Username is required')[0]), 400
        taken = User.query.filter(
            db.func.lower(User.username) == username.lower(),
            User.id != user.id,
        ).first()
        if taken:
            return jsonify(error_response('Username already exists')[0]), 409
        user.username = username

    if 'email' in data:
        email = (data.get('email') or '').strip()
        if not email:
            return jsonify(error_response('Email is required')[0]), 400
        taken = User.query.filter(
            db.func.lower(User.email) == email.lower(),
            User.id != user.id,
        ).first()
        if taken:
            return jsonify(error_response('Email already exists')[0]), 409
        user.email = email

    for field in ['full_name', 'mobile', 'branch_id', 'is_active']:
        if field in data:
            setattr(user, field, data[field])

    if wants_profile_edit:
        if user.role == 'advisor':
            _sync_adviser_login(user, old_username=old_username)
        elif user.role == 'member':
            _sync_member_profile(user)

    db.session.commit()
    return jsonify(success_response(user.to_dict(), 'User updated')[0]), 200


@users_bp.route('/<int:user_id>/reset-password', methods=['POST'])
@jwt_required()
def reset_password(user_id):
    """Super Admin only — set or auto-generate a user's login password."""
    denied = _require_superadmin()
    if denied:
        return denied

    user = User.query.get_or_404(user_id)
    data = request.get_json(silent=True) or {}

    password = (data.get('password') or '').strip()
    if not password:
        password = secrets.token_hex(5)
    elif len(password) < 6:
        return jsonify(error_response('Password must be at least 6 characters', 400)[0]), 400

    user.set_password(password)
    db.session.commit()

    return jsonify(success_response({
        'id': user.id,
        'username': user.username,
        'full_name': user.full_name,
        'role': user.role,
        'password': password,
        'message': (
            f'Password reset for {user.username}. '
            f'Share the new password securely with the user.'
        ),
    }, 'Password reset successfully')[0]), 200


@users_bp.route('/<int:user_id>', methods=['DELETE'])
@jwt_required()
def delete_user(user_id):
    """Super Admin only — delete branch manager, advisor, or investor portal accounts."""
    denied = _require_superadmin()
    if denied:
        return denied

    current_id = get_jwt_identity()
    user = User.query.get_or_404(user_id)

    if str(user.id) == str(current_id):
        return jsonify(error_response('Cannot delete your own account')[0]), 400

    if user.role not in PORTAL_CRUD_ROLES:
        return jsonify(error_response(
            'Only branch manager, advisor, and investor accounts can be deleted'
        )[0]), 400

    Notification.query.filter_by(user_id=user.id).delete()
    Member.query.filter_by(approved_by=user.id).update({'approved_by': None})
    Investment.query.filter_by(approved_by=user.id).update({'approved_by': None})
    WalletTransaction.query.filter_by(created_by=user.id).update({'created_by': None})

    db.session.delete(user)
    db.session.commit()
    return jsonify(success_response({'id': user_id}, 'User deleted')[0]), 200
