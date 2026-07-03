from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from models.adviser import Adviser, RANKS
from models.member import Member
from extensions import db
from sqlalchemy import text, func
from utils.helpers import (
    generate_adviser_code, success_response, error_response,
    normalize_mobile, find_adviser_by_mobile, find_member_by_mobile,
)
from utils.rank_helpers import validate_assigned_rank, allowed_ranks_for_promoter, rank_label
from utils.member_lookup import find_promoter_adviser
import json
import traceback


advisers_bp = Blueprint('advisers', __name__, url_prefix='/api/advisers')

ADVISER_FEE = 650  # Fixed adviser registration fee


def _investor_counts():
    rows = (
        db.session.query(Member.adviser_code, func.count(Member.id))
        .filter(Member.approval_status == 'Approved')
        .group_by(Member.adviser_code)
        .all()
    )
    return {code: count for code, count in rows}


def _adviser_payload(adviser, counts=None):
    counts = counts if counts is not None else _investor_counts()
    inv = counts.get(adviser.adviser_code, 0)
    return adviser.to_dict(investor_count=inv)


def _check_aadhar_unique(aadhar, exclude_mobile=None):
    if not aadhar:
        return None
    aadhar = str(aadhar).strip()
    member = Member.query.filter_by(aadhar_number=aadhar).first()
    if member and (not exclude_mobile or member.mobile != exclude_mobile):
        return f'Aadhar number already registered to investor {member.investor_id}'
    for adv in Adviser.query.all():
        reg = adv._registration_dict() if hasattr(adv, '_registration_dict') else {}
        if reg.get('aadhar_number') == aadhar and adv.mobile != exclude_mobile:
            return f'Aadhar number already registered to adviser {adv.adviser_code}'
    return None


@advisers_bp.route('/', methods=['GET'])
@jwt_required()
def list_advisers():
    claims = get_jwt()
    role = claims.get('role')
    branch_id = claims.get('branch_id')
    pending_only = request.args.get('pending', '').lower() in ('1', 'true', 'yes')
    include_blacklisted = request.args.get('include_blacklisted', '').lower() in ('1', 'true', 'yes')

    q = Adviser.query.filter(Adviser.is_company_owner == False)
    if not include_blacklisted:
        q = q.filter(Adviser.is_blacklisted == False)

    if role == 'branchmanager':
        q = q.filter(Adviser.branch_id == branch_id)

    if pending_only:
        q = q.filter(Adviser.is_active == False, Adviser.is_blacklisted == False)

    counts = _investor_counts()
    advisers = q.order_by(Adviser.created_at.desc()).all()
    return jsonify(success_response([_adviser_payload(a, counts) for a in advisers])[0]), 200


@advisers_bp.route('/detail/<int:adviser_id>', methods=['GET'])
@jwt_required()
def adviser_detail(adviser_id):
    adviser = Adviser.query.get_or_404(adviser_id)
    counts = _investor_counts()
    investors = (
        Member.query.filter_by(adviser_code=adviser.adviser_code, approval_status='Approved')
        .order_by(Member.created_at.desc())
        .all()
    )
    payload = _adviser_payload(adviser, counts)
    payload['investors'] = [m.to_dict() for m in investors]
    return jsonify(success_response(payload)[0]), 200


def _promoter_verify_payload(adviser):
    """Build verify response with rank options for downline registration."""
    promoter_rank = int(adviser.rank_id or 1)
    payload = _adviser_payload(adviser)
    payload['rank_id'] = promoter_rank
    rank_ids, rank_err = allowed_ranks_for_promoter(promoter_rank)
    payload['promoter_rank_id'] = promoter_rank
    payload['promoter_rank_display'] = rank_label(promoter_rank)
    if rank_ids:
        max_rank = rank_ids[-1]
        payload['max_allowed_rank_id'] = max_rank
        payload['allowed_rank_ids'] = rank_ids
        payload['allowed_ranks'] = [{'id': r, 'label': rank_label(r)} for r in rank_ids]
        payload['allowed_rank_id'] = max_rank
        payload['allowed_rank_display'] = rank_label(max_rank)
    else:
        payload['allowed_rank_error'] = rank_err
    return payload


@advisers_bp.route('/verify-promoter', methods=['POST'])
@jwt_required()
def verify_promoter_adviser():
    """Verify promoter adviser ID and return assignable downline ranks."""
    data = request.get_json() or {}
    code = (data.get('adviser_code') or data.get('promoter_adviser_id') or '').strip()
    if not code:
        return jsonify(error_response('Please enter a Promoter Adviser ID')[0]), 400

    adviser, err = find_promoter_adviser(code)
    if err:
        return jsonify(error_response(err, 404)[0]), 404

    return jsonify(success_response(_promoter_verify_payload(adviser), 'Adviser verified')[0]), 200


