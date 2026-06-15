"""
Adviser routes
==============
Key rule: investor_id == adviser_code for the same person.
When creating an adviser who is already an investor → reuse their code.
When creating a new adviser (not yet investor) → generate new code.
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from models.adviser import Adviser
from models.member import Member
from extensions import db
from utils.helpers import generate_code, success_response, error_response
import traceback

advisers_bp = Blueprint('advisers', __name__, url_prefix='/api/advisers')

RANKS = {
    1:'SR', 2:'SO', 3:'SD', 4:'SI', 5:'DO', 6:'RO', 7:'ZO',
    8:'EM', 9:'EM I', 10:'EM II', 11:'EM R', 12:'EM C',
    13:'House 1', 14:'House 2', 15:'House 3', 16:'House 4',
    17:'House 5', 18:'House 6', 19:'House 7', 20:'House 8',
}


@advisers_bp.route('/', methods=['GET'])
@jwt_required()
def list_advisers():
    claims    = get_jwt()
    branch_id = claims.get('branch_id')
    q = Adviser.query.filter_by(is_active=True)
    if branch_id and claims.get('role') == 'branchmanager':
        q = q.filter_by(branch_id=branch_id)
    return jsonify(success_response([a.to_dict() for a in q.all()])[0]), 200


@advisers_bp.route('/<code>', methods=['GET'])
@jwt_required()
def get_adviser(code):
    a = Adviser.query.filter_by(adviser_code=code).first()
    if not a:
        return jsonify(error_response('Adviser not found', 404)[0]), 404
    return jsonify(success_response(a.to_dict())[0]), 200


@advisers_bp.route('/', methods=['POST'])
@jwt_required()
def create_adviser():
    claims = get_jwt()
    if claims.get('role') not in ['superadmin', 'branchmanager']:
        return jsonify(error_response('Unauthorized', 403)[0]), 403

    data      = request.get_json() or {}
    mobile    = str(data.get('mobile', '')).strip()
    full_name = str(data.get('full_name', '')).strip()
    branch_id = data.get('branch_id') or claims.get('branch_id')

    if not full_name or not mobile:
        return jsonify(error_response('full_name and mobile are required')[0]), 400

    # Already an adviser?
    existing = Adviser.query.filter_by(mobile=mobile).first()
    if existing:
        return jsonify(error_response(
            f'This person is already an adviser. Code: {existing.adviser_code}'
        )[0]), 409

    # ── Core rule: same person = same code ────────────────────────────────
    # If this mobile belongs to an approved investor → reuse their code
    investor = Member.query.filter_by(mobile=mobile, approval_status='Approved').first()
    if investor:
        code = investor.investor_id          # SAME code
        note = (f'Investor {code} promoted to adviser — same code used for both roles.')
    else:
        code = generate_code()               # NEW code
        note = f'New adviser created with code {code}.'

    try:
        adviser = Adviser(
            adviser_code        = code,
            full_name           = full_name,
            mobile              = mobile,
            email               = data.get('email') or None,
            rank_id             = int(data.get('rank_id', 1)),
            branch_id           = int(branch_id) if branch_id else None,
            parent_adviser_code = data.get('parent_adviser_code') or None,
            is_active           = True,
        )
        db.session.add(adviser)
        db.session.commit()
        resp       = adviser.to_dict()
        resp['note'] = note
        return jsonify(success_response(resp, f'Adviser code: {code}')[0]), 201
    except Exception as e:
        db.session.rollback()
        print(traceback.format_exc())
        return jsonify(error_response(str(e))[0]), 500


@advisers_bp.route('/lookup-by-mobile/<mobile>', methods=['GET'])
@jwt_required()
def lookup_by_mobile(mobile):
    """Check if mobile belongs to an existing investor — for adviser creation form."""
    investor = Member.query.filter_by(mobile=mobile, approval_status='Approved').first()
    adviser  = Adviser.query.filter_by(mobile=mobile).first()
    return jsonify(success_response({
        'is_investor': bool(investor),
        'is_adviser':  bool(adviser),
        'investor_id': investor.investor_id if investor else None,
        'adviser_code':adviser.adviser_code if adviser else None,
        'full_name':   investor.full_name if investor else (adviser.full_name if adviser else None),
        'will_reuse':  bool(investor and not adviser),
        'code_to_reuse': investor.investor_id if (investor and not adviser) else None,
    })[0]), 200


@advisers_bp.route('/<int:adviser_id>', methods=['PUT'])
@jwt_required()
def update_adviser(adviser_id):
    claims = get_jwt()
    if claims.get('role') != 'superadmin':
        return jsonify(error_response('Unauthorized', 403)[0]), 403
    a = Adviser.query.get_or_404(adviser_id)
    data = request.get_json() or {}
    for f in ['full_name', 'mobile', 'email', 'rank_id', 'is_active', 'branch_id']:
        if f in data:
            setattr(a, f, data[f])
    db.session.commit()
    return jsonify(success_response(a.to_dict(), 'Adviser updated')[0]), 200