"""
investment_plan.py  — DefOex IntraTech Backend
Routes for: MIS Plan, SIS Plan, MIS Contribution, Approve Investment

Fixes & Features in this version:
  1. get-investor-details → accepts investor_id OR adviser_id
     AND accepts status == 'approved' OR 'active'
  2. Plan amount must be a multiple of ₹1,000 (min ₹1,000)
     [Old 10rs plan bug: FIXED — minimum is now ₹1,000]
  3. UPI payment: transaction_id (alphanumeric, max 35 chars) + upi_app
     stored when payment_mode == 'UPI'
  4. Cash payment: no extra fields required
  5. MIS/SIS/MIS-Contribution all share same UPI logic
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
import re

from extensions import db
from models.investment import Investment, Installment, MIS_PLANS, SIS_PLANS
from models.member import Member
from models.adviser import Adviser
from models.branch import Branch
from models.user import User
from utils.helpers import success_response, error_response, generate_irn
from utils.member_lookup import (
    resolve_member_from_code,
    link_adviser_investor,
    find_adviser_identity,
    find_member_for_adviser,
)

investment_plan_bp = Blueprint('investment_plan', __name__, url_prefix='/api/investment-plans')

# ─── Constants ───────────────────────────────────────────────────────────────
VALID_UPI_APPS = {'phonepe', 'paytm', 'gpay', 'googlepay', 'bhim', 'other'}
TRANSACTION_ID_RE = re.compile(r'^[A-Za-z0-9]{1,35}$')
MIN_PLAN_AMOUNT = Decimal('1000')

# ─── Helpers ─────────────────────────────────────────────────────────────────

def _validate_amount(amount_raw):
    """
    Validate that amount is a positive integer multiple of 1000.
    Returns (Decimal, None) on success or (None, error_str) on failure.
    """
    try:
        amount = Decimal(str(amount_raw))
        if amount <= 0:
            raise ValueError
    except (TypeError, ValueError, InvalidOperation):
        return None, 'Amount must be a positive number'

    if amount < MIN_PLAN_AMOUNT:
        return None, f'Minimum investment amount is ₹1,000'

    if amount % 1000 != 0:
        return None, 'Investment amount must be a multiple of ₹1,000 (e.g. ₹1,000 / ₹2,000 / ₹5,000)'

    return amount, None


def _validate_upi_fields(data: dict):
    """
    Validate UPI-specific fields when payment_mode is 'UPI'.
    Returns (transaction_id, upi_app, None) on success or (None, None, error_str).
    """
    transaction_id = (data.get('transaction_id') or '').strip()
    upi_app = (data.get('upi_app') or '').strip().lower()

    if not transaction_id:
        return None, None, 'Transaction ID is required for UPI payment'

    if not TRANSACTION_ID_RE.match(transaction_id):
        return None, None, (
            'Transaction ID must be alphanumeric (letters and digits only), '
            'maximum 35 characters'
        )

    if not upi_app:
        return None, None, 'UPI App is required (PhonePe / Paytm / GPay)'

    if upi_app not in VALID_UPI_APPS:
        return None, None, (
            f'Invalid UPI App "{upi_app}". '
            f'Allowed: PhonePe, Paytm, GPay, BHIM, Other'
        )

    return transaction_id, upi_app, None


def _get_member_by_any_id(member_id: str):
    """Look up approved Member by investor ID, adviser code (DFX-*), or login ID (DEFAD*)."""
    return resolve_member_from_code(member_id)


def _get_current_user():
    """Resolve logged-in user from JWT identity (stored as user id string)."""
    identity = get_jwt_identity()
    if identity is None:
        return None
    try:
        return User.query.get(int(identity))
    except (TypeError, ValueError):
        return User.query.filter_by(username=str(identity).strip()).first()


def _normalize_payment_mode(mode):
    """Map request payment mode to Investment enum value."""
    key = (mode or 'Cash').strip().upper()
    return {'CASH': 'Cash', 'UPI': 'UPI', 'NEFT': 'NEFT', 'CHEQUE': 'Cheque', 'DD': 'DD'}.get(key, 'Cash')


def _get_current_branch(member=None):
    """Get branch for the logged-in branch manager (or member's branch as fallback)."""
    claims = get_jwt() or {}
    user = _get_current_user()

    branch_id = None
    if user and user.branch_id:
        branch_id = user.branch_id
    elif claims.get('branch_id'):
        branch_id = claims.get('branch_id')
    elif member and member.branch_id:
        branch_id = member.branch_id

    if not branch_id:
        return None, 'Branch manager account not found'

    branch = Branch.query.get(int(branch_id))
    if not branch:
        return None, 'Branch not found'

    return branch, None


# ─── GET INVESTOR / ADVISER DETAILS ──────────────────────────────────────────

@investment_plan_bp.route('/get-investor-details', methods=['GET'])
@investment_plan_bp.route('/get-investor-details/<member_id>', methods=['GET'])
@jwt_required()
def get_investor_details(member_id=None):
    """
    Fetch member info for the MIS / SIS plan creation form.
    Accepts investor_id, adviser_code, or DEFAD login ID.
    Returns adviser-only profile when investor registration is still pending.

    Use ?member_id=DEFAD202608 so DEFAD IDs are not in the URL path (some
    browsers/ad blockers strip Authorization when the path contains "AD").
    """
    code = (
        member_id
        or request.args.get('member_id')
        or request.args.get('code')
        or ''
    ).strip().upper()
    if not code:
        return jsonify({'success': False, 'message': 'member_id is required'}), 400
    member, err = _get_member_by_any_id(code)

    if member:
        adviser_name = None
        if member.adviser_code:
            adviser = Adviser.query.filter(
                db.func.upper(Adviser.adviser_code) == member.adviser_code.strip().upper()
            ).first()
            if adviser:
                adviser_name = adviser.full_name

        data = {
            'investor_id':      member.investor_id,
            'adviser_id':       member.adviser_code,
            'full_name':        member.full_name,
            'father_name':      member.father_spouse_name,
            'mobile':           member.mobile,
            'adviser_name':     adviser_name,
            'nominee_name':     member.nominee_name,
            'nominee_relation': member.nominee_relationship,
            'status':           (member.approval_status or '').lower(),
            'can_create_plan':  True,
        }
        return jsonify({'success': True, 'data': data, 'message': 'Member details fetched'}), 200

    adviser, _user = find_adviser_identity(code)
    if adviser:
        pending = None
        if adviser.mobile:
            pending = Member.query.filter_by(
                mobile=adviser.mobile,
                approval_status='Pending',
            ).first()

        linked_member = find_member_for_adviser(adviser)

        if linked_member and (linked_member.approval_status or '').lower() != 'approved':
            pending = linked_member

        if pending:
            msg = (
                f'Investor registration for {adviser.full_name} ({pending.investor_id}) '
                f'is pending approval. Approve the member before creating a plan.'
            )
        else:
            msg = (
                f'{adviser.full_name} is registered as an adviser ({adviser.adviser_code}) '
                f'but has no approved investor profile. Register them as an investor first.'
            )

        data = {
            'investor_id':      getattr(adviser, 'investor_id', None) or '',
            'adviser_id':       adviser.adviser_code,
            'full_name':        adviser.full_name,
            'father_name':      getattr(adviser, 'father_name', None),
            'mobile':           adviser.mobile,
            'adviser_name':     adviser.full_name,
            'nominee_name':     None,
            'nominee_relation': None,
            'status':           'pending' if pending else 'adviser_only',
            'can_create_plan':  False,
            'pending_investor_id': pending.investor_id if pending else None,
        }
        return jsonify({'success': True, 'data': data, 'message': msg, 'can_create_plan': False}), 200

    return jsonify({'success': False, 'message': err or f'No record found for "{code}"'}), 400


# ─── CREATE MIS PLAN ─────────────────────────────────────────────────────────

@investment_plan_bp.route('/create-mis', methods=['POST'])
@jwt_required()
def create_mis_plan():
    """
    Create a new MIS Plan.

    JSON body:
      investor_id    : str   (investor_id or adviser_id)
      plan_tenure    : str   ('3Y', '5Y', '7Y')
      monthly_amount : int   (must be multiple of 1000, min 1000)
      payment_mode   : str   ('Cash' or 'UPI')
      transaction_id : str   (required if UPI, alphanumeric, max 35)
      upi_app        : str   (required if UPI: phonepe/paytm/gpay/bhim/other)
      investment_date: str   (YYYY-MM-DD, optional — defaults to today)
    """
    data = request.get_json(force=True) or {}

    # 1. Validate member
    member, err = _get_member_by_any_id(data.get('investor_id', ''))
    if err:
        return jsonify({'success': False, 'message': err}), 400

    # 2. Validate tenure
    plan_tenure = (data.get('plan_tenure') or '').strip().upper()
    if plan_tenure not in MIS_PLANS:
        return jsonify({'success': False,
                        'message': f'Invalid MIS tenure. Choose: {", ".join(MIS_PLANS.keys())}'}), 400

    # 3. Validate amount
    amount, err = _validate_amount(data.get('monthly_amount'))
    if err:
        return jsonify({'success': False, 'message': err}), 400

    # 4. Payment mode & UPI fields
    payment_mode = (data.get('payment_mode') or 'Cash').strip()
    transaction_id, upi_app = None, None

    if payment_mode.upper() == 'UPI':
        transaction_id, upi_app, err = _validate_upi_fields(data)
        if err:
            return jsonify({'success': False, 'message': err}), 400

    # 5. Investment date
    investment_date = date.today()
    if data.get('investment_date'):
        try:
            investment_date = datetime.strptime(data['investment_date'], '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'success': False, 'message': 'Invalid investment_date format (use YYYY-MM-DD)'}), 400

    # 6. Get branch
    branch, err = _get_current_branch(member)
    if err:
        return jsonify({'success': False, 'message': err}), 400

    try:
        plan_info = MIS_PLANS[plan_tenure]
        months = plan_info['months']
        total_investment = amount * months
        roi_num = plan_info['roi_num']
        roi_den = plan_info['roi_den']
        maturity = (total_investment * roi_num / roi_den).to_integral_value(rounding=ROUND_HALF_UP)
        maturity_date = investment_date + relativedelta(months=months)
        payment_mode_enum = _normalize_payment_mode(payment_mode)

        investment = Investment(
            irn                     = generate_irn(),
            investor_id             = member.investor_id,
            adviser_code            = member.adviser_code,
            branch_id               = branch.id,
            plan_type               = 'MIS',
            plan_tenure             = plan_tenure,
            plan_name               = plan_info['label'],
            monthly_amount          = float(amount),
            total_installments      = months,
            total_investment_amount = float(total_investment),
            total_maturity_amount   = float(maturity),
            roi_percentage          = float(plan_info['roi_pct']),
            investment_date         = investment_date,
            maturity_date           = maturity_date,
            due_date                = investment_date + relativedelta(months=1),
            payment_mode            = payment_mode_enum,
            approval_status         = 'Pending',
            status                  = 'Active',
        )
        db.session.add(investment)
        db.session.flush()

        inst = Installment(
            investment_id      = investment.id,
            investor_id        = member.investor_id,
            installment_number = 1,
            due_date           = investment_date,
            amount             = float(amount),
            payment_mode       = payment_mode_enum,
            status             = 'Pending',
        )
        db.session.add(inst)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'MIS Plan created successfully for {member.full_name}. Pending approval.',
            'data': {
                'investment_id':         investment.id,
                'plan_name':             investment.plan_name,
                'monthly_amount':        float(amount),
                'total_installments':    months,
                'total_investment':      float(total_investment),
                'maturity_amount':       float(maturity),
                'investment_date':       investment_date.isoformat(),
                'maturity_date':         maturity_date.isoformat(),
                'payment_mode':          payment_mode,
            }
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Failed to create MIS Plan: {str(e)}'}), 500


# ─── CREATE SIS PLAN ─────────────────────────────────────────────────────────

@investment_plan_bp.route('/create-sis', methods=['POST'])
@jwt_required()
def create_sis_plan():
    """
    Create a new SIS Plan (lump sum, 7.5 Year, amount doubles at maturity).

    JSON body:
      investor_id    : str
      lump_amount    : int   (must be multiple of 1000, min 1000)
      payment_mode   : str   ('Cash' or 'UPI')
      transaction_id : str   (required if UPI)
      upi_app        : str   (required if UPI)
      investment_date: str   (YYYY-MM-DD, optional)
    """
    data = request.get_json(force=True) or {}

    member, err = _get_member_by_any_id(data.get('investor_id', ''))
    if err:
        return jsonify({'success': False, 'message': err}), 400

    amount, err = _validate_amount(data.get('lump_amount'))
    if err:
        return jsonify({'success': False, 'message': err}), 400

    payment_mode = (data.get('payment_mode') or 'Cash').strip()
    transaction_id, upi_app = None, None
    if payment_mode.upper() == 'UPI':
        transaction_id, upi_app, err = _validate_upi_fields(data)
        if err:
            return jsonify({'success': False, 'message': err}), 400

    investment_date = date.today()
    if data.get('investment_date'):
        try:
            investment_date = datetime.strptime(data['investment_date'], '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'success': False, 'message': 'Invalid investment_date format'}), 400

    branch, err = _get_current_branch(member)
    if err:
        return jsonify({'success': False, 'message': err}), 400

    try:
        plan_info = SIS_PLANS.get('7.5Y') or SIS_PLANS.get('7Y')
        months = plan_info['months']
        maturity = amount * 2
        maturity_date = investment_date + relativedelta(months=months)
        payment_mode_enum = _normalize_payment_mode(payment_mode)

        investment = Investment(
            irn                     = generate_irn(),
            investor_id             = member.investor_id,
            adviser_code            = member.adviser_code,
            branch_id               = branch.id,
            plan_type               = 'SIS',
            plan_tenure             = '7Y',
            plan_name               = 'SIS 7.5 Year Plan',
            monthly_amount          = float(amount),
            total_installments      = 1,
            total_investment_amount = float(amount),
            total_maturity_amount   = float(maturity),
            roi_percentage          = 100.0,
            investment_date         = investment_date,
            maturity_date           = maturity_date,
            due_date                = investment_date + relativedelta(months=1),
            payment_mode            = payment_mode_enum,
            approval_status         = 'Pending',
            status                  = 'Active',
        )
        db.session.add(investment)
        db.session.flush()

        inst = Installment(
            investment_id      = investment.id,
            investor_id        = member.investor_id,
            installment_number = 1,
            due_date           = investment_date,
            amount             = float(amount),
            payment_mode       = payment_mode_enum,
            status             = 'Pending',
        )
        db.session.add(inst)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'SIS Plan created for {member.full_name}. Pending approval.',
            'data': {
                'investment_id':   investment.id,
                'plan_name':       investment.plan_name,
                'lump_amount':     float(amount),
                'maturity_amount': float(maturity),
                'investment_date': investment_date.isoformat(),
                'maturity_date':   maturity_date.isoformat(),
                'payment_mode':    payment_mode,
            }
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Failed to create SIS Plan: {str(e)}'}), 500


# ─── MIS CONTRIBUTION ────────────────────────────────────────────────────────

@investment_plan_bp.route('/mis-contribution', methods=['POST'])
@jwt_required()
def mis_contribution():
    """
    Record a monthly MIS contribution (installment payment).

    JSON body:
      investment_id  : int
      amount         : int   (must be multiple of 1000)
      payment_mode   : str   ('Cash' or 'UPI')
      transaction_id : str   (required if UPI)
      upi_app        : str   (required if UPI)
      payment_date   : str   (YYYY-MM-DD, optional)
    """
    data = request.get_json(force=True) or {}

    investment_id = data.get('investment_id')
    if not investment_id:
        return jsonify({'success': False, 'message': 'investment_id is required'}), 400

    investment = Investment.query.get(investment_id)
    if not investment:
        return jsonify({'success': False, 'message': 'Investment plan not found'}), 404

    if investment.approval_status != 'Approved':
        return jsonify({'success': False,
                        'message': 'Investment plan is not approved yet'}), 400

    amount, err = _validate_amount(data.get('amount'))
    if err:
        return jsonify({'success': False, 'message': err}), 400

    # Validate contribution matches plan monthly amount
    plan_monthly = Decimal(str(investment.monthly_amount))
    if amount != plan_monthly:
        return jsonify({
            'success': False,
            'message': f'Contribution amount must match plan monthly amount: ₹{int(plan_monthly):,}'
        }), 400

    payment_mode = (data.get('payment_mode') or 'Cash').strip()
    transaction_id, upi_app = None, None
    if payment_mode.upper() == 'UPI':
        transaction_id, upi_app, err = _validate_upi_fields(data)
        if err:
            return jsonify({'success': False, 'message': err}), 400

    payment_date = date.today()
    if data.get('payment_date'):
        try:
            payment_date = datetime.strptime(data['payment_date'], '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'success': False, 'message': 'Invalid payment_date format'}), 400

    try:
        # Count paid installments
        paid_count = Installment.query.filter_by(
            investment_id=investment_id,
            status='Paid'
        ).count()

        if paid_count >= investment.total_installments:
            return jsonify({'success': False,
                            'message': 'All installments have already been paid'}), 400

        next_inst_no = paid_count + 1

        inst = Installment(
            investment_id      = investment_id,
            investor_id        = investment.investor_id,
            installment_number = next_inst_no,
            due_date           = payment_date,
            paid_date          = payment_date,
            amount             = float(amount),
            payment_mode       = _normalize_payment_mode(payment_mode),
            status             = 'Paid',
        )
        db.session.add(inst)

        investment.installments_paid = next_inst_no

        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Installment #{next_inst_no} recorded successfully',
            'data': {
                'installment_no':   next_inst_no,
                'total_paid':       next_inst_no,
                'remaining':        investment.total_installments - next_inst_no,
                'payment_mode':     payment_mode,
            }
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Failed to record contribution: {str(e)}'}), 500


# ─── APPROVE / REJECT INVESTMENT ─────────────────────────────────────────────

@investment_plan_bp.route('/approve-investment/<int:investment_id>', methods=['POST'])
@jwt_required()
def approve_investment(investment_id):
    """
    Approve or reject a pending investment plan.

    JSON body:
      action  : str  ('approve' or 'reject')
      remarks : str  (optional)
    """
    data = request.get_json(force=True) or {}
    action = (data.get('action') or '').strip().lower()

    if action not in ('approve', 'reject'):
        return jsonify({'success': False, 'message': 'action must be "approve" or "reject"'}), 400

    investment = Investment.query.get(investment_id)
    if not investment:
        return jsonify({'success': False, 'message': 'Investment not found'}), 404

    if investment.approval_status != 'Pending':
        return jsonify({'success': False,
                        'message': f'Investment is already {investment.approval_status}'}), 400

    try:
        if action == 'approve':
            investment.approval_status = 'Approved'
            investment.approved_at = datetime.utcnow()
            msg = 'Investment plan approved successfully'
        else:
            investment.approval_status = 'Rejected'
            msg = 'Investment plan rejected'

        db.session.commit()
        return jsonify({'success': True, 'message': msg}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Action failed: {str(e)}'}), 500


# ─── LIST ALL INVESTMENTS ─────────────────────────────────────────────────────

@investment_plan_bp.route('/list', methods=['GET'])
@jwt_required()
def list_investments():
    """
    List investments for the current branch.
    Query params: page, per_page, plan_type, status
    """
    branch, err = _get_current_branch()
    if err:
        return jsonify({'success': False, 'message': err}), 400

    page     = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))
    plan_type = request.args.get('plan_type', '')
    status    = request.args.get('status', '')

    q = Investment.query.filter_by(branch_id=branch.id)
    if plan_type:
        q = q.filter_by(plan_type=plan_type.upper())
    if status:
        s = status.strip().lower()
        if s == 'pending':
            q = q.filter_by(approval_status='Pending')
        elif s == 'approved':
            q = q.filter_by(approval_status='Approved')
        elif s == 'rejected':
            q = q.filter_by(approval_status='Rejected')
        else:
            q = q.filter_by(status=status.title())

    q = q.order_by(Investment.created_at.desc())
    paginated = q.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'success': True,
        'data': [inv.to_dict() for inv in paginated.items],
        'total':    paginated.total,
        'page':     page,
        'per_page': per_page,
        'pages':    paginated.pages,
    }), 200