"""
Adviser Portal Routes
======================
Adviser Login → Dashboard, Adviser Info, Self Contribution, Down Contribution
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from models.adviser import Adviser
from models.member import Member
from models.investment import Investment
from models.commission import Commission
from extensions import db
from utils.helpers import success_response, error_response
from utils.role_scoping import sanitize_response
from sqlalchemy import text
import traceback

adviser_portal_bp = Blueprint('adviser_portal', __name__, url_prefix='/api/adviser-portal')


def get_current_adviser():
    """Get the adviser record for the currently logged-in adviser user."""
    claims = get_jwt()
    role = (claims.get('role') or '').lower()
    if role not in ('advisor', 'adviser'):
        return None, 'Not an adviser account'

    identity = get_jwt_identity()
    from models.user import User
    from utils.member_lookup import find_adviser_for_user

    try:
        user = User.query.get(int(identity))
    except (TypeError, ValueError):
        user = User.query.filter_by(username=str(identity).strip()).first()
    if not user:
        return None, 'User not found'

    adviser = find_adviser_for_user(user)
    if not adviser:
        adviser = Adviser.query.filter_by(is_active=True).filter(
            db.or_(
                Adviser.mobile == user.mobile,
                db.func.upper(Adviser.login_username) == (user.username or '').strip().upper(),
            )
        ).first()
    if not adviser:
        return None, 'Adviser profile not found for this login'
    return adviser, None


def get_downline_codes(adviser_code, max_depth=10):
    """
    Get all adviser codes in the downline (advisers whose promoter chain leads to this adviser).
    Returns set of adviser codes.
    """
    result = set()
    to_check = [adviser_code]
    seen = set()
    depth = 0
    while to_check and depth < max_depth:
        current_batch = to_check[:]
        to_check = []
        for code in current_batch:
            if code in seen:
                continue
            seen.add(code)
            # Find advisers who have this code as parent
            children = Adviser.query.filter_by(
                parent_adviser_code=code, is_active=True, is_company_owner=False
            ).all()
            for child in children:
                if child.adviser_code not in result:
                    result.add(child.adviser_code)
                    to_check.append(child.adviser_code)
        depth += 1
    return result


TEAM_BENEFIT_TYPES = ('Team', 'Upper Rank')


def _commission_sum(adviser_code, types=None):
    q = db.session.query(db.func.sum(Commission.commission_amount)).filter(
        Commission.adviser_code == adviser_code
    )
    if types:
        q = q.filter(Commission.commission_type.in_(types))
    return float(q.scalar() or 0)


def _business_volume(adviser_codes):
    if not adviser_codes:
        return 0.0
    return float(
        db.session.query(db.func.sum(Investment.total_investment_amount)).filter(
            Investment.adviser_code.in_(list(adviser_codes)),
            Investment.approval_status == 'Approved',
        ).scalar() or 0
    )


def _benefits_summary(adviser):
    """Direct / Team benefits and business volumes for adviser panel."""
    code = adviser.adviser_code
    downline = get_downline_codes(code)
    direct_benefits = _commission_sum(code, ('Direct',))
    team_benefits = _commission_sum(code, TEAM_BENEFIT_TYPES)
    self_business = _business_volume({code})
    team_business = _business_volume(downline)
    return {
        'direct_benefits':     direct_benefits,
        'team_benefits':       team_benefits,
        'total_benefits':      direct_benefits + team_benefits,
        'self_business':       self_business,
        'team_business':       team_business,
        'total_business_volume': self_business + team_business,
    }


# ── Dashboard ─────────────────────────────────────────────────────
@adviser_portal_bp.route('/dashboard', methods=['GET'])
@jwt_required()
def adviser_dashboard():
    adviser, err = get_current_adviser()
    if err or not adviser:
        return jsonify(error_response(err or 'Adviser not found', 404)[0]), 404

    downline_codes = get_downline_codes(adviser.adviser_code)
    benefits       = _benefits_summary(adviser)

    # Counts
    my_investors    = Member.query.filter_by(adviser_code=adviser.adviser_code, approval_status='Approved').count()
    my_investments  = Investment.query.filter_by(adviser_code=adviser.adviser_code, approval_status='Approved').count()
    down_investors  = Member.query.filter(Member.adviser_code.in_(downline_codes), Member.approval_status=='Approved').count() if downline_codes else 0
    down_investments= Investment.query.filter(Investment.adviser_code.in_(downline_codes), Investment.approval_status=='Approved').count() if downline_codes else 0
    total_business  = benefits['total_business_volume']
    my_commission   = benefits['total_benefits']

    return jsonify(success_response(sanitize_response({
        'adviser':          adviser.to_dict(),
        'my_investors':     my_investors,
        'my_investments':   my_investments,
        'down_investors':   down_investors,
        'down_investments': down_investments,
        'total_business':   total_business,
        'my_commission':    my_commission,
        'direct_benefits':  benefits['direct_benefits'],
        'team_benefits':    benefits['team_benefits'],
        'self_business':    benefits['self_business'],
        'team_business':    benefits['team_business'],
        'downline_count':   len(downline_codes),
    }))[0]), 200


# ── Adviser Info ──────────────────────────────────────────────────
@adviser_portal_bp.route('/info', methods=['GET'])
@jwt_required()
def adviser_info():
    adviser, err = get_current_adviser()
    if err or not adviser:
        return jsonify(error_response(err or 'Adviser not found', 404)[0]), 404

    # Get promoter info
    promoter = None
    if adviser.parent_adviser_code:
        p = Adviser.query.filter_by(adviser_code=adviser.parent_adviser_code).first()
        if p:
            promoter = {'adviser_code': p.adviser_code, 'full_name': p.full_name, 'rank_name': p.rank_name}

    # Get direct investors count
    investors_count = Member.query.filter_by(
        adviser_code=adviser.adviser_code, approval_status='Approved'
    ).count()

    # Commissions
    benefits = _benefits_summary(adviser)
    commissions = Commission.query.filter_by(adviser_code=adviser.adviser_code).all()
    total_comm  = benefits['total_benefits']
    paid_comm   = sum(float(c.commission_amount or 0) for c in commissions if c.status == 'Paid')

    return jsonify(success_response(sanitize_response({
        **adviser.to_dict(),
        'promoter':         promoter,
        'investors_count':  investors_count,
        'total_commission': total_comm,
        'paid_commission':  paid_comm,
        'pending_commission': total_comm - paid_comm,
        'direct_benefits':  benefits['direct_benefits'],
        'team_benefits':    benefits['team_benefits'],
        'self_business':    benefits['self_business'],
        'team_business':    benefits['team_business'],
    }))[0]), 200


# ── Self Contribution Info ────────────────────────────────────────
@adviser_portal_bp.route('/self-contribution', methods=['GET'])
@jwt_required()
def self_contribution():
    """Display list of all investments made through this adviser (their direct investors)."""
    adviser, err = get_current_adviser()
    if err or not adviser:
        return jsonify(error_response(err or 'Adviser not found', 404)[0]), 404

    page     = request.args.get('page', 1, type=int)
    per_page = 20
    offset   = (page - 1) * per_page

    investments = Investment.query.filter_by(
        adviser_code=adviser.adviser_code, approval_status='Approved'
    ).order_by(Investment.created_at.desc()).offset(offset).limit(per_page).all()

    total = Investment.query.filter_by(
        adviser_code=adviser.adviser_code, approval_status='Approved'
    ).count()

    total_business = db.session.query(db.func.sum(Investment.total_investment_amount)).filter_by(
        adviser_code=adviser.adviser_code, approval_status='Approved'
    ).scalar() or 0

    my_commission = db.session.query(db.func.sum(Commission.commission_amount)).filter_by(
        adviser_code=adviser.adviser_code, commission_type='Direct'
    ).scalar() or 0

    # Enrich with investor name
    items = []
    for inv in investments:
        d = inv.to_dict()
        member = Member.query.filter_by(investor_id=inv.investor_id).first()
        d['investor_name']   = member.full_name if member else None
        d['investor_mobile'] = member.mobile    if member else None
        items.append(d)

    return jsonify(success_response(sanitize_response({
        'adviser_code':     adviser.adviser_code,
        'adviser_name':     adviser.full_name,
        'items':            items,
        'total':            total,
        'pages':            (total + per_page - 1) // per_page,
        'total_business':   float(total_business),
        'direct_commission':float(my_commission),
    }))[0]), 200


# ── Down Contribution Info ────────────────────────────────────────
@adviser_portal_bp.route('/down-contribution', methods=['GET'])
@jwt_required()
def down_contribution():
    """
    Display all investment records made through this adviser's downline network:
    - Business generated by all advisers under them
    - Details of their own direct investments
    """
    adviser, err = get_current_adviser()
    if err or not adviser:
        return jsonify(error_response(err or 'Adviser not found', 404)[0]), 404

    page     = request.args.get('page', 1, type=int)
    per_page = 20

    downline_codes = get_downline_codes(adviser.adviser_code)

    if not downline_codes:
        return jsonify(success_response(sanitize_response({
            'items':          [],
            'total':          0,
            'total_business': 0,
            'downline_count': 0,
            'by_adviser':     [],
        }))[0]), 200

    offset = (page - 1) * per_page

    investments = Investment.query.filter(
        Investment.adviser_code.in_(downline_codes),
        Investment.approval_status == 'Approved'
    ).order_by(Investment.created_at.desc()).offset(offset).limit(per_page).all()

    total = Investment.query.filter(
        Investment.adviser_code.in_(downline_codes),
        Investment.approval_status == 'Approved'
    ).count()

    total_business = db.session.query(db.func.sum(Investment.total_investment_amount)).filter(
        Investment.adviser_code.in_(downline_codes),
        Investment.approval_status == 'Approved'
    ).scalar() or 0

    upper_commission = _commission_sum(adviser.adviser_code, TEAM_BENEFIT_TYPES)

    # Group by adviser
    by_adviser = []
    for code in sorted(downline_codes):
        a = Adviser.query.filter_by(adviser_code=code).first()
        if not a: continue
        inv_count = Investment.query.filter_by(adviser_code=code, approval_status='Approved').count()
        biz = db.session.query(db.func.sum(Investment.total_investment_amount)).filter_by(
            adviser_code=code, approval_status='Approved'
        ).scalar() or 0
        by_adviser.append({
            'adviser_code': code,
            'adviser_name': a.full_name,
            'rank_name':    a.rank_name or 'SR',
            'inv_count':    inv_count,
            'business':     float(biz),
        })

    items = []
    for inv in investments:
        d = inv.to_dict()
        member = Member.query.filter_by(investor_id=inv.investor_id).first()
        adv    = Adviser.query.filter_by(adviser_code=inv.adviser_code).first()
        d['investor_name']   = member.full_name  if member else None
        d['adviser_name']    = adv.full_name     if adv    else None
        items.append(d)

    return jsonify(success_response(sanitize_response({
        'items':            items,
        'total':            total,
        'pages':            (total + per_page - 1) // per_page,
        'total_business':   float(total_business),
        'upper_commission': float(upper_commission),
        'team_benefits':    float(upper_commission),
        'downline_count':   len(downline_codes),
        'by_adviser':       sorted(by_adviser, key=lambda x: -x['business']),
    }))[0]), 200