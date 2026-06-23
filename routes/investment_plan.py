from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from models.investment import Investment, Installment, MIS_PLANS, SIS_PLANS
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

    # Determine plan type (MIS or SIS)
    plan_type = str(data.get('plan_type', 'MIS')).upper()

    # Validate tenure and get plan definition
    if plan_type == 'SIS':
        if not plan_tenure:
            plan_tenure = '7.5Y'
        plan = SIS_PLANS.get(plan_tenure) or SIS_PLANS.get('7.5Y')
        if not plan:
            return jsonify(error_response('Invalid SIS plan tenure')[0]), 400
    else:
        plan_type = 'MIS'
        if not plan_tenure or plan_tenure not in MIS_PLANS:
            return jsonify(error_response('plan_tenure must be 3Y, 5Y, or 7Y')[0]), 400
        plan = MIS_PLANS[plan_tenure]

    try:
        monthly_amount = float(monthly_amount)
        if monthly_amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify(error_response('monthly_amount must be a positive number')[0]), 400

    # Validate investor — try exact match first, then fallback formats
    member = Member.query.filter_by(investor_id=investor_id, approval_status='Approved').first()

    # Try old format fallback: INV2026091192 → DFX-2026-091192 style
    if not member and not investor_id.startswith('DFX-'):
        # Try searching by mobile or partial match
        member = Member.query.filter(
            Member.investor_id.ilike(f'%{investor_id[-6:]}%'),
            Member.approval_status == 'Approved'
        ).first()

    if not member:
        # Show available investor IDs to help debug
        sample = [m.investor_id for m in Member.query.filter_by(approval_status='Approved').limit(5).all()]
        hint = f' Available IDs: {", ".join(sample)}' if sample else ' No approved investors found.'
        return jsonify(error_response(
            f'Investor "{investor_id}" not found or not yet approved.{hint}'
        )[0]), 404

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

    # SIS: monthly_amount IS the lump sum. MIS: monthly × months
    if plan_type == 'SIS':
        total_amount = monthly_amount  # lump sum upfront
    else:
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
    # Auto-fix commission_status_enum if it's still a PostgreSQL Enum type
    try:
        from sqlalchemy import text as _text
        with db.engine.connect() as _conn:
            _conn.execute(_text("ALTER TABLE commissions ALTER COLUMN status TYPE VARCHAR(20)"))
            _conn.execute(_text("DROP TYPE IF EXISTS commission_status_enum CASCADE"))
            _conn.commit()
    except Exception:
        pass  # Already VARCHAR — ignore
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
    if claims.get('role') == 'branchmanager' and branch_id:
        # BM strictly sees only their branch data
        # Exclude investments linked to company owner adviser
        from models.adviser import Adviser as AdvModel
        owner = AdvModel.query.filter_by(is_company_owner=True).first()
        owner_code = owner.adviser_code if owner else None
        query = query.filter_by(branch_id=branch_id)
        if owner_code:
            query = query.filter(Investment.adviser_code != owner_code)
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


@investment_plan_bp.route('/receipt/<irn>', methods=['GET'])
@jwt_required()
def get_receipt(irn):
    """Full receipt data for printing — Branch Manager and Superadmin only"""
    claims = get_jwt()
    role = claims.get('role')
    if role not in ['branchmanager', 'superadmin']:
        return jsonify(error_response('Only Branch Manager can print receipts', 403)[0]), 403

    investment = Investment.query.filter_by(irn=irn).first()
    if not investment:
        return jsonify(error_response('IRN not found', 404)[0]), 404

    member = Member.query.filter_by(investor_id=investment.investor_id).first()

    # Count actual paid installments from installments table
    from models.investment import Installment
    paid_count = Installment.query.filter_by(
        investment_id=investment.id,
        status='Paid'
    ).count()

    # Update investment record if count differs
    if investment.installments_paid != paid_count:
        investment.installments_paid = paid_count
        db.session.commit()

    # Get adviser info
    adviser = None
    if investment.adviser_code:
        adv = Adviser.query.filter_by(adviser_code=investment.adviser_code).first()
        if adv:
            adviser = adv.to_dict()

    total = investment.total_installments or 0
    paid  = paid_count
    remaining = total - paid

    return jsonify(success_response({
        'irn':              investment.irn,
        'investor':         member.to_dict() if member else None,
        'investment':       investment.to_dict(),
        'adviser':          adviser,
        'installments_paid': paid,
        'total_installments': total,
        'remaining_installments': remaining,
        'status_label':     f'Installment {paid} of {total}',
        'completion_pct':   round((paid / total * 100), 1) if total else 0,
        'printed_by_role':  role,
        'printed_at':       datetime.utcnow().isoformat(),
    })[0]), 200


