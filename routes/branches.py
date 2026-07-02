from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from models.branch import Branch
from models.branch_wallet import BranchWallet, WalletTransaction, AdminWallet, ADMIN_WALLET_LIMIT
from extensions import db
from utils.helpers import success_response, error_response
from utils.datetime_utils import now_ist, isoformat_ist
from utils.role_scoping import branch_access_error, should_hide_branch
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
        claims = get_jwt() or {}
        role = (claims.get('role') or '').lower()

        if should_hide_branch(role):
            return jsonify(error_response('Unauthorized', 403)[0]), 403

        q = Branch.query.filter_by(is_active=True)
        if role == 'branchmanager':
            branch_id = claims.get('branch_id')
            if not branch_id:
                return jsonify(success_response([])[0]), 200
            q = q.filter_by(id=int(branch_id))

        branches = q.all()
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
    denied = branch_access_error(branch_id)
    if denied:
        return jsonify(error_response(denied, 403)[0]), 403

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

    # Auto-create branch-specific tables
    try:
        from utils.branch_schema import create_branch_tables
        create_branch_tables(branch.branch_code)
        print(f"Branch tables created for {branch.branch_code}")
    except Exception as e:
        print(f"Warning: could not create branch tables: {e}")

    return jsonify(success_response({
        **branch.to_dict(),
        'branch_tables_created': True,
        'tables': [
            f'{branch.branch_code}_advisers',
            f'{branch.branch_code}_members',
            f'{branch.branch_code}_investments',
            f'{branch.branch_code}_installments',
            f'{branch.branch_code}_commissions',
        ]
    }, f'Branch {branch.branch_code} created with dedicated tables')[0]), 201


@branches_bp.route('/admin-wallet', methods=['GET'])
@jwt_required()
def admin_wallet_status():
    from sqlalchemy import text as st
    claims = get_jwt()
    if claims.get('role') != 'superadmin':
        return jsonify(error_response('Unauthorized', 403)[0]), 403

    TOTAL_LIMIT = 1_000_000_000  # ₹1,00,00,00,000 fixed

    aw = AdminWallet.query.first()
    if not aw:
        aw = AdminWallet(total_limit=TOTAL_LIMIT, total_distributed=0, total_returned=0)
        db.session.add(aw)
        db.session.commit()

    # Correct columns: total_limit, total_distributed, total_returned
    # available = total_limit - total_distributed + total_returned
    aw.total_limit = TOTAL_LIMIT
    db.session.commit()

    limit    = float(aw.total_limit or TOTAL_LIMIT)
    dist     = float(aw.total_distributed or 0)
    ret      = float(aw.total_returned or 0)
    avail    = limit - dist + ret
    used_pct = round((dist / limit) * 100, 2) if limit > 0 else 0

    branches = Branch.query.all()
    branch_wallets = []
    for b in branches:
        bw = BranchWallet.query.filter_by(branch_id=b.id).first()
        branch_wallets.append({
            'branch_id':       b.id,
            'branch_name':     b.branch_name,
            'branch_code':     b.branch_code,
            'current_balance': float(bw.current_balance) if bw else 0,
            'cash_wallet':     float(bw.cash_wallet)     if bw else 0,
            'is_low_balance':  bw.is_low_balance         if bw else False,
        })

    # Transactions for history
    txns = WalletTransaction.query.order_by(
        WalletTransaction.created_at.desc()).limit(100).all()

    return jsonify(success_response({
        'admin_wallet': {
            'total_limit':       limit,
            'total_distributed': dist,
            'total_returned':    ret,
            'available_balance': avail,
            'used_amount':       dist - ret,
            'use_percentage':    used_pct,
            'is_low_balance':    avail < float(aw.low_balance_threshold or 0),
        },
        'branch_wallets': branch_wallets,
        'transactions':   [t.to_dict() for t in txns],
    })[0]), 200

@branches_bp.route('/<int:branch_id>/topup', methods=['POST'])
@jwt_required()
def topup_branch_wallet(branch_id):
    claims = get_jwt()
    if claims.get('role') != 'superadmin':
        return jsonify(error_response('Unauthorized', 403)[0]), 403

    data   = request.get_json() or {}
    amount = float(data.get('amount', 0))
    desc   = data.get('description', 'Admin top-up')

    # FIX: max ₹1,00,00,00,000 per transaction
    MAX_TXN     = 1_000_000_000
    TOTAL_LIMIT = 1_000_000_000

    if amount <= 0:
        return jsonify(error_response('Amount must be positive')[0]), 400
    if amount > MAX_TXN:
        return jsonify(error_response('Maximum transaction is ₹1,00,00,00,000')[0]), 400

    branch = Branch.query.get_or_404(branch_id)
    aw     = AdminWallet.query.first()
    if not aw:
        aw = AdminWallet(total_limit=TOTAL_LIMIT, total_distributed=0, total_returned=0)
        db.session.add(aw)
        db.session.flush()

    # Use correct columns: available = total_limit - total_distributed + total_returned
    avail = float(aw.total_limit or TOTAL_LIMIT) - float(aw.total_distributed or 0) + float(aw.total_returned or 0)

    # FIX: prevent negative balance
    if avail < amount:
        return jsonify(error_response(
            f'Insufficient admin balance. Available: ₹{avail:,.0f}'
        )[0]), 400

    # Get or create branch wallet
    bw = BranchWallet.query.filter_by(branch_id=branch_id).first()
    if not bw:
        bw = BranchWallet(branch_id=branch_id, current_balance=0, cash_wallet=0)
        db.session.add(bw)
        db.session.flush()

    # Update admin wallet — use correct column: total_distributed
    aw.total_distributed = float(aw.total_distributed or 0) + amount
    aw.updated_at = now_ist()

    # Update branch wallet
    bw.current_balance = float(bw.current_balance or 0) + amount
    bw.updated_at = now_ist()

    identity = get_jwt_identity()
    try:
        created_by = int(identity)
    except (TypeError, ValueError):
        created_by = None

    txn = WalletTransaction(
        branch_id=int(branch_id),
        transaction_type='TopUp',
        amount=amount,
        description=desc,
        balance_after=float(bw.current_balance),
        cash_wallet_after=float(bw.cash_wallet or 0),
        created_by=created_by,
        created_at=now_ist(),
    )
    db.session.add(txn)

    db.session.commit()

    new_avail = avail - amount
    return jsonify(success_response({
        'branch_name':    branch.branch_name,
        'amount_added':   amount,
        'branch_balance': float(bw.current_balance),
        'admin_balance':  new_avail,
        'transaction':    txn.to_dict(),
        'topup_at':       isoformat_ist(txn.created_at),
    }, f'₹{amount:,.0f} sent to {branch.branch_name}')[0]), 200

@branches_bp.route('/<int:branch_id>/wallet-history', methods=['GET'])
@jwt_required()
def wallet_history(branch_id):
    denied = branch_access_error(branch_id)
    if denied:
        return jsonify(error_response(denied, 403)[0]), 403

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