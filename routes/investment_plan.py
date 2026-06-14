from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from models.investment import Investment, Installment, MIS_PLANS
from models.member import Member
from models.branch import Branch
from models.branch_wallet import BranchWallet, WalletTransaction
from models.adviser import Adviser
from models.commission import Commission, MIS_COMMISSION_RATES
from models.notification import Notification
from extensions import db
from utils.helpers import generate_irn, success_response, error_response
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
import traceback

investment_plan_bp = Blueprint('investment_plan', __name__, url_prefix='/api/investment-plans')


def safe_date(val):
    if not val:
        return None
    try:
        if '/' in str(val):
            return datetime.strptime(str(val), '%m/%d/%Y').date()
        return date.fromisoformat(str(val))
    except Exception:
        return None


def get_or_create_wallet(branch_id):
    """Always returns a wallet — creates one if missing"""
    if not branch_id:
        return None
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


def resolve_branch_id(claims, data=None):
    """
    Get branch_id from:
    1. JWT claims (for branchmanager)
    2. Request body branch_id (for superadmin)
    3. Investor's branch (fallback)
    """
    branch_id = claims.get('branch_id')
    if branch_id:
        return branch_id
    # Superadmin — try from request body or investor
    if data:
        body_branch = data.get('branch_id')
        if body_branch:
            return int(body_branch)
    return None


def _create_commission(investment, adviser):
    try:
        rate_table = MIS_COMMISSION_RATES.get(adviser.rank_name, {})
        rate = rate_table.get(investment.plan_tenure, 0)
        if rate and investment.total_investment_amount:
            comm = Commission(
                investment_id=investment.id,
                adviser_code=adviser.adviser_code,
                adviser_rank=adviser.rank_name,
                plan_type=investment.plan_type,
                plan_tenure=investment.plan_tenure,
                investment_amount=investment.total_investment_amount,
                commission_rate=rate,
                commission_amount=float(investment.total_investment_amount) * rate / 100
            )
            db.session.add(comm)
    except Exception as e:
        print(f"Commission calc error: {e}")


@investment_plan_bp.route('/create', methods=['POST'])
@jwt_required()
def create_plan():
    claims = get_jwt()
    data = request.get_json() or {}

    investor_id    = str(data.get('investor_id', '')).strip()
    plan_tenure    = str(data.get('plan_tenure', '')).strip()
    monthly_amount = data.get('monthly_amount')

    if not investor_id:
        return jsonify(error_response('investor_id is required')[0]), 400
    if not plan_tenure or plan_tenure not in MIS_PLANS:
        return jsonify(error_response('plan_tenure must be 3Y, 5Y, or 7Y')[0]), 400
    try:
        monthly_amount = float(monthly_amount)
        if monthly_amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify(error_response('monthly_amount must be a positive number')[0]), 400

    # Validate investor
    member = Member.query.filter_by(investor_id=investor_id, approval_status='Approved').first()
    if not member:
        return jsonify(error_response('Investor not found or not yet approved')[0]), 404

    # Resolve branch_id — BM gets it from JWT, superadmin gets it from investor's branch
    branch_id = resolve_branch_id(claims, data)
    if not branch_id:
        # Fall back to investor's branch
        branch_id = member.branch_id
    if not branch_id:
        # Last fallback: first active branch
        first_branch = Branch.query.filter_by(is_active=True).first()
        if first_branch:
            branch_id = first_branch.id

    if not branch_id:
        return jsonify(error_response('Cannot determine branch. Please set branch_id in request.')[0]), 400

    # Get or create wallet
    wallet = get_or_create_wallet(branch_id)
    if not wallet:
        return jsonify(error_response('Could not create branch wallet')[0]), 500

    plan = MIS_PLANS[plan_tenure]
    total_amount = monthly_amount * plan['months']

    if float(wallet.current_balance or 0) < total_amount:
        available = float(wallet.current_balance or 0)
        return jsonify(error_response(
            f'CURRENT BALANCE LOW. Required: ₹{total_amount:,.0f}, Available: ₹{available:,.0f}. '
            f'Ask admin to top up the branch wallet first.'
        )[0]), 400

    investment_date = safe_date(data.get('investment_date')) or date.today()

    try:
        irn = generate_irn()
        investment = Investment(
            irn=irn,
            investor_id=investor_id,
            branch_id=branch_id,
            plan_type='MIS',
            plan_tenure=plan_tenure,
            investment_date=investment_date,
            monthly_amount=monthly_amount,
            plan_fee=float(data.get('plan_fee') or 0),
            payment_mode=data.get('payment_mode') or 'Cash',
            company_account=data.get('company_account') or None,
            adviser_code=member.adviser_code,
            approval_status='Pending'
        )
        investment.calculate_plan()
        db.session.add(investment)
        db.session.flush()

        for i in range(1, plan['months'] + 1):
            inst = Installment(
                investment_id=investment.id,
                investor_id=investor_id,
                installment_number=i,
                due_date=investment_date + relativedelta(months=i),
                amount=monthly_amount,
                status='Pending'
            )
            db.session.add(inst)

        db.session.commit()
        return jsonify(success_response(investment.to_dict(), 'Investment plan created, pending approval')[0]), 201

    except Exception as e:
        db.session.rollback()
        print("Plan create error:", traceback.format_exc())
        return jsonify(error_response(f'Failed to create plan: {str(e)}')[0]), 500