@investment_plan_bp.route('/get-investor-details/<investor_id>', methods=['GET'])
@jwt_required()
def get_investor_details(investor_id):
    """
    Fetch investor details for MIS/SIS plan creation form.
    Returns: Investor ID, Name, Father Name, Mobile, Adviser ID, Adviser Name, Nominee Details
    """
    member = Member.query.filter_by(
        investor_id=investor_id,
        approval_status='Approved'
    ).first()
    if not member:
        return jsonify(error_response(
            f'Investor "{investor_id}" not found or not approved yet'
        , 404)[0]), 404

    adviser = None
    if member.adviser_code:
        from models.adviser import Adviser
        a = Adviser.query.filter_by(adviser_code=member.adviser_code).first()
        if a:
            adviser = {'adviser_code': a.adviser_code, 'full_name': a.full_name, 'rank_name': a.rank_name}

    return jsonify(success_response({
        'investor_id':    member.investor_id,
        'investor_name':  member.full_name,
        'father_name':    member.father_spouse_name,
        'mobile':         member.mobile,
        'adviser_id':     member.adviser_code,
        'adviser_name':   adviser['full_name'] if adviser else None,
        'adviser_rank':   adviser['rank_name'] if adviser else None,
        'nominee_name':   member.nominee_name,
        'nominee_relation': member.nominee_relationship,
        'nominee_age':    member.nominee_age,
        'city':           member.corr_city,
        'branch_id':      member.branch_id,
    })[0]), 200


@investment_plan_bp.route('/mis-contribution', methods=['GET'])
@jwt_required()
def mis_contribution_lookup():
    """
    MIS Contribution — Enter Investor ID → Get Details → Show investment status.
    Returns: investor info + all plans with installment status (1 of 36, etc.)
    """
    investor_id = request.args.get('investor_id', '').strip()
    if not investor_id:
        return jsonify(error_response('investor_id required')[0]), 400

    member = Member.query.filter_by(investor_id=investor_id, approval_status='Approved').first()
    if not member:
        return jsonify(error_response(f'Investor "{investor_id}" not found or not approved')[0]), 404

    plans = Investment.query.filter_by(
        investor_id=investor_id, approval_status='Approved'
    ).all()

    from models.investment import Installment
    from datetime import date

    plan_list = []
    for p in plans:
        paid    = Installment.query.filter_by(investment_id=p.id, status='Paid').count()
        pending = Installment.query.filter_by(investment_id=p.id, status='Pending').first()
        total   = p.total_installments or 0

        # Check if due date exceeded
        is_overdue  = pending and pending.due_date and pending.due_date < date.today()
        penalty_amt = 15  # ₹15 penalty if overdue
        base_amount = float(p.monthly_amount or 0)
        payable_amt = base_amount + penalty_amt if is_overdue else base_amount

        plan_list.append({
            **p.to_dict(),
            'installments_paid':    paid,
            'total_installments':   total,
            'status_label':         f'{paid} of {total}',
            'next_due_date':        pending.due_date.isoformat() if pending and pending.due_date else None,
            'is_overdue':           is_overdue,
            'base_amount':          base_amount,
            'penalty_amount':       penalty_amt if is_overdue else 0,
            'payable_amount':       payable_amt,
            'payable_display':      f'\u20b9{payable_amt:,.0f}' + (f' (\u20b9{base_amount:,.0f} + \u20b9{penalty_amt} penalty)' if is_overdue else ''),
        })

    return jsonify(success_response({
        'investor': {
            'investor_id':   member.investor_id,
            'investor_name': member.full_name,
            'father_name':   member.father_spouse_name,
            'mobile':        member.mobile,
            'adviser_id':    member.adviser_code,
            'nominee_name':  member.nominee_name,
            'nominee_relation': member.nominee_relationship,
        },
        'plans': plan_list,
    })[0]), 200