@advisers_bp.route('/<code>', methods=['GET'])
@jwt_required()
def get_adviser(code):
    adviser, err = find_promoter_adviser(code)
    if err:
        return jsonify(error_response(err, 404)[0]), 404
    return jsonify(success_response(_adviser_payload(adviser))[0]), 200


@advisers_bp.route('/', methods=['POST'])
@jwt_required()
def create_adviser():
    claims = get_jwt()
    if claims.get('role') not in ('superadmin', 'branchmanager'):
        return jsonify(error_response('Unauthorized', 403)[0]), 403

    data = request.get_json() or {}
    mobile = normalize_mobile(data.get('mobile', ''))
    full_name = str(data.get('full_name', '')).strip()
    branch_id = data.get('branch_id') or claims.get('branch_id')
    parent_code = (data.get('parent_adviser_code') or data.get('promoter_adviser_id') or '').strip()
    rank_id = int(data.get('rank_id') or 0)
    aadhar = str(data.get('aadhar_number') or '').strip()

    required = {
        'full_name': full_name,
        'mobile': mobile,
        'aadhar_number': aadhar,
        'father_spouse_name': data.get('father_spouse_name') or data.get('father_name'),
        'corr_address': data.get('corr_address'),
        'date_of_birth': data.get('date_of_birth'),
        'gender': data.get('gender'),
        'marital_status': data.get('marital_status'),
        'nominee_name': data.get('nominee_name'),
        'nominee_age': data.get('nominee_age'),
        'nominee_relationship': data.get('nominee_relationship'),
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        return jsonify(error_response(f'Missing required fields: {", ".join(missing)}')[0]), 400

    if len(mobile) != 10:
        return jsonify(error_response('Valid 10-digit mobile number is required')[0]), 400
    if len(aadhar) != 12:
        return jsonify(error_response('Valid 12-digit Aadhar number is required')[0]), 400

    if not parent_code:
        return jsonify(error_response('Promoter Adviser ID is required')[0]), 400

    promoter, promoter_err = find_promoter_adviser(parent_code)
    if promoter_err:
        return jsonify(error_response(promoter_err)[0]), 400
    parent_code = promoter.adviser_code

    rank_err = validate_assigned_rank(promoter.rank_id, rank_id)
    if rank_err:
        return jsonify(error_response(rank_err)[0]), 400

    existing = find_adviser_by_mobile(mobile)
    if existing:
        return jsonify(error_response(
            f'This mobile is already registered as adviser {existing.adviser_code}'
        )[0]), 409

    aadhar_err = _check_aadhar_unique(aadhar, exclude_mobile=mobile)
    if aadhar_err:
        return jsonify(error_response(aadhar_err)[0]), 409

    investor = find_member_by_mobile(mobile)
    if investor and investor.approval_status == 'Approved':
        code = investor.investor_id
        note = f'Investor {code} promoted to adviser — same code used for both roles.'
    else:
        code = generate_adviser_code()
        note = f'New adviser created with code {code}.'

    reg_payload = {k: v for k, v in data.items() if v is not None}
    reg_payload['promoter_adviser_id'] = parent_code
    reg_payload['promoter_name'] = promoter.full_name
    reg_payload['promoter_rank'] = promoter.rank_name
    reg_payload['promoter_rank_id'] = promoter.rank_id

    try:
        adviser = Adviser(
            adviser_code=code,
            full_name=full_name,
            mobile=mobile,
            email=data.get('email') or None,
            rank_id=rank_id,
            branch_id=int(branch_id) if branch_id else None,
            parent_adviser_code=parent_code,
            investor_id=investor.investor_id if (investor and investor.approval_status == 'Approved') else None,
            is_active=False,
            registration_data=json.dumps(reg_payload),
        )
        try:
            adviser.father_name = data.get('father_spouse_name') or data.get('father_name') or None
        except Exception:
            pass

        db.session.add(adviser)
        db.session.flush()

        fees = ADVISER_FEE
        if branch_id and fees > 0:
            from utils.branch_wallet_ops import deduct_branch_wallet
            from flask_jwt_extended import get_jwt_identity
            wallet_result, wallet_err = deduct_branch_wallet(
                int(branch_id),
                fees,
                f'Adviser registration fee — {full_name} ({code})',
                reference_id=f'ADVISER-{code}',
                created_by=get_jwt_identity(),
            )
            if wallet_err:
                db.session.rollback()
                return jsonify(error_response(wallet_err)[0]), 400
        else:
            wallet_result = None

        db.session.commit()
        resp = _adviser_payload(adviser)
        resp['note'] = note
        if wallet_result:
            resp['wallet'] = wallet_result
        return jsonify(success_response(
            resp,
            f'Adviser registered ({code}). Go to Approved Adviser tab. Fee ₹{fees:.0f} deducted.'
        )[0]), 201
    except Exception as e:
        db.session.rollback()
        print(traceback.format_exc())
        return jsonify(error_response(str(e))[0]), 500


@advisers_bp.route('/lookup-by-mobile/<mobile>', methods=['GET'])
@jwt_required()
def lookup_by_mobile(mobile):
    investor = Member.query.filter_by(mobile=mobile, approval_status='Approved').first()
    adviser = Adviser.query.filter_by(mobile=mobile).first()
    return jsonify(success_response({
        'is_investor': bool(investor),
        'is_adviser': bool(adviser),
        'investor_id': investor.investor_id if investor else None,
        'adviser_code': adviser.adviser_code if adviser else None,
        'full_name': investor.full_name if investor else (adviser.full_name if adviser else None),
        'will_reuse': bool(investor and not adviser),
        'code_to_reuse': investor.investor_id if (investor and not adviser) else None,
    })[0]), 200


@advisers_bp.route('/check-investor/<mobile>', methods=['GET'])
@jwt_required()
def check_investor_by_mobile(mobile):
    member = Member.query.filter_by(mobile=mobile, approval_status='Approved').first()
    if member:
        return jsonify(success_response({
            'found': True,
            'investor_id': member.investor_id,
            'full_name': member.full_name,
            'will_reuse_id': True,
        })[0]), 200
    return jsonify(success_response({'found': False})[0]), 200


@advisers_bp.route('/<int:adviser_id>', methods=['PUT'])
@jwt_required()
def update_adviser(adviser_id):
    claims = get_jwt()
    if claims.get('role') != 'superadmin':
        return jsonify(error_response('Unauthorized', 403)[0]), 403
    a = Adviser.query.get_or_404(adviser_id)
    data = request.get_json() or {}
    for f in ('full_name', 'mobile', 'email', 'rank_id', 'is_active', 'branch_id'):
        if f in data:
            setattr(a, f, data[f])
    db.session.commit()
    return jsonify(success_response(_adviser_payload(a), 'Adviser updated')[0]), 200


@advisers_bp.route('/<int:adviser_id>', methods=['DELETE'])
@jwt_required()
def delete_adviser(adviser_id):
    """Delete pending adviser registration (Approved Adviser tab — Delete)."""
    claims = get_jwt()
    if claims.get('role') not in ('superadmin', 'branchmanager'):
        return jsonify(error_response('Unauthorized', 403)[0]), 403

    adviser = Adviser.query.get_or_404(adviser_id)
    if adviser.is_active:
        return jsonify(error_response('Cannot delete an approved adviser')[0]), 400

    db.session.delete(adviser)
    db.session.commit()
    return jsonify(success_response({'id': adviser_id}, 'Adviser registration deleted')[0]), 200


@advisers_bp.route('/<int:adviser_id>/approve', methods=['POST'])
@jwt_required()
def approve_adviser(adviser_id):
    """Approve adviser → generate DEFAD credentials → display in toaster."""
    claims = get_jwt()
    role = claims.get('role')

    if role not in ('superadmin', 'branchmanager'):
        return jsonify(error_response('Unauthorized', 403)[0]), 403

    adviser = Adviser.query.get_or_404(adviser_id)
    data = request.get_json() or {}
    action = data.get('action', 'approve')

    if action in ('reject', 'delete'):
        db.session.delete(adviser)
        db.session.commit()
        return jsonify(success_response({'id': adviser_id}, 'Adviser registration deleted')[0]), 200

    import secrets
    from models.user import User
    from werkzeug.security import generate_password_hash

    username = (adviser.adviser_code or '').strip().upper()
    if not username:
        return jsonify(error_response('Adviser ID is missing — cannot create login')[0]), 400

    taken = User.query.filter(db.func.upper(User.username) == username).first()
    if taken and taken.mobile != adviser.mobile:
        return jsonify(error_response(
            f'Login username {username} is already assigned to another user'
        )[0]), 409

    password = secrets.token_hex(5)

    branch_id = adviser.branch_id or claims.get('branch_id')
    _base_email = adviser.email or f'{username.lower()}@defoex.com'
    _existing_email = User.query.filter_by(email=_base_email).first()
    adviser_email = _base_email if not _existing_email else f'{username.lower()}@defoex.com'
    password_hash = generate_password_hash(password)

    existing = User.query.filter_by(mobile=adviser.mobile).first()
    mobile_val = None if existing else adviser.mobile

    try:
        db.session.execute(text("""
            INSERT INTO users (username, email, password_hash, full_name, mobile,
                               role, branch_id, is_active, created_at, updated_at)
            VALUES (:u, :e, :p, :f, :m, 'advisor', :b, true, NOW(), NOW())
        """), {
            'u': username,
            'e': adviser_email,
            'p': password_hash,
            'f': adviser.full_name,
            'm': mobile_val,
            'b': branch_id,
        })
    except Exception as ex:
        print(f'User insert skipped: {ex}')
        db.session.rollback()

    adviser.is_active = True
    adviser.login_username = username.strip().upper()
    try:
        from utils.member_lookup import link_adviser_investor
        link_adviser_investor(adviser)
        db.session.commit()
    except Exception as ex:
        db.session.rollback()
        print(f'Adviser commit error: {ex}')

    adv_dict = _adviser_payload(adviser)
    return jsonify(success_response({
        **adv_dict,
        'credentials': {
            'username': username,
            'password': password,
            'message': (
                f'Congratulations Adviser Created! Username: {username} '
                f'Password: {password}'
            ),
        },
    }, f'Adviser approved — Username: {username}')[0]), 200


@advisers_bp.route('/<int:adviser_id>/blacklist', methods=['POST'])
@jwt_required()
def blacklist_adviser(adviser_id):
    """Admin only — blacklisted adviser cannot create investors."""
    claims = get_jwt()
    if claims.get('role') != 'superadmin':
        return jsonify(error_response('Only Admin can blacklist advisers', 403)[0]), 403

    adviser = Adviser.query.get_or_404(adviser_id)
    adviser.is_active = False
    if hasattr(adviser, 'is_blacklisted'):
        adviser.is_blacklisted = True
    db.session.commit()
    return jsonify(success_response(
        _adviser_payload(adviser),
        f'Adviser {adviser.adviser_code} blacklisted'
    )[0]), 200


@advisers_bp.route('/by-promoter/<promoter_code>', methods=['GET'])
@jwt_required()
def advisers_by_promoter(promoter_code):
    """
    Rank visibility (conditions 01–15):
    Promoter rank N → visible downline ranks N-1 down to 1.
    """
    promoter = Adviser.query.filter_by(adviser_code=promoter_code, is_active=True).first()
    if not promoter:
        return jsonify(error_response('Promoter not found', 404)[0]), 404

    max_visible_rank = promoter.rank_id - 1
    if max_visible_rank < 1:
        return jsonify(success_response([])[0]), 200

    counts = _investor_counts()
    advisers = Adviser.query.filter(
        Adviser.rank_id <= max_visible_rank,
        Adviser.is_active == True,
        Adviser.is_company_owner == False,
    ).all()
    return jsonify(success_response([_adviser_payload(a, counts) for a in advisers])[0]), 200


@advisers_bp.route('/allowed-rank/<promoter_code>', methods=['GET'])
@jwt_required()
def allowed_rank_for_promoter_route(promoter_code):
    """Return assignable ranks when registering under this promoter (rank N → ranks 1..N-1)."""
    promoter, err = find_promoter_adviser(promoter_code)
    if err:
        return jsonify(error_response(err, 404)[0]), 404

    rank_ids, err = allowed_ranks_for_promoter(promoter.rank_id)
    if err:
        return jsonify(error_response(err)[0]), 400

    max_rank = rank_ids[-1]
    return jsonify(success_response({
        'promoter_code': promoter.adviser_code,
        'promoter_name': promoter.full_name,
        'promoter_rank_id': promoter.rank_id,
        'promoter_rank_name': promoter.rank_name,
        'promoter_rank_display': rank_label(promoter.rank_id),
        'max_allowed_rank_id': max_rank,
        'allowed_rank_ids': rank_ids,
        'allowed_ranks': [{'id': r, 'label': rank_label(r)} for r in rank_ids],
        'allowed_rank_id': max_rank,
        'allowed_rank_name': RANKS.get(max_rank, 'SR'),
        'allowed_rank_display': rank_label(max_rank),
    })[0]), 200
