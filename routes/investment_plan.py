"""
investment_plan.py  — DefOex IntraTech Backend
Routes for: MIS Plan, SIS Plan, MIS Contribution, Approve Investment

Fixes & Features in this version:
  1. get-investor-details → accepts investor_id OR adviser_id
     AND accepts status == 'approved' OR 'active'
  2. MIS monthly amount: official chart ₹100–₹30,000 per month
  3. SIS lump sum must be ₹5,000–₹10,00,000 (multiple of ₹1,000); maturity doubles
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
from models.investment import (
    Investment, Installment, MIS_PLANS, MIS_AMOUNTS, MIS_MIN_AMOUNT, MIS_MAX_AMOUNT,
    SIS_PLANS, SIS_REF, mis_rate_chart, sis_rate_chart, SIS_AMOUNTS,
    investment_progress,
)
from models.commission import Commission
from models.member import Member
from models.adviser import Adviser
from models.branch import Branch
from models.branch_wallet import BranchWallet
from models.user import User
from utils.helpers import success_response, error_response, generate_investment_plan_id
from utils.datetime_utils import now_ist, today_ist, isoformat_ist
from utils.role_scoping import sanitize_response, current_role, should_hide_branch
from utils.member_lookup import (
    resolve_member_from_code,
    link_adviser_investor,
    find_adviser_identity,
    find_member_for_adviser,
)
from utils.branch_wallet_ops import deduct_branch_wallet, refund_branch_wallet
from utils.commission_processor import process_investment_commissions

investment_plan_bp = Blueprint('investment_plan', __name__, url_prefix='/api/investment-plans')

# ─── Constants ───────────────────────────────────────────────────────────────
VALID_UPI_APPS = {'phonepe', 'paytm', 'gpay', 'googlepay', 'bhim', 'other'}
TRANSACTION_ID_RE = re.compile(r'^[A-Za-z0-9]{1,35}$')
MIN_SIS_AMOUNT = Decimal('5000')
MAX_SIS_AMOUNT = Decimal('1000000')
MIS_AMOUNT_SET = {Decimal(str(a)) for a in MIS_AMOUNTS}

# ─── Helpers ─────────────────────────────────────────────────────────────────

def _validate_mis_amount(amount_raw):
    """
    Validate MIS monthly amount against official rate chart.
    Returns (Decimal, None) on success or (None, error_str) on failure.
    """
    try:
        amount = Decimal(str(amount_raw))
        if amount <= 0:
            raise ValueError
        if amount != int(amount):
            raise ValueError
    except (TypeError, ValueError, InvalidOperation):
        return None, 'Amount must be a positive whole number'

    if amount not in MIS_AMOUNT_SET:
        allowed = ', '.join(f'₹{int(a):,}' for a in MIS_AMOUNTS)
        return None, f'Invalid MIS amount. Choose from official chart: {allowed}'

    return amount, None


def _validate_sis_amount(amount_raw):
    """
    Validate SIS lump-sum amount (₹5,000–₹10,00,000, multiples of ₹1,000).
    Returns (Decimal, None) on success or (None, error_str) on failure.
    """
    try:
        amount = Decimal(str(amount_raw))
        if amount <= 0:
            raise ValueError
        if amount != int(amount):
            raise ValueError
    except (TypeError, ValueError, InvalidOperation):
        return None, 'Amount must be a positive whole number'

    if amount < MIN_SIS_AMOUNT:
        return None, 'Minimum SIS investment amount is ₹5,000'

    if amount > MAX_SIS_AMOUNT:
        return None, 'Maximum SIS investment amount is ₹10,00,000'

    if amount % 1000 != 0:
        return None, 'SIS amount must be a multiple of ₹1,000 (e.g. ₹5,000 / ₹10,000)'

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


PLAN_ADMIN_ROLES = frozenset({'superadmin', 'branchmanager'})


def _require_plan_admin():
    """Only branch manager / superadmin may create plans, contribute, or approve."""
    if current_role() not in PLAN_ADMIN_ROLES:
        return jsonify({
            'success': False,
            'message': 'Unauthorized — only branch manager or admin can perform this action',
        }), 403
    return None


def _require_superadmin():
    """Only superadmin may CRUD investment plans (view, update, delete)."""
    if current_role() != 'superadmin':
        return jsonify({
            'success': False,
            'message': 'Unauthorized — only admin can manage investment plans',
        }), 403
    return None


def _investment_detail(investment):
    """Full plan payload for admin read/update."""
    items = _enrich_investment_items([investment])
    detail = items[0] if items else investment.to_dict()

    member = Member.query.filter_by(investor_id=investment.investor_id).first()
    if member:
        detail['investor_name'] = member.full_name
        detail['investor_mobile'] = member.mobile

    detail['installments'] = [
        i.to_dict() for i in Installment.query.filter_by(investment_id=investment.id)
        .order_by(Installment.installment_number).all()
    ]
    return detail


def _recalculate_mis_plan(investment, amount, tenure, investment_date=None):
    plan_info = MIS_PLANS[tenure]
    months = plan_info['months']
    total_investment = amount * months
    maturity = (total_investment * plan_info['roi_num'] / plan_info['roi_den']).to_integral_value(
        rounding=ROUND_HALF_UP
    )
    inv_date = investment_date or investment.investment_date or today_ist()

    investment.plan_tenure = tenure
    investment.plan_type = 'MIS'
    investment.monthly_amount = float(amount)
    investment.total_installments = months
    investment.total_investment_amount = float(total_investment)
    investment.total_maturity_amount = float(maturity)
    investment.roi_percentage = float(plan_info['roi_pct'])
    investment.plan_name = plan_info['label']
    investment.investment_date = inv_date
    investment.maturity_date = inv_date + relativedelta(months=months)
    investment.due_date = inv_date + relativedelta(months=1)


def _recalculate_sis_plan(investment, amount, investment_date=None):
    inv_date = investment_date or investment.investment_date or today_ist()
    maturity = (amount * 2).to_integral_value(rounding=ROUND_HALF_UP)

    investment.plan_type = 'SIS'
    investment.plan_tenure = '7Y'
    investment.monthly_amount = float(amount)
    investment.total_installments = 1
    investment.total_investment_amount = float(amount)
    investment.total_maturity_amount = float(maturity)
    investment.roi_percentage = Decimal('100.00')
    investment.plan_name = SIS_PLANS['7.5Y']['label']
    investment.investment_date = inv_date
    investment.maturity_date = inv_date + relativedelta(months=90)
    investment.due_date = inv_date


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


def _investor_id_for_user(user):
    """Resolve investor_id for a member-role login user."""
    if not user:
        return None
    uname = (user.username or '').strip().upper()
    if uname:
        member = Member.query.filter(
            db.func.upper(Member.investor_id) == uname
        ).first()
        if member:
            return member.investor_id
    if user.mobile:
        from utils.helpers import find_member_by_mobile
        member = find_member_by_mobile(user.mobile)
        if member:
            return member.investor_id
    return None


def _enrich_investment_items(investments):
    """Attach branch name and wallet balance for each investment (approval UI)."""
    branch_ids = {inv.branch_id for inv in investments if inv.branch_id}
    if not branch_ids:
        return [inv.to_dict() for inv in investments]

    branches = {
        b.id: b for b in Branch.query.filter(Branch.id.in_(branch_ids)).all()
    }
    wallets = {
        w.branch_id: w
        for w in BranchWallet.query.filter(BranchWallet.branch_id.in_(branch_ids)).all()
    }

    items = []
    for inv in investments:
        d = inv.to_dict()
        branch = branches.get(inv.branch_id)
        wallet = wallets.get(inv.branch_id)
        d['branch_name'] = branch.branch_name if branch else None
        d['branch_code'] = branch.branch_code if branch else None
        d['branch_current_balance'] = float(wallet.current_balance or 0) if wallet else 0
        items.append(d)
    return items


def _deduct_investment_payment(investment, amount, created_by=None, note=''):
    """Deduct plan payment from branch current balance → add to cash wallet."""
    desc = (
        f'{investment.plan_type} plan — {investment.investor_id} '
        f'({investment.irn}){note}'
    )
    return deduct_branch_wallet(
        investment.branch_id,
        amount,
        desc,
        reference_id=f'INVEST-{investment.id}',
        created_by=created_by,
    )


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
    denied = _require_plan_admin()
    if denied:
        return denied
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


# ─── MIS RATE CHART ──────────────────────────────────────────────────────────

@investment_plan_bp.route('/mis-chart', methods=['GET'])
@jwt_required()
def get_mis_chart():
    """Return official MIS rate chart (monthly amounts × 3Y/5Y/7Y projections)."""
    return jsonify({
        'success': True,
        'data': {
            'plans': MIS_PLANS,
            'amounts': MIS_AMOUNTS,
            'min_amount': MIS_MIN_AMOUNT,
            'max_amount': MIS_MAX_AMOUNT,
            'rows': mis_rate_chart(),
        },
    }), 200


@investment_plan_bp.route('/sis-chart', methods=['GET'])
@jwt_required()
def get_sis_chart():
    """Return official SIS 7.5Y rate chart (lump sum → double at maturity)."""
    return jsonify({
        'success': True,
        'data': {
            'plan': SIS_PLANS['7.5Y'],
            'amounts': SIS_AMOUNTS,
            'rows': sis_rate_chart(),
        },
    }), 200


# ─── CREATE (unified) ────────────────────────────────────────────────────────

@investment_plan_bp.route('/create', methods=['POST'])
@jwt_required()
def create_plan():
    """Create MIS or SIS plan based on plan_type in JSON body."""
    data = request.get_json(force=True) or {}
    plan_type = (data.get('plan_type') or 'MIS').strip().upper()
    if plan_type == 'SIS':
        if data.get('monthly_amount') and not data.get('lump_amount'):
            data = {**data, 'lump_amount': data['monthly_amount']}
        return _do_create_sis(data)
    return _do_create_mis(data)


# ─── CREATE MIS PLAN ─────────────────────────────────────────────────────────

def _do_create_mis(data):
    """
    Create a new MIS Plan.

    JSON body:
      investor_id    : str   (investor_id or adviser_id)
      plan_tenure    : str   ('3Y', '5Y', '7Y')
      monthly_amount : int   (official MIS chart amount: 100, 200, 500, ... 30000)
      payment_mode   : str   ('Cash' or 'UPI')
      transaction_id : str   (required if UPI, alphanumeric, max 35)
      upi_app        : str   (required if UPI: phonepe/paytm/gpay/bhim/other)
      investment_date: str   (YYYY-MM-DD, optional — defaults to today)
    """
    denied = _require_plan_admin()
    if denied:
        return denied

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
    amount, err = _validate_mis_amount(data.get('monthly_amount'))
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
    investment_date = today_ist()
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
            irn                     = generate_investment_plan_id(branch.id, 'MIS'),
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
            'message': (
                f'MIS Plan created for {member.full_name}. '
                f'Awaiting branch manager approval.'
            ),
            'data': {
                'investment_id':         investment.id,
                'irn':                   investment.irn,
                'plan_id':               investment.irn,
                'plan_name':             investment.plan_name,
                'monthly_amount':        float(amount),
                'total_installments':    months,
                'total_investment':      float(total_investment),
                'maturity_amount':       float(maturity),
                'investment_date':       investment_date.isoformat(),
                'maturity_date':         maturity_date.isoformat(),
                'payment_mode':          payment_mode,
                'approval_status':       'Pending',
            }
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Failed to create MIS Plan: {str(e)}'}), 500


@investment_plan_bp.route('/create-mis', methods=['POST'])
@jwt_required()
def create_mis_plan():
    return _do_create_mis(request.get_json(force=True) or {})


# ─── CREATE SIS PLAN ─────────────────────────────────────────────────────────

def _do_create_sis(data):
    """
    Create a new SIS Plan (lump sum, 7.5 Year, amount doubles at maturity).

    JSON body:
      investor_id    : str
      lump_amount    : int   (₹5,000–₹10,00,000, multiple of ₹1,000)
      payment_mode   : str   ('Cash' or 'UPI')
      transaction_id : str   (required if UPI)
      upi_app        : str   (required if UPI)
      investment_date: str   (YYYY-MM-DD, optional)
    """
    denied = _require_plan_admin()
    if denied:
        return denied

    member, err = _get_member_by_any_id(data.get('investor_id', ''))
    if err:
        return jsonify({'success': False, 'message': err}), 400

    amount, err = _validate_sis_amount(data.get('lump_amount'))
    if err:
        return jsonify({'success': False, 'message': err}), 400

    payment_mode = (data.get('payment_mode') or 'Cash').strip()
    transaction_id, upi_app = None, None
    if payment_mode.upper() == 'UPI':
        transaction_id, upi_app, err = _validate_upi_fields(data)
        if err:
            return jsonify({'success': False, 'message': err}), 400

    investment_date = today_ist()
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
            irn                     = generate_investment_plan_id(branch.id, 'SIS'),
            investor_id             = member.investor_id,
            adviser_code            = member.adviser_code,
            branch_id               = branch.id,
            plan_type               = 'SIS',
            plan_tenure             = '7Y',
            plan_name               = plan_info['label'],
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
            'message': (
                f'SIS Plan created for {member.full_name}. '
                f'Awaiting branch manager approval.'
            ),
            'data': {
                'investment_id':   investment.id,
                'irn':             investment.irn,
                'plan_id':         investment.irn,
                'plan_name':       investment.plan_name,
                'lump_amount':     float(amount),
                'maturity_amount': float(maturity),
                'investment_date': investment_date.isoformat(),
                'maturity_date':   maturity_date.isoformat(),
                'payment_mode':    payment_mode,
                'approval_status': 'Pending',
            }
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Failed to create SIS Plan: {str(e)}'}), 500


@investment_plan_bp.route('/create-sis', methods=['POST'])
@jwt_required()
def create_sis_plan():
    return _do_create_sis(request.get_json(force=True) or {})


# ─── MIS CONTRIBUTION ────────────────────────────────────────────────────────

def _enrich_contribution_plan(investment):
    """Build MIS contribution card payload with TRI and SMI status."""
    d = investment.to_dict()
    monthly = float(investment.monthly_amount or 0)
    paid = investment.installments_paid or 0
    total = investment.total_installments or 0
    tri = d.get('tri', 0)
    due = investment.due_date
    today = today_ist()
    is_overdue = bool(due and today > due and paid < total)
    penalty_amount = 50 if is_overdue else 0
    base_amount = monthly
    payable_amount = base_amount + penalty_amount

    d.update({
        'status_label': d.get('status_label') or f'{paid} of {total}',
        'tri': tri,
        'total_received_investment': tri,
        'next_due_date': due.isoformat() if due else None,
        'is_overdue': is_overdue,
        'base_amount': base_amount,
        'penalty_amount': penalty_amount,
        'payable_amount': payable_amount,
    })
    return d


@investment_plan_bp.route('/mis-contribution', methods=['GET'])
@jwt_required()
def get_mis_contribution():
    """Fetch approved MIS plans for an investor (TRI + SMI status)."""
    denied = _require_plan_admin()
    if denied:
        return denied

    investor_id = (request.args.get('investor_id') or '').strip()
    if not investor_id:
        return jsonify({'success': False, 'message': 'investor_id is required'}), 400

    member, err = _get_member_by_any_id(investor_id)
    if err:
        return jsonify({'success': False, 'message': err}), 400

    plans = Investment.query.filter_by(
        investor_id=member.investor_id,
        approval_status='Approved',
        plan_type='MIS',
    ).filter(Investment.status.in_(['Active', 'Completed'])).all()

    return jsonify({
        'success': True,
        'data': {
            'investor': {
                'investor_id': member.investor_id,
                'investor_name': member.full_name,
                'father_name': member.father_spouse_name,
                'mobile': member.mobile,
                'adviser_id': member.adviser_code,
                'nominee_name': member.nominee_name,
            },
            'plans': [_enrich_contribution_plan(p) for p in plans],
        },
    }), 200


@investment_plan_bp.route('/pay-installment/<int:investment_id>', methods=['POST'])
@jwt_required()
def pay_installment(investment_id):
    """Pay next MIS installment (Schedule Monthly Investment / SMI)."""
    denied = _require_plan_admin()
    if denied:
        return denied

    investment = Investment.query.get(investment_id)
    if not investment:
        return jsonify({'success': False, 'message': 'Investment plan not found'}), 404

    if investment.approval_status != 'Approved':
        return jsonify({'success': False, 'message': 'Investment plan is not approved yet'}), 400

    if investment.plan_type != 'MIS':
        return jsonify({'success': False, 'message': 'Only MIS plans support monthly installments'}), 400

    amount = Decimal(str(investment.monthly_amount))
    today = today_ist()
    due = investment.due_date
    is_overdue = bool(due and today > due and (investment.installments_paid or 0) < (investment.total_installments or 0))
    penalty = Decimal('50') if is_overdue else Decimal('0')
    payable = amount + penalty

    paid_count = Installment.query.filter_by(investment_id=investment_id, status='Paid').count()
    if paid_count >= (investment.total_installments or 0):
        return jsonify({'success': False, 'message': 'All installments have already been paid'}), 400

    next_inst_no = paid_count + 1

    try:
        inst = Installment(
            investment_id=investment_id,
            investor_id=investment.investor_id,
            installment_number=next_inst_no,
            due_date=today,
            paid_date=today,
            amount=float(payable),
            payment_mode=investment.payment_mode or 'Cash',
            status='Paid',
        )
        db.session.add(inst)
        investment.installments_paid = next_inst_no
        investment.due_date = today + relativedelta(months=1)

        identity = get_jwt_identity()
        wallet_result, wallet_err = deduct_branch_wallet(
            investment.branch_id,
            float(payable),
            f'MIS installment #{next_inst_no} — {investment.investor_id} ({investment.irn})',
            reference_id=f'INSTALL-{investment_id}-{next_inst_no}',
            created_by=identity,
        )
        if wallet_err:
            db.session.rollback()
            return jsonify({'success': False, 'message': wallet_err}), 400

        db.session.commit()

        _, total, tri, status_label = investment_progress(
            investment.plan_type,
            investment.installments_paid,
            investment.total_installments,
            investment.monthly_amount,
        )

        return jsonify({
            'success': True,
            'message': f'Installment #{next_inst_no} paid successfully',
            'data': {
                'installment_no': next_inst_no,
                'amount_paid': float(payable),
                'base_amount': float(amount),
                'penalty': float(penalty),
                'is_overdue': is_overdue,
                'tri': tri,
                'total_received_investment': tri,
                'status_label': status_label,
                'installments_paid': investment.installments_paid,
                'total_installments': investment.total_installments,
                'wallet': wallet_result,
            },
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Payment failed: {str(e)}'}), 500


@investment_plan_bp.route('/mis-contribution', methods=['POST'])
@jwt_required()
def mis_contribution():
    """
    Record a monthly MIS contribution (installment payment).

    JSON body:
      investment_id  : int
      amount         : int   (must match plan monthly amount)
      payment_mode   : str   ('Cash' or 'UPI')
      transaction_id : str   (required if UPI)
      upi_app        : str   (required if UPI)
      payment_date   : str   (YYYY-MM-DD, optional)
    """
    denied = _require_plan_admin()
    if denied:
        return denied
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

    try:
        amount = Decimal(str(data.get('amount')))
        if amount <= 0:
            raise ValueError
    except (TypeError, ValueError, InvalidOperation):
        return jsonify({'success': False, 'message': 'Amount must be a positive number'}), 400

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

    payment_date = today_ist()
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

        identity = get_jwt_identity()
        wallet_result, wallet_err = deduct_branch_wallet(
            investment.branch_id,
            float(amount),
            f'MIS installment #{next_inst_no} — {investment.investor_id} ({investment.irn})',
            reference_id=f'INSTALL-{investment_id}-{next_inst_no}',
            created_by=identity,
        )
        if wallet_err:
            db.session.rollback()
            return jsonify({'success': False, 'message': wallet_err}), 400

        db.session.commit()

        _, total, tri, status_label = investment_progress(
            investment.plan_type,
            investment.installments_paid,
            investment.total_installments,
            investment.monthly_amount,
        )

        return jsonify({
            'success': True,
            'message': (
                f'Installment #{next_inst_no} recorded. '
                f'₹{float(amount):,.0f} deducted from branch current balance → cash wallet.'
            ),
            'data': {
                'installment_no':   next_inst_no,
                'total_paid':       next_inst_no,
                'remaining':        investment.total_installments - next_inst_no,
                'payment_mode':     payment_mode,
                'amount_paid':      float(amount),
                'tri':              tri,
                'total_received_investment': tri,
                'status_label':     status_label,
                'wallet':           wallet_result,
            }
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Failed to record contribution: {str(e)}'}), 500


# ─── APPROVE / REJECT INVESTMENT ─────────────────────────────────────────────

@investment_plan_bp.route('/approve/<int:investment_id>', methods=['POST'])
@investment_plan_bp.route('/approve-investment/<int:investment_id>', methods=['POST'])
@jwt_required()
def approve_investment(investment_id):
    """
    Approve or reject a pending investment plan.

    On approve: deduct plan amount from branch current balance → cash wallet (if not
    already deducted at create time), then mark approved.
    """
    denied = _require_plan_admin()
    if denied:
        return denied
    data = request.get_json(force=True) or {}
    action = (data.get('action') or '').strip().lower()
    identity = get_jwt_identity()

    if action not in ('approve', 'reject'):
        return jsonify({'success': False, 'message': 'action must be "approve" or "reject"'}), 400

    investment = Investment.query.get(investment_id)
    if not investment:
        return jsonify({'success': False, 'message': 'Investment not found'}), 404

    role = (get_jwt() or {}).get('role', '').lower()
    if role == 'branchmanager':
        branch, err = _get_current_branch()
        if err:
            return jsonify({'success': False, 'message': err}), 400
        if investment.branch_id != branch.id:
            return jsonify({'success': False, 'message': 'Investment not in your branch'}), 403

    if investment.approval_status != 'Pending':
        return jsonify({'success': False,
                        'message': f'Investment is already {investment.approval_status}'}), 400

    try:
        wallet_result = None
        if action == 'approve':
            deduct_amount = float(investment.monthly_amount or 0)
            wallet_result, wallet_err = _deduct_investment_payment(
                investment, deduct_amount, created_by=identity, note=' — approval'
            )
            if wallet_err:
                db.session.rollback()
                return jsonify({'success': False, 'message': wallet_err}), 400

            investment.approval_status = 'Approved'
            investment.status = 'Active'
            investment.approved_at = now_ist()
            try:
                investment.approved_by = int(identity)
            except (TypeError, ValueError):
                pass

            first_inst = Installment.query.filter_by(
                investment_id=investment.id, installment_number=1
            ).first()
            if first_inst:
                first_inst.status = 'Paid'
                first_inst.paid_date = today_ist()
            investment.installments_paid = 1
            if investment.plan_type == 'MIS':
                investment.due_date = today_ist() + relativedelta(months=1)
            elif first_inst:
                investment.due_date = investment.maturity_date

            commissions = process_investment_commissions(investment)

            msg = (
                f'Investment plan approved. '
                f'₹{deduct_amount:,.0f} deducted from branch current balance → cash wallet.'
            )
            if commissions:
                msg += f' {len(commissions)} benefit record(s) created.'
        else:
            deduct_amount = float(investment.monthly_amount or 0)
            wallet_result, wallet_err = refund_branch_wallet(
                investment.branch_id,
                deduct_amount,
                (
                    f'{investment.plan_type} plan rejected — {investment.investor_id} '
                    f'({investment.irn})'
                ),
                reference_id=f'INVEST-{investment.id}',
                created_by=identity,
            )
            if wallet_err:
                db.session.rollback()
                return jsonify({'success': False, 'message': wallet_err}), 400

            investment.approval_status = 'Rejected'
            investment.status = 'Cancelled'
            msg = 'Investment plan rejected'

        db.session.commit()
        resp = {'success': True, 'message': msg}
        if wallet_result:
            resp['wallet'] = wallet_result
        if action == 'approve':
            db.session.refresh(investment)
            resp['data'] = investment.to_dict()
        return jsonify(resp), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Action failed: {str(e)}'}), 500


@investment_plan_bp.route('/<int:investment_id>', methods=['GET'])
@jwt_required()
def get_investment(investment_id):
    """Super Admin only — fetch a single investment plan with full details."""
    denied = _require_superadmin()
    if denied:
        return denied

    investment = Investment.query.get(investment_id)
    if not investment:
        return jsonify({'success': False, 'message': 'Investment not found'}), 404

    return jsonify({'success': True, 'data': _investment_detail(investment)}), 200


@investment_plan_bp.route('/<int:investment_id>', methods=['PUT'])
@jwt_required()
def update_investment(investment_id):
    """Super Admin only — update an investment plan."""
    denied = _require_superadmin()
    if denied:
        return denied

    investment = Investment.query.get(investment_id)
    if not investment:
        return jsonify({'success': False, 'message': 'Investment not found'}), 404

    data = request.get_json() or {}
    is_pending = (investment.approval_status or '') == 'Pending'

    try:
        investment_date = None
        if data.get('investment_date'):
            try:
                investment_date = datetime.strptime(data['investment_date'], '%Y-%m-%d').date()
            except ValueError:
                return jsonify({'success': False, 'message': 'Invalid investment_date (YYYY-MM-DD)'}), 400

        if is_pending and ('monthly_amount' in data or 'plan_tenure' in data):
            plan_type = (investment.plan_type or 'MIS').upper()
            if plan_type == 'SIS':
                amount, err = _validate_sis_amount(
                    data.get('monthly_amount', investment.monthly_amount)
                )
                if err:
                    return jsonify({'success': False, 'message': err}), 400
                _recalculate_sis_plan(investment, amount, investment_date)
            else:
                tenure = (data.get('plan_tenure') or investment.plan_tenure or '3Y').strip().upper()
                if tenure not in MIS_PLANS:
                    return jsonify({'success': False, 'message': 'Invalid MIS tenure'}), 400
                amount, err = _validate_mis_amount(
                    data.get('monthly_amount', investment.monthly_amount)
                )
                if err:
                    return jsonify({'success': False, 'message': err}), 400
                _recalculate_mis_plan(investment, amount, tenure, investment_date)
        elif investment_date:
            investment.investment_date = investment_date
            if investment.maturity_date and investment.investment_date:
                months = investment.total_installments or 36
                investment.maturity_date = investment_date + relativedelta(months=months)
                investment.due_date = investment_date + relativedelta(months=1)

        if 'payment_mode' in data:
            investment.payment_mode = _normalize_payment_mode(data['payment_mode'])

        if 'approval_status' in data:
            status_val = (data['approval_status'] or '').strip().title()
            if status_val not in ('Pending', 'Approved', 'Rejected'):
                return jsonify({'success': False, 'message': 'Invalid approval_status'}), 400
            investment.approval_status = status_val

        if 'status' in data:
            status_val = (data['status'] or '').strip().title()
            if status_val not in ('Active', 'Completed', 'Cancelled'):
                return jsonify({'success': False, 'message': 'Invalid status'}), 400
            investment.status = status_val

        if 'installments_paid' in data:
            paid = int(data['installments_paid'])
            total = investment.total_installments or 0
            if paid < 0 or (total and paid > total):
                return jsonify({'success': False, 'message': 'Invalid installments_paid'}), 400
            investment.installments_paid = paid

        db.session.commit()
        return jsonify({
            'success': True,
            'message': 'Investment plan updated',
            'data': _investment_detail(investment),
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Update failed: {str(e)}'}), 500


@investment_plan_bp.route('/<int:investment_id>', methods=['DELETE'])
@jwt_required()
def delete_investment(investment_id):
    """Super Admin only — permanently delete an investment plan."""
    denied = _require_superadmin()
    if denied:
        return denied

    investment = Investment.query.get(investment_id)
    if not investment:
        return jsonify({'success': False, 'message': 'Investment not found'}), 404

    identity = get_jwt_identity()
    irn = investment.irn

    try:
        if investment.approval_status == 'Approved':
            monthly = float(investment.monthly_amount or 0)
            if monthly > 0:
                _, wallet_err = refund_branch_wallet(
                    investment.branch_id,
                    monthly,
                    f'Investment deleted — {irn}',
                    reference_id=f'INVEST-{investment.id}',
                    created_by=identity,
                )
                if wallet_err:
                    db.session.rollback()
                    return jsonify({'success': False, 'message': wallet_err}), 400

            paid_installments = Installment.query.filter_by(
                investment_id=investment.id, status='Paid'
            ).all()
            for inst in paid_installments:
                if inst.installment_number <= 1:
                    continue
                _, wallet_err = refund_branch_wallet(
                    investment.branch_id,
                    float(inst.amount or monthly),
                    f'Installment #{inst.installment_number} refund — plan deleted {irn}',
                    reference_id=f'INSTALL-{investment.id}-{inst.installment_number}',
                    created_by=identity,
                )
                if wallet_err:
                    db.session.rollback()
                    return jsonify({'success': False, 'message': wallet_err}), 400

        Installment.query.filter_by(investment_id=investment.id).delete()
        Commission.query.filter_by(investment_id=investment.id).delete()
        db.session.delete(investment)
        db.session.commit()

        return jsonify({'success': True, 'message': f'Investment plan {irn} deleted'}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Delete failed: {str(e)}'}), 500


# ─── LIST ALL INVESTMENTS ─────────────────────────────────────────────────────

@investment_plan_bp.route('/list', methods=['GET'])
@jwt_required()
def list_investments():
    """
    List investments scoped by role:
      superadmin  → all (optional branch_id query param)
      branchmanager → current branch
      advisor/adviser → own adviser_code
      member      → own investor_id only
    """
    claims = get_jwt() or {}
    role = (claims.get('role') or '').lower()
    user = _get_current_user()

    page      = int(request.args.get('page', 1))
    per_page  = int(request.args.get('per_page', 20))
    plan_type = request.args.get('plan_type', '')
    status    = request.args.get('status', '')

    empty = {
        'success': True,
        'data': {
            'items': [],
            'total': 0,
            'page': page,
            'per_page': per_page,
            'pages': 0,
        },
    }

    q = Investment.query

    if role == 'member':
        investor_id = _investor_id_for_user(user)
        if not investor_id:
            return jsonify(empty), 200
        q = q.filter_by(investor_id=investor_id)
    elif role == 'branchmanager':
        branch, err = _get_current_branch()
        if err:
            return jsonify({'success': False, 'message': err}), 400
        q = q.filter_by(branch_id=branch.id)
    elif role in ('advisor', 'adviser'):
        from utils.member_lookup import find_adviser_for_user
        adviser = find_adviser_for_user(user)
        if not adviser:
            return jsonify(empty), 200
        q = q.filter_by(adviser_code=adviser.adviser_code)
    elif role == 'superadmin':
        branch_id = request.args.get('branch_id') or claims.get('branch_id')
        if branch_id:
            q = q.filter_by(branch_id=int(branch_id))
    else:
        branch, err = _get_current_branch()
        if err:
            return jsonify({'success': False, 'message': err}), 400
        q = q.filter_by(branch_id=branch.id)
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
        elif s == 'active':
            q = q.filter_by(approval_status='Approved', status='Active')
        elif s in ('completed', 'cancelled'):
            q = q.filter_by(status=s.title())
        else:
            q = q.filter_by(status=status.title())

    q = q.order_by(Investment.created_at.desc())
    paginated = q.paginate(page=page, per_page=per_page, error_out=False)

    items = _enrich_investment_items(paginated.items)
    if should_hide_branch(current_role()):
        items = sanitize_response(items)

    return jsonify({
        'success': True,
        'data': {
            'items':    items,
            'total':    paginated.total,
            'page':     page,
            'per_page': per_page,
            'pages':    paginated.pages,
        },
    }), 200


# ─── INVESTMENT RECEIPT ───────────────────────────────────────────────────────

def _fmt_receipt_date(d):
    if not d:
        return today_ist().strftime('%d %B %Y').lstrip('0')
    if isinstance(d, str):
        try:
            d = datetime.strptime(d[:10], '%Y-%m-%d').date()
        except ValueError:
            return d
    return d.strftime('%d %B %Y').lstrip('0')


def _fmt_due_date_upper(d):
    if not d:
        return '—'
    if isinstance(d, str):
        try:
            d = datetime.strptime(d[:10], '%Y-%m-%d').date()
        except ValueError:
            return str(d).upper()
    return d.strftime('%d %B %Y').lstrip('0').upper()


def _receipt_plan_label(investment):
    amount = int(float(investment.monthly_amount or 0))
    if investment.plan_type == 'SIS':
        return f'SISLT{amount}'
    tenure = investment.plan_tenure or ''
    return f'MIS{tenure}{amount}'


def _generate_receipt_no(investment, installments_paid):
    raw = int(f'{investment.branch_id or 0}{investment.id}{max(installments_paid, 1)}')
    return str(raw).zfill(8)


@investment_plan_bp.route('/receipt/<irn>', methods=['GET'])
@jwt_required()
def investment_receipt(irn):
    """Investment installment receipt data for branch manager / superadmin."""
    claims = get_jwt() or {}
    role = (claims.get('role') or '').lower()

    investment = Investment.query.filter_by(irn=irn).first()
    if not investment:
        return jsonify({'success': False, 'message': 'Investment plan not found'}), 404

    if role not in ('superadmin', 'branchmanager'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    if role == 'branchmanager':
        branch, err = _get_current_branch()
        if err:
            return jsonify({'success': False, 'message': err}), 400
        if investment.branch_id != branch.id:
            return jsonify({'success': False, 'message': 'Investment not in your branch'}), 403

    member = Member.query.filter_by(investor_id=investment.investor_id).first()
    if not member:
        return jsonify({'success': False, 'message': 'Investor not found'}), 404

    branch = Branch.query.get(investment.branch_id) if investment.branch_id else None
    branch_name = branch.branch_name.upper() if branch and branch.branch_name else '—'

    paid = investment.installments_paid or 0
    total = investment.total_installments or 0
    monthly = float(investment.monthly_amount or 0)
    is_sis = investment.plan_type == 'SIS'

    if is_sis:
        tri = int(monthly) if paid else 0
    else:
        tri = int(round(paid * monthly, 0)) if paid and monthly else 0

    roi_amount = int(float(investment.total_maturity_amount or 0))

    last_paid = Installment.query.filter_by(
        investment_id=investment.id, status='Paid'
    ).order_by(Installment.installment_number.desc()).first()

    receipt_date = last_paid.paid_date if last_paid and last_paid.paid_date else today_ist()
    payment_mode = (last_paid.payment_mode if last_paid and last_paid.payment_mode
                    else investment.payment_mode or 'Cash')

    return jsonify({
        'success': True,
        'data': {
            'irn': investment.irn,
            'receipt_no': _generate_receipt_no(investment, paid),
            'receipt_date': _fmt_receipt_date(receipt_date),
            'receipt_date_iso': receipt_date.isoformat() if hasattr(receipt_date, 'isoformat') else str(receipt_date),
            'company_name': 'DEFOEX INTRATECH PRIVATE LIMITED',
            'document_title': 'INVESTMENT RECEIPT',
            'investment_id': investment.irn,
            'investor_id': member.investor_id,
            'investor_name': member.full_name,
            'mobile': member.mobile,
            'plan_name': _receipt_plan_label(investment),
            'plan_type': investment.plan_type,
            'investment_term': 'Single' if is_sis else 'Monthly',
            'status_label': f'{paid} out of {total}' if total else f'{paid} out of 0',
            'final_investment': int(monthly),
            'late_fee': 0,
            'next_due_date': _fmt_due_date_upper(investment.due_date),
            'total_received': tri,
            'return_of_investment': roi_amount,
            'payment_mode': (payment_mode or 'Cash').upper(),
            'branch_name': branch_name,
            'remarks': (
                'Received with thanks towards the investment amount under the selected investment plan.'
                if is_sis else
                'Received with thanks towards the monthly investment installment '
                'under the selected investment plan.'
            ),
            'installments_paid': paid,
            'total_installments': total,
            'investor': {
                'investor_id': member.investor_id,
                'full_name': member.full_name,
                'mobile': member.mobile,
            },
            'investment': investment.to_dict(),
            'printed_at': isoformat_ist(now_ist()),
        }
    }), 200