@investment_plan_bp.route('/pay-installment/<int:investment_id>', methods=['POST'])
@jwt_required()
def pay_installment(investment_id):
    """
    Pay next installment for a plan.
    Checks if overdue → adds ₹15 penalty.
    After payment → go to Approve Investment Tab.
    """
    from models.investment import Installment
    from datetime import date, datetime

    claims    = get_jwt()
    identity  = get_jwt_identity()
    investment = Investment.query.get_or_404(investment_id)

    # Get next pending installment
    installment = Installment.query.filter_by(
        investment_id=investment_id, status='Pending'
    ).order_by(Installment.installment_number).first()

    if not installment:
        return jsonify(error_response('No pending installments for this plan')[0]), 400

    data        = request.get_json() or {}
    is_overdue  = installment.due_date and installment.due_date < date.today()
    penalty     = 15 if is_overdue else 0
    amount_paid = float(installment.amount or 0) + penalty

    try:
        installment.status    = 'Paid'
        installment.paid_date = date.today()

        paid_count = Installment.query.filter_by(
            investment_id=investment_id, status='Paid').count()
        investment.installments_paid = paid_count

        db.session.commit()

        return jsonify(success_response({
            'installment_number': installment.installment_number,
            'total_installments': investment.total_installments,
            'amount_paid':        amount_paid,
            'base_amount':        float(installment.amount or 0),
            'penalty':            penalty,
            'is_overdue':         is_overdue,
            'installments_paid':  paid_count,
            'status_label':       f'{paid_count} of {investment.total_installments}',
            'message':            f'Payment successful! Go to Approve Investment Tab.',
        }, f'Installment {installment.installment_number} paid — ₹{amount_paid:,.0f}')[0]), 200

    except Exception as e:
        db.session.rollback()
        print(traceback.format_exc())
        return jsonify(error_response(str(e))[0]), 500


@investment_plan_bp.route('/by-irn/<irn>', methods=['GET'])
@jwt_required()
def get_by_irn(irn):
    """MIS Contribution — Enter Investment ID (IRN) → Fetch full details"""
    inv = Investment.query.filter_by(irn=irn).first()
    if not inv:
        return jsonify(error_response(f'Investment "{irn}" not found', 404)[0]), 404

    member  = Member.query.filter_by(investor_id=inv.investor_id).first()
    from models.investment import Installment
    from datetime import date

    paid    = Installment.query.filter_by(investment_id=inv.id, status='Paid').count()
    pending = Installment.query.filter_by(investment_id=inv.id, status='Pending')                .order_by(Installment.installment_number).first()

    is_overdue  = pending and pending.due_date and pending.due_date < date.today()
    base        = float(inv.monthly_amount or 0)
    penalty     = 15 if is_overdue else 0
    payable     = base + penalty

    return jsonify(success_response({
        'investment': {
            **inv.to_dict(),
            'installments_paid':  paid,
            'status_label':       f'{paid} of {inv.total_installments}',
            'next_due_date':      pending.due_date.isoformat() if pending and pending.due_date else None,
            'is_overdue':         bool(is_overdue),
            'base_amount':        base,
            'penalty_amount':     penalty,
            'payable_amount':     payable,
        },
        'investor': {
            'investor_id':       member.investor_id if member else inv.investor_id,
            'investor_name':     member.full_name if member else None,
            'father_name':       member.father_spouse_name if member else None,
            'mobile':            member.mobile if member else None,
            'adviser_id':        member.adviser_code if member else inv.adviser_code,
            'nominee_name':      member.nominee_name if member else None,
            'nominee_relation':  member.nominee_relationship if member else None,
        }
    })[0]), 200