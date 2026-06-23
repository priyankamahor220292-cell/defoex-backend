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
from sqlalchemy import text
import traceback

adviser_portal_bp = Blueprint('adviser_portal', __name__, url_prefix='/api/adviser-portal')


def get_current_adviser():
    """Get the adviser record for the currently logged-in adviser user."""
    claims = get_jwt()
    if claims.get('role') != 'adviser':
        return None, 'Not an adviser account'
    # Find adviser by mobile or username from JWT
    identity = get_jwt_identity()
    from models.user import User
    user = User.query.get(int(identity))
    if not user:
        return None, 'User not found'
    # Match adviser by mobile
    adviser = Adviser.query.filter_by(mobile=user.mobile, is_active=True).first()
    if not adviser:
        # Try matching by username prefix (DEFA202601 → adviser created around that time)
        adviser = Adviser.query.filter_by(is_active=True).filter(
            db.or_(
                Adviser.email == user.email,
                Adviser.mobile == user.mobile,
            )
        ).first()
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


# ── Dashboard ─────────────────────────────────────────────────────
@adviser_portal_bp.route('/dashboard', methods=['GET'])
@jwt_required()
def adviser_dashboard():
    adviser, err = get_current_adviser()
    if err or not adviser:
        return jsonify(error_response(err or 'Adviser not found', 404)[0]), 404

    downline_codes = get_downline_codes(adviser.adviser_code)
    all_codes      = {adviser.adviser_code} | downline_codes

    # Counts
    my_investors    = Member.query.filter_by(adviser_code=adviser.adviser_code, approval_status='Approved').count()
    my_investments  = Investment.query.filter_by(adviser_code=adviser.adviser_code, approval_status='Approved').count()
    down_investors  = Member.query.filter(Member.adviser_code.in_(downline_codes), Member.approval_status=='Approved').count() if downline_codes else 0
    down_investments= Investment.query.filter(Investment.adviser_code.in_(downline_codes), Investment.approval_status=='Approved').count() if downline_codes else 0
    total_business  = db.session.query(db.func.sum(Investment.total_investment_amount)).filter(
        Investment.adviser_code.in_(all_codes), Investment.approval_status=='Approved'
    ).scalar() or 0
    my_commission   = db.session.query(db.func.sum(Commission.commission_amount)).filter_by(
        adviser_code=adviser.adviser_code
    ).scalar() or 0

    return jsonify(success_response({
        'adviser':          adviser.to_dict(),
        'my_investors':     my_investors,
        'my_investments':   my_investments,
        'down_investors':   down_investors,
        'down_investments': down_investments,
        'total_business':   float(total_business),
        'my_commission':    float(my_commission),
        'downline_count':   len(downline_codes),
    })[0]), 200


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
    commissions = Commission.query.filter_by(adviser_code=adviser.adviser_code).all()
    total_comm  = sum(float(c.commission_amount or 0) for c in commissions)
    paid_comm   = sum(float(c.commission_amount or 0) for c in commissions if c.status == 'Paid')

    return jsonify(success_response({
        **adviser.to_dict(),
        'promoter':         promoter,
        'investors_count':  investors_count,
        'total_commission': total_comm,
        'paid_commission':  paid_comm,
        'pending_commission': total_comm - paid_comm,
    })[0]), 200


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

    return jsonify(success_response({
        'adviser_code':     adviser.adviser_code,
        'adviser_name':     adviser.full_name,
        'items':            items,
        'total':            total,
        'pages':            (total + per_page - 1) // per_page,
        'total_business':   float(total_business),
        'direct_commission':float(my_commission),
    })[0]), 200


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
        return jsonify(success_response({
            'items':          [],
            'total':          0,
            'total_business': 0,
            'downline_count': 0,
            'by_adviser':     [],
        })[0]), 200

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

    upper_commission = db.session.query(db.func.sum(Commission.commission_amount)).filter_by(
        adviser_code=adviser.adviser_code, commission_type='Upper Rank'
    ).scalar() or 0

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

    return jsonify(success_response({
        'items':            items,
        'total':            total,
        'pages':            (total + per_page - 1) // per_page,
        'total_business':   float(total_business),
        'upper_commission': float(upper_commission),
        'downline_count':   len(downline_codes),
        'by_adviser':       sorted(by_adviser, key=lambda x: -x['business']),
    })[0]), 200