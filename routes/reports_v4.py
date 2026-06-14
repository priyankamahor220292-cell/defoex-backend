from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from models.investment import Investment
from models.member import Member
from models.branch_wallet import BranchWallet
from extensions import db
from utils.helpers import success_response, error_response
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from sqlalchemy import func

reports_v4_bp = Blueprint('reports_v4', __name__, url_prefix='/api/reports')


def _business_total(branch_id, start_date, end_date):
    """Sum of approved investment amounts in date range"""
    q = db.session.query(func.sum(Investment.monthly_amount)).filter(
        Investment.approval_status == 'Approved',
        Investment.investment_date >= start_date,
        Investment.investment_date <= end_date
    )
    if branch_id:
        q = q.filter(Investment.branch_id == branch_id)
    return float(q.scalar() or 0)


def _investment_count(branch_id, start_date, end_date):
    q = Investment.query.filter(
        Investment.approval_status == 'Approved',
        Investment.investment_date >= start_date,
        Investment.investment_date <= end_date
    )
    if branch_id:
        q = q.filter_by(branch_id=branch_id)
    return q.count()


@reports_v4_bp.route('/business-summary', methods=['GET'])
@jwt_required()
def business_summary():
    """Task 4: Business totals for 1M, 3M, 6M, 1Y, Overall"""
    claims = get_jwt()
    branch_id = claims.get('branch_id') if claims.get('role') == 'branchmanager' else request.args.get('branch_id', type=int)

    today = date.today()

    periods = {
        '1_month':  (today - relativedelta(months=1), today),
        '3_months': (today - relativedelta(months=3), today),
        '6_months': (today - relativedelta(months=6), today),
        '1_year':   (today - relativedelta(years=1), today),
        'overall':  (date(2020, 1, 1), today),
    }

    summary = {}
    for label, (start, end) in periods.items():
        summary[label] = {
            'total_business': _business_total(branch_id, start, end),
            'investment_count': _investment_count(branch_id, start, end),
            'from': start.isoformat(),
            'to': end.isoformat()
        }

    # Wallet info
    wallet = None
    if branch_id:
        w = BranchWallet.query.filter_by(branch_id=branch_id).first()
        if w:
            wallet = w.to_dict()

    return jsonify(success_response({
        'summary': summary,
        'wallet': wallet
    })[0]), 200


@reports_v4_bp.route('/list-investors', methods=['GET'])
@jwt_required()
def list_investors():
    """Task 5: List investors with date range"""
    claims = get_jwt()
    branch_id = claims.get('branch_id') if claims.get('role') == 'branchmanager' else request.args.get('branch_id', type=int)

    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    query = Member.query.filter_by(approval_status='Approved')

    if branch_id:
        query = query.filter_by(branch_id=branch_id)
    if date_from:
        query = query.filter(Member.date_of_joining >= date.fromisoformat(date_from))
    if date_to:
        query = query.filter(Member.date_of_joining <= date.fromisoformat(date_to))

    paginated = query.order_by(Member.date_of_joining.desc()).paginate(page=page, per_page=per_page, error_out=False)

    items = []
    for m in paginated.items:
        has_plan = Investment.query.filter_by(investor_id=m.investor_id, approval_status='Approved').count() > 0
        items.append({
            'investor_name': m.full_name,
            'investor_id': m.investor_id,
            'date_of_joining': m.date_of_joining.isoformat() if m.date_of_joining else None,
            'adviser_code': m.adviser_code,
            'mobile': m.mobile,
            'city': m.corr_city,
            'status': 'Active' if has_plan else 'Not Active'
        })

    return jsonify(success_response({
        'items': items,
        'total': paginated.total,
        'pages': paginated.pages,
        'current_page': paginated.page
    })[0]), 200


@reports_v4_bp.route('/dashboard-stats', methods=['GET'])
@jwt_required()
def dashboard_stats():
    """Dashboard statistics for all roles"""
    claims = get_jwt()
    role = claims.get('role')
    branch_id = claims.get('branch_id')

    today = date.today()
    this_month_start = today.replace(day=1)

    q_members = Member.query.filter_by(approval_status='Approved')
    q_investments = Investment.query.filter_by(approval_status='Approved')

    if role == 'branchmanager' and branch_id:
        q_members = q_members.filter_by(branch_id=branch_id)
        q_investments = q_investments.filter_by(branch_id=branch_id)

    total_members = q_members.count()
    total_investments = q_investments.count()
    monthly_business = float(db.session.query(func.sum(Investment.monthly_amount)).filter(
        Investment.approval_status == 'Approved',
        Investment.investment_date >= this_month_start,
        *([Investment.branch_id == branch_id] if branch_id and role == 'branchmanager' else [])
    ).scalar() or 0)

    pending_members = Member.query.filter_by(approval_status='Pending').count()
    pending_investments = Investment.query.filter_by(approval_status='Pending').count()

    return jsonify(success_response({
        'total_members': total_members,
        'total_investments': total_investments,
        'monthly_business': monthly_business,
        'pending_members': pending_members,
        'pending_investments': pending_investments
    })[0]), 200