@investment_plan_bp.route('/approve/<int:investment_id>', methods=['POST'])
@jwt_required()
def approve_plan(investment_id):
    claims = get_jwt()
    if claims.get('role') not in ['branchmanager', 'superadmin']:
        return jsonify(error_response('Unauthorized', 403)[0]), 403

    identity = get_jwt_identity()
    data = request.get_json() or {}
    action = data.get('action')

    investment = Investment.query.get_or_404(investment_id)
    branch_id  = investment.branch_id

    try:
        if action == 'approve':
            investment.approval_status = 'Approved'
            investment.approved_by = int(identity)
            investment.approved_at = datetime.utcnow()

            if branch_id:
                wallet = get_or_create_wallet(branch_id)
                monthly = float(investment.monthly_amount or 0)
                wallet.current_balance = float(wallet.current_balance or 0) - monthly
                wallet.cash_wallet     = float(wallet.cash_wallet or 0) + monthly

                txn = WalletTransaction(
                    branch_id=branch_id,
                    transaction_type='Deduction',
                    amount=monthly,
                    description=f'Plan {investment.irn} approved',
                    reference_id=investment.irn,
                    balance_after=wallet.current_balance,
                    cash_wallet_after=wallet.cash_wallet,
                    created_by=int(identity)
                )
                db.session.add(txn)

                if float(wallet.current_balance) <= float(wallet.low_balance_threshold or 10000):
                    notif = Notification(
                        user_id=int(identity),
                        branch_id=branch_id,
                        title='⚠️ Low Balance Alert',
                        message=f'Balance ₹{float(wallet.current_balance):,.0f}. Request top-up.',
                        notification_type='Warning'
                    )
                    db.session.add(notif)

            adviser = Adviser.query.filter_by(adviser_code=investment.adviser_code).first()
            if adviser:
                _create_commission(investment, adviser)

            msg = f'Investment plan {investment.irn} approved'

        elif action == 'reject':
            investment.approval_status = 'Rejected'
            msg = f'Investment plan {investment.irn} rejected'
        else:
            return jsonify(error_response('action must be approve or reject')[0]), 400

        db.session.commit()
        return jsonify(success_response(investment.to_dict(), msg)[0]), 200

    except Exception as e:
        db.session.rollback()
        print("Approve error:", traceback.format_exc())
        return jsonify(error_response(f'Failed: {str(e)}')[0]), 500


@investment_plan_bp.route('/print/<irn>', methods=['GET'])
@jwt_required()
def print_irn(irn):
    investment = Investment.query.filter_by(irn=irn).first()
    if not investment:
        return jsonify(error_response('IRN not found', 404)[0]), 404
    member = Member.query.filter_by(investor_id=investment.investor_id).first()
    return jsonify(success_response({
        'irn': investment.irn,
        'investor': member.to_dict() if member else None,
        'investment': investment.to_dict(),
        'installments_paid': investment.installments_paid,
        'total_installments': investment.total_installments,
        'status_label': f'{investment.installments_paid} out of {investment.total_installments}'
    })[0]), 200


@investment_plan_bp.route('/list', methods=['GET'])
@jwt_required()
def list_plans():
    claims      = get_jwt()
    branch_id   = claims.get('branch_id')
    page        = request.args.get('page', 1, type=int)
    status      = request.args.get('status')
    investor_id = request.args.get('investor_id')

    query = Investment.query
    if branch_id and claims.get('role') == 'branchmanager':
        query = query.filter_by(branch_id=branch_id)
    if status:
        query = query.filter_by(approval_status=status)
    if investor_id:
        query = query.filter_by(investor_id=investor_id)

    paginated = query.order_by(Investment.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False)
    return jsonify(success_response({
        'items': [i.to_dict() for i in paginated.items],
        'total': paginated.total,
        'pages': paginated.pages,
        'current_page': paginated.page
    })[0]), 200