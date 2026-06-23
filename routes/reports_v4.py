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
import traceback

reports_v4_bp = Blueprint('reports_v4', __name__, url_prefix='/api/reports')


def _business_total(branch_id, start_date, end_date):
    try:
        q = db.session.query(func.sum(Investment.monthly_amount)).filter(
            Investment.approval_status == 'Approved',
            Investment.investment_date >= start_date,
            Investment.investment_date <= end_date
        )
        if branch_id:
            q = q.filter(Investment.branch_id == branch_id)
        return float(q.scalar() or 0)
    except Exception:
        return 0


def _investment_count(branch_id, start_date, end_date):
    try:
        q = Investment.query.filter(
            Investment.approval_status == 'Approved',
            Investment.investment_date >= start_date,
            Investment.investment_date <= end_date
        )
        if branch_id:
            q = q.filter(Investment.branch_id == branch_id)
        return q.count()
    except Exception:
        return 0


@reports_v4_bp.route('/dashboard-stats', methods=['GET'])
@jwt_required()
def dashboard_stats():
    """Dashboard statistics — works for all roles"""
    try:
        claims = get_jwt()
        role      = claims.get('role')
        branch_id = claims.get('branch_id')

        today            = date.today()
        this_month_start = today.replace(day=1)

        # Base queries
        q_members     = Member.query.filter_by(approval_status='Approved')
        q_investments = Investment.query.filter_by(approval_status='Approved')

        # Filter by branch for BM
        if role == 'branchmanager' and branch_id:
            q_members     = q_members.filter_by(branch_id=branch_id)
            q_investments = q_investments.filter_by(branch_id=branch_id)
            # Exclude company owner adviser from BM view
            from models.adviser import Adviser as AdvModel
            q_advisers_bm = AdvModel.query.filter_by(
                branch_id=branch_id, is_active=True, is_company_owner=False
            )

        total_members     = q_members.count()
        total_investments = q_investments.count()

        # Monthly business — fix: no splat operator
        monthly_q = db.session.query(func.sum(Investment.monthly_amount)).filter(
            Investment.approval_status == 'Approved',
            Investment.investment_date >= this_month_start
        )
        if role == 'branchmanager' and branch_id:
            monthly_q = monthly_q.filter(Investment.branch_id == branch_id)
        monthly_business = float(monthly_q.scalar() or 0)

        # Pending counts
        pending_q_members = Member.query.filter_by(approval_status='Pending')
        pending_q_inv     = Investment.query.filter_by(approval_status='Pending')
        if role == 'branchmanager' and branch_id:
            pending_q_members = pending_q_members.filter_by(branch_id=branch_id)
            pending_q_inv     = pending_q_inv.filter_by(branch_id=branch_id)
            # BM never sees company owner related data

        pending_members     = pending_q_members.count()
        pending_investments = pending_q_inv.count()

        return jsonify(success_response({
            'total_members':       total_members,
            'total_investments':   total_investments,
            'monthly_business':    monthly_business,
            'pending_members':     pending_members,
            'pending_investments': pending_investments,
        })[0]), 200

    except Exception as e:
        print("dashboard_stats error:", traceback.format_exc())
        return jsonify(error_response(f'Dashboard stats error: {str(e)}')[0]), 500


@reports_v4_bp.route('/business-summary', methods=['GET'])
@jwt_required()
def business_summary():
    """Business totals for 1M, 3M, 6M, 1Y, Overall"""
    try:
        claims    = get_jwt()
        branch_id = claims.get('branch_id') if claims.get('role') == 'branchmanager' \
                    else request.args.get('branch_id', type=int)

        today = date.today()
        periods = {
            '1_month':  (today - relativedelta(months=1),  today),
            '3_months': (today - relativedelta(months=3),  today),
            '6_months': (today - relativedelta(months=6),  today),
            '1_year':   (today - relativedelta(years=1),   today),
            'overall':  (date(2020, 1, 1),                 today),
        }

        summary = {}
        for label, (start, end) in periods.items():
            summary[label] = {
                'total_business':   _business_total(branch_id, start, end),
                'investment_count': _investment_count(branch_id, start, end),
                'from': start.isoformat(),
                'to':   end.isoformat(),
            }

        wallet = None
        if branch_id:
            w = BranchWallet.query.filter_by(branch_id=branch_id).first()
            if w:
                wallet = w.to_dict()

        return jsonify(success_response({'summary': summary, 'wallet': wallet})[0]), 200

    except Exception as e:
        print("business_summary error:", traceback.format_exc())
        return jsonify(error_response(f'Summary error: {str(e)}')[0]), 500


