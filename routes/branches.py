from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from models.branch import Branch
from models.branch_wallet import BranchWallet, WalletTransaction
from models.user import User
from extensions import db
from utils.helpers import success_response, error_response

branches_bp = Blueprint('branches', __name__, url_prefix='/api/branches')


def _ensure_wallet(branch_id):
    """Get or create wallet for a branch"""
    wallet = BranchWallet.query.filter_by(branch_id=branch_id).first()
    if not wallet:
        wallet = BranchWallet(
            branch_id=branch_id,
            current_balance=0,
            cash_wallet=0,
            low_balance_threshold=10000
        )
        db.session.add(wallet)
        db.session.flush()
    return wallet


@branches_bp.route('/', methods=['GET'])
@jwt_required()
def list_branches():
    branches = Branch.query.filter_by(is_active=True).all()
    return jsonify(success_response([b.to_dict() for b in branches])[0]), 200


@branches_bp.route('/<int:branch_id>', methods=['GET'])
@jwt_required()
def get_branch(branch_id):
    branch = Branch.query.get_or_404(branch_id)
    data = branch.to_dict()
    wallet = _ensure_wallet(branch_id)
    db.session.commit()
    data['wallet'] = wallet.to_dict()
    return jsonify(success_response(data)[0]), 200


@branches_bp.route('/', methods=['POST'])
@jwt_required()
def create_branch():
    claims = get_jwt()
    if claims.get('role') != 'superadmin':
        return jsonify(error_response('Unauthorized', 403)[0]), 403

    data = request.get_json() or {}
    # Only pass valid Branch fields
    allowed = ['branch_code','branch_name','address','city','state','pincode',
               'manager_name','manager_email','manager_mobile','is_active']
    branch_data = {k: v for k, v in data.items() if k in allowed}
    branch = Branch(**branch_data)
    db.session.add(branch)
    db.session.flush()

    wallet = BranchWallet(branch_id=branch.id, current_balance=0, cash_wallet=0, low_balance_threshold=10000)
    db.session.add(wallet)
    db.session.commit()
    return jsonify(success_response(branch.to_dict(), 'Branch created')[0]), 201


@branches_bp.route('/<int:branch_id>/topup', methods=['POST'])
@jwt_required()
def topup_wallet(branch_id):
    claims = get_jwt()
    if claims.get('role') != 'superadmin':
        return jsonify(error_response('Unauthorized', 403)[0]), 403

    identity = get_jwt_identity()
    data = request.get_json() or {}

    try:
        amount = float(data.get('amount', 0))
    except (TypeError, ValueError):
        amount = 0

    if amount <= 0:
        return jsonify(error_response('Amount must be a positive number')[0]), 400

    # Ensure branch exists
    Branch.query.get_or_404(branch_id)

    wallet = _ensure_wallet(branch_id)
    old_balance = float(wallet.current_balance or 0)
    wallet.current_balance = old_balance + amount

    txn = WalletTransaction(
        branch_id=branch_id,
        transaction_type='TopUp',
        amount=amount,
        description=data.get('description') or 'Admin top-up',
        balance_after=wallet.current_balance,
        cash_wallet_after=wallet.cash_wallet,
        created_by=int(identity)
    )
    db.session.add(txn)
    db.session.commit()

    return jsonify(success_response(
        wallet.to_dict(),
        f'₹{amount:,.0f} added to branch wallet successfully'
    )[0]), 200


@branches_bp.route('/<int:branch_id>/wallet-history', methods=['GET'])
@jwt_required()
def wallet_history(branch_id):
    page = request.args.get('page', 1, type=int)
    txns = WalletTransaction.query\
        .filter_by(branch_id=branch_id)\
        .order_by(WalletTransaction.created_at.desc())\
        .paginate(page=page, per_page=20, error_out=False)
    return jsonify(success_response({
        'items': [t.to_dict() for t in txns.items],
        'total': txns.total
    })[0]), 200


@branches_bp.route('/fix-wallets', methods=['POST'])
@jwt_required()
def fix_wallets():
    """Auto-create missing wallets for all branches — run once"""
    claims = get_jwt()
    if claims.get('role') != 'superadmin':
        return jsonify(error_response('Unauthorized', 403)[0]), 403

    branches = Branch.query.all()
    fixed = 0
    for b in branches:
        existing = BranchWallet.query.filter_by(branch_id=b.id).first()
        if not existing:
            wallet = BranchWallet(branch_id=b.id, current_balance=0, cash_wallet=0, low_balance_threshold=10000)
            db.session.add(wallet)
            fixed += 1
    db.session.commit()
    return jsonify(success_response({'fixed': fixed}, f'Created wallets for {fixed} branches')[0]), 200