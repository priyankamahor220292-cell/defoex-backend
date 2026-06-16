from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from models.branch import Branch
from models.branch_wallet import BranchWallet, WalletTransaction, AdminWallet, ADMIN_WALLET_LIMIT
from extensions import db
from utils.helpers import success_response, error_response
from sqlalchemy import text
import traceback

branches_bp = Blueprint('branches', __name__, url_prefix='/api/branches')


def _ensure_wallet(branch_id):
    w = BranchWallet.query.filter_by(branch_id=branch_id).first()
    if not w:
        w = BranchWallet(branch_id=branch_id, current_balance=0, cash_wallet=0)
        db.session.add(w)
        db.session.flush()
    return w


def _ensure_admin_wallet():
    try:
        aw = AdminWallet.query.first()
        if not aw:
            aw = AdminWallet(total_limit=ADMIN_WALLET_LIMIT, total_distributed=0, total_returned=0)
            db.session.add(aw)
            db.session.flush()
        return aw
    except Exception:
        # Table might not exist — create it via raw SQL
        with db.engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS admin_wallet (
                    id SERIAL PRIMARY KEY,
                    total_limit NUMERIC(18,2) DEFAULT 10000000000,
                    total_distributed NUMERIC(18,2) DEFAULT 0,
                    total_returned NUMERIC(18,2) DEFAULT 0,
                    low_balance_threshold NUMERIC(18,2) DEFAULT 100000000,
                    updated_at TIMESTAMP DEFAULT NOW(),
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text("""
                INSERT INTO admin_wallet (total_limit, total_distributed, total_returned)
                SELECT 10000000000, 0, 0
                WHERE NOT EXISTS (SELECT 1 FROM admin_wallet)
            """))
            conn.commit()
        return AdminWallet.query.first()


@branches_bp.route('/', methods=['GET'])
@jwt_required()
def list_branches():
    try:
        branches = Branch.query.filter_by(is_active=True).all()
        result = []
        for b in branches:
            d = b.to_dict()
            w = BranchWallet.query.filter_by(branch_id=b.id).first()
            d['wallet'] = w.to_dict() if w else None
            result.append(d)
        return jsonify(success_response(result)[0]), 200
    except Exception as e:
        print(traceback.format_exc())
        return jsonify(error_response(str(e))[0]), 500


@branches_bp.route('/<int:branch_id>', methods=['GET'])
@jwt_required()
def get_branch(branch_id):
    branch = Branch.query.get_or_404(branch_id)
    data   = branch.to_dict()
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
    data   = request.get_json() or {}
    allowed = ['branch_code','branch_name','address','city','state','pincode',
               'manager_name','manager_email','manager_mobile','is_active']
    branch = Branch(**{k: v for k, v in data.items() if k in allowed})
    db.session.add(branch)
    db.session.flush()
    db.session.add(BranchWallet(branch_id=branch.id, current_balance=0, cash_wallet=0))
    db.session.commit()
    return jsonify(success_response(branch.to_dict(), 'Branch created')[0]), 201


@branches_bp.route('/admin-wallet', methods=['GET'])
@jwt_required()
def get_admin_wallet():
    claims = get_jwt()
    if claims.get('role') != 'superadmin':
        return jsonify(error_response('Unauthorized', 403)[0]), 403
    try:
        aw = _ensure_admin_wallet()
        db.session.commit()

        branches = Branch.query.filter_by(is_active=True).all()
        branch_wallets = []
        for b in branches:
            w = BranchWallet.query.filter_by(branch_id=b.id).first()
            branch_wallets.append({
                'branch_id':       b.id,
                'branch_code':     b.branch_code,
                'branch_name':     b.branch_name,
                'current_balance': float(w.current_balance or 0) if w else 0,
                'cash_wallet':     float(w.cash_wallet or 0) if w else 0,
                'is_low_balance':  w.is_low_balance if w else False,
            })

        try:
            txns = WalletTransaction.query\
                .order_by(WalletTransaction.created_at.desc()).limit(50).all()
            txn_list = [t.to_dict() for t in txns]
        except Exception:
            txn_list = []

        return jsonify(success_response({
            'admin_wallet':   aw.to_dict() if aw else None,
            'branch_wallets': branch_wallets,
            'transactions':   txn_list,
        })[0]), 200
    except Exception as e:
        print(traceback.format_exc())
        return jsonify(error_response(str(e))[0]), 500


