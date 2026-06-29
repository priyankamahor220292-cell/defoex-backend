from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
import secrets
from models.user import User
from models.branch import Branch
from extensions import db
from utils.helpers import success_response, error_response

users_bp = Blueprint('users', __name__, url_prefix='/api/users')


@users_bp.route('/', methods=['GET'])
@jwt_required()
def list_users():
    claims = get_jwt()
    if claims.get('role') != 'superadmin':
        return jsonify(error_response('Unauthorized', 403)[0]), 403
    users = User.query.all()
    return jsonify(success_response([u.to_dict() for u in users])[0]), 200


@users_bp.route('/', methods=['POST'])
@jwt_required()
def create_user():
    claims = get_jwt()
    if claims.get('role') != 'superadmin':
        return jsonify(error_response('Unauthorized', 403)[0]), 403

    data = request.get_json()
    if User.query.filter_by(username=data['username']).first():
        return jsonify(error_response('Username already exists')[0]), 409

    user = User(
        username=data['username'],
        email=data['email'],
        full_name=data['full_name'],
        mobile=data.get('mobile'),
        role=data['role'],
        branch_id=data.get('branch_id')
    )
    user.set_password(data['password'])
    db.session.add(user)
    db.session.commit()
    payload = user.to_dict()
    payload['password'] = data['password']
    return jsonify(success_response(payload, 'User created')[0]), 201


@users_bp.route('/<int:user_id>', methods=['PUT'])
@jwt_required()
def update_user(user_id):
    claims = get_jwt()
    if claims.get('role') != 'superadmin':
        return jsonify(error_response('Unauthorized', 403)[0]), 403

    user = User.query.get_or_404(user_id)
    data = request.get_json()
    for field in ['full_name', 'email', 'mobile', 'role', 'branch_id', 'is_active']:
        if field in data:
            setattr(user, field, data[field])
    db.session.commit()
    return jsonify(success_response(user.to_dict(), 'User updated')[0]), 200


@users_bp.route('/<int:user_id>/reset-password', methods=['POST'])
@jwt_required()
def reset_password(user_id):
    """Super Admin only — set or auto-generate a user's login password."""
    claims = get_jwt()
    if claims.get('role') != 'superadmin':
        return jsonify(error_response('Unauthorized', 403)[0]), 403

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
