from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    create_access_token, create_refresh_token,
    jwt_required, get_jwt_identity, get_jwt
)
from models.user import User
from models.branch_wallet import BranchWallet
from extensions import db
from utils.helpers import success_response, error_response

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')


def _find_user_by_login(login):
    """Find user by username or email (case-insensitive)."""
    login = (login or '').strip()
    if not login:
        return None
    key = login.lower()
    return User.query.filter(
        db.or_(
            db.func.lower(User.username) == key,
            db.func.lower(User.email) == key,
        )
    ).first()


@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '')

    if not username or not password:
        return jsonify(error_response('Username and password required')[0]), 400

    user = _find_user_by_login(username)

    if not user or not user.check_password(password):
        return jsonify(error_response('Invalid credentials', 401)[0]), 401

    if not user.is_active:
        return jsonify(error_response('Account is inactive', 401)[0]), 401

    additional_claims = {
        'role': user.role,
        'branch_id': user.branch_id,
        'full_name': user.full_name
    }

    # Get wallet info if branch manager
    wallet_info = None
    if user.role == 'branchmanager' and user.branch_id:
        wallet = BranchWallet.query.filter_by(branch_id=user.branch_id).first()
        if wallet:
            wallet_info = wallet.to_dict()

    access_token = create_access_token(identity=str(user.id), additional_claims=additional_claims)
    refresh_token = create_refresh_token(identity=str(user.id))

    return jsonify(success_response({
        'access_token': access_token,
        'refresh_token': refresh_token,
        'user': user.to_dict(),
        'wallet': wallet_info
    }, 'Login successful')[0]), 200


@auth_bp.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    identity = get_jwt_identity()
    user = User.query.get(int(identity))
    if not user:
        return jsonify(error_response('User not found', 404)[0]), 404

    additional_claims = {
        'role': user.role,
        'branch_id': user.branch_id,
        'full_name': user.full_name
    }
    access_token = create_access_token(identity=identity, additional_claims=additional_claims)
    return jsonify(success_response({'access_token': access_token})[0]), 200


@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def me():
    identity = get_jwt_identity()
    user = User.query.get(int(identity))
    if not user:
        return jsonify(error_response('User not found', 404)[0]), 404
    return jsonify(success_response(user.to_dict())[0]), 200


@auth_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    return jsonify(success_response(message='Logged out successfully')[0]), 200


@auth_bp.route('/change-password', methods=['POST'])
@jwt_required()
def change_password():
    identity = get_jwt_identity()
    user = User.query.get(int(identity))
    data = request.get_json()

    if not user.check_password(data.get('current_password', '')):
        return jsonify(error_response('Current password is incorrect', 400)[0]), 400

    user.set_password(data.get('new_password', ''))
    db.session.commit()
    return jsonify(success_response(message='Password changed successfully')[0]), 200