@reports_v4_bp.route('/list-investors', methods=['GET'])
@jwt_required()
def list_investors():
    """List investors with date range filter"""
    try:
        claims    = get_jwt()
        branch_id = claims.get('branch_id') if claims.get('role') == 'branchmanager' \
                    else request.args.get('branch_id', type=int)

        date_from = request.args.get('date_from')
        date_to   = request.args.get('date_to')
        page      = request.args.get('page', 1, type=int)
        per_page  = request.args.get('per_page', 20, type=int)

        query = Member.query.filter_by(approval_status='Approved')
        if branch_id:
            query = query.filter_by(branch_id=branch_id)
        if date_from:
            try:
                query = query.filter(Member.date_of_joining >= date.fromisoformat(date_from))
            except ValueError:
                pass
        if date_to:
            try:
                query = query.filter(Member.date_of_joining <= date.fromisoformat(date_to))
            except ValueError:
                pass

        paginated = query.order_by(Member.date_of_joining.desc()).paginate(
            page=page, per_page=per_page, error_out=False)

        items = []
        for m in paginated.items:
            has_plan = Investment.query.filter_by(
                investor_id=m.investor_id, approval_status='Approved').count() > 0
            items.append({
                'investor_name':  m.full_name,
                'investor_id':    m.investor_id,
                'date_of_joining': m.date_of_joining.isoformat() if m.date_of_joining else None,
                'adviser_code':   m.adviser_code,
                'mobile':         m.mobile,
                'city':           m.corr_city,
                'status':         'Active' if has_plan else 'Not Active',
            })

        return jsonify(success_response({
            'items':        items,
            'total':        paginated.total,
            'pages':        paginated.pages,
            'current_page': paginated.page,
        })[0]), 200

    except Exception as e:
        print("list_investors error:", traceback.format_exc())
        return jsonify(error_response(f'List error: {str(e)}')[0]), 500


@reports_v4_bp.route('/search', methods=['GET'])
@jwt_required()
def global_search():
    """
    Universal search across investors, investment plans, and advisers.
    Search by: IRN, Investor ID, Investor Name, Mobile, Adviser Code
    """
    try:
        claims    = get_jwt()
        branch_id = claims.get('branch_id') if claims.get('role') == 'branchmanager' else None
        query     = request.args.get('q', '').strip()
        search_by = request.args.get('by', 'all')   # irn | investor | adviser | mobile | all

        if not query or len(query) < 2:
            return jsonify(error_response('Enter at least 2 characters')[0]), 400

        results = {'investors': [], 'investments': [], 'advisers': []}
        q_like  = f'%{query}%'

        # ── Search Investments by IRN ─────────────────────────────
        if search_by in ('irn', 'all'):
            inv_q = Investment.query.filter(Investment.irn.ilike(q_like))
            if branch_id:
                inv_q = inv_q.filter_by(branch_id=branch_id)
            for inv in inv_q.limit(10).all():
                member = Member.query.filter_by(investor_id=inv.investor_id).first()
                results['investments'].append({
                    **inv.to_dict(),
                    'investor_name': member.full_name if member else None,
                    'investor_mobile': member.mobile if member else None,
                })

        # ── Search Investors by ID, Name, Mobile ─────────────────
        if search_by in ('investor', 'mobile', 'all'):
            mem_q = Member.query.filter(
                db.or_(
                    Member.investor_id.ilike(q_like),
                    Member.full_name.ilike(q_like),
                    Member.mobile.ilike(q_like),
                    Member.aadhar_number.ilike(q_like),
                )
            )
            if branch_id:
                mem_q = mem_q.filter_by(branch_id=branch_id)
            for m in mem_q.limit(10).all():
                inv_count = Investment.query.filter_by(
                    investor_id=m.investor_id, approval_status='Approved'
                ).count()
                d = m.to_dict()
                d['plan_count'] = inv_count
                d['status'] = 'Active' if inv_count > 0 else 'Not Active'
                results['investors'].append(d)

        # ── Search Advisers ───────────────────────────────────────
        if search_by in ('adviser', 'all'):
            from models.adviser import Adviser
            adv_q = Adviser.query.filter(
                db.or_(
                    Adviser.adviser_code.ilike(q_like),
                    Adviser.full_name.ilike(q_like),
                    Adviser.mobile.ilike(q_like),
                ),
                Adviser.is_company_owner == False  # Never show company owner
            )
            if branch_id:
                adv_q = adv_q.filter_by(branch_id=branch_id)
            results['advisers'] = [a.to_dict() for a in adv_q.limit(10).all()]

        total = sum(len(v) for v in results.values())
        return jsonify(success_response({
            'query':   query,
            'search_by': search_by,
            'total':   total,
            **results,
        })[0]), 200

    except Exception as e:
        print(traceback.format_exc())
        return jsonify(error_response(f'Search failed: {str(e)}')[0]), 500