@branches_bp.route('/<int:branch_id>/topup', methods=['POST'])
@jwt_required()
def topup_wallet(branch_id):
    claims = get_jwt()
    if claims.get('role') != 'superadmin':
        return jsonify(error_response('Unauthorized', 403)[0]), 403

    identity = get_jwt_identity()
    data     = request.get_json() or {}
    try:
        amount = float(data.get('amount', 0))
    except (TypeError, ValueError):
        amount = 0
    if amount <= 0:
        return jsonify(error_response('Amount must be positive')[0]), 400

    Branch.query.get_or_404(branch_id)

    try:
        aw = _ensure_admin_wallet()
        if aw and aw.available_balance < amount:
            return jsonify(error_response(
                f'Admin wallet insufficient. Available: {aw.available_balance:,.0f}'
            )[0]), 400

        # Update admin wallet
        if aw:
            aw.total_distributed = float(aw.total_distributed or 0) + amount

        # Update branch wallet
        wallet = _ensure_wallet(branch_id)
        wallet.current_balance = float(wallet.current_balance or 0) + amount

        # Record transaction using raw SQL to avoid Enum issues
        from datetime import datetime
        db.session.execute(
            text("""INSERT INTO wallet_transactions
                    (branch_id, transaction_type, amount, description,
                     balance_after, cash_wallet_after, created_by, created_at)
                    VALUES (:bid, :ttype, :amt, :desc,
                            :bal, :cash, :by, :at)"""),
            {
                'bid':   branch_id,
                'ttype': 'TopUp',
                'amt':   amount,
                'desc':  data.get('description') or 'Admin top-up',
                'bal':   float(wallet.current_balance),
                'cash':  float(wallet.cash_wallet or 0),
                'by':    int(identity),
                'at':    datetime.utcnow(),
            }
        )
        db.session.commit()
        return jsonify(success_response(
            wallet.to_dict(),
            f'Added successfully to branch wallet'
        )[0]), 200

    except Exception as e:
        db.session.rollback()
        print(traceback.format_exc())
        return jsonify(error_response(f'Top-up failed: {str(e)}')[0]), 500


@branches_bp.route('/<int:branch_id>/wallet-history', methods=['GET'])
@jwt_required()
def wallet_history(branch_id):
    try:
        page = request.args.get('page', 1, type=int)
        txns = WalletTransaction.query\
            .filter_by(branch_id=branch_id)\
            .order_by(WalletTransaction.created_at.desc())\
            .paginate(page=page, per_page=20, error_out=False)
        return jsonify(success_response({
            'items': [t.to_dict() for t in txns.items],
            'total': txns.total,
        })[0]), 200
    except Exception as e:
        return jsonify(success_response({'items': [], 'total': 0})[0]), 200


@branches_bp.route('/fix-wallets', methods=['POST'])
@jwt_required()
def fix_wallets():
    claims = get_jwt()
    if claims.get('role') != 'superadmin':
        return jsonify(error_response('Unauthorized', 403)[0]), 403
    branches = Branch.query.all()
    fixed = 0
    for b in branches:
        if not BranchWallet.query.filter_by(branch_id=b.id).first():
            db.session.add(BranchWallet(branch_id=b.id, current_balance=0, cash_wallet=0))
            fixed += 1
    db.session.commit()
    return jsonify(success_response({'fixed': fixed})[0]), 200