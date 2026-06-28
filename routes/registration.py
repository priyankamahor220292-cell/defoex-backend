from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from models.member import Member
from models.adviser import Adviser
from models.investment import Investment
from extensions import db
from utils.helpers import (
    generate_investor_id, calculate_age,
    success_response, error_response, paginate_query,
    normalize_mobile, find_member_by_mobile,
)
from datetime import datetime, date
import traceback

registration_bp = Blueprint('registration', __name__, url_prefix='/api/registration')


def safe_date(val):
    if not val:
        return None
    try:
        if '/' in str(val):
            return datetime.strptime(str(val), '%m/%d/%Y').date()
        return date.fromisoformat(str(val))
    except Exception:
        return None


def safe_decimal(val):
    if val is None or val == '' or val == 'null':
        return None
    try:
        return float(val)
    except Exception:
        return None


def safe_enum(val, allowed, default=None):
    if val and val in allowed:
        return val
    return default


@registration_bp.route('/check-adviser', methods=['POST'])
@jwt_required()
def check_adviser():
    data = request.get_json() or {}
    code = data.get('adviser_code', '').strip()
    if not code:
        return jsonify(error_response('Please enter an adviser code')[0]), 400

    # Block IRN codes
    if 'DFX-IRN-' in code.upper():
        return jsonify(error_response(
            'That is an Investment Bond number, not an adviser code. '
            'Adviser codes look like DFX-2026-000001.'
        )[0]), 400

    # Find adviser — try code, login username, or DEFAD user
    from utils.member_lookup import find_adviser_by_code_or_login, find_adviser_for_user
    from models.user import User

    adviser = find_adviser_by_code_or_login(code)
    if not adviser:
        user = User.query.filter(db.func.upper(User.username) == code.upper()).first()
        if user:
            adviser = find_adviser_for_user(user)
    if not adviser:
        adviser = Adviser.query.filter_by(adviser_code=code, is_active=True).first()

    # Try old ADV format if not found  (DFX-ADV-2026-000001)
    if not adviser and not code.startswith('DFX-ADV-'):
        adviser = Adviser.query.filter_by(
            adviser_code='DFX-ADV-' + code.replace('DFX-', '', 1),
            is_active=True
        ).first()

    if not adviser:
        # Show available codes to help the user
        codes = [a.adviser_code for a in
                 Adviser.query.filter_by(is_active=True).limit(10).all()]
        msg = f'Adviser code "{code}" not found.'
        if codes:
            msg += f' Available codes: {", ".join(codes)}'
        return jsonify(error_response(msg, 404)[0]), 404

    from utils.rank_helpers import allowed_ranks_for_promoter, rank_label

    promoter_rank = int(adviser.rank_id or 1)
    payload = adviser.to_dict()
    payload['rank_id'] = promoter_rank
    rank_ids, rank_err = allowed_ranks_for_promoter(promoter_rank)
    payload['promoter_rank_id'] = promoter_rank
    payload['promoter_rank_display'] = rank_label(promoter_rank)
    if rank_ids:
        max_rank = rank_ids[-1]
        payload['max_allowed_rank_id'] = max_rank
        payload['allowed_rank_ids'] = rank_ids
        payload['allowed_ranks'] = [
            {'id': r, 'label': rank_label(r)} for r in rank_ids
        ]
        payload['allowed_rank_id'] = max_rank
        payload['allowed_rank_display'] = rank_label(max_rank)
    else:
        payload['allowed_rank_error'] = rank_err

    return jsonify(success_response(payload, 'Adviser verified')[0]), 200


@registration_bp.route('/new', methods=['POST'])
@jwt_required()
def new_registration():
    claims    = get_jwt()
    branch_id = claims.get('branch_id')
    data      = request.get_json() or {}

    required = ['adviser_code', 'full_name', 'mobile', 'aadhar_number']
    missing  = [f for f in required if not data.get(f)]
    if missing:
        return jsonify(error_response(f"Missing required fields: {', '.join(missing)}")[0]), 400

    mobile = normalize_mobile(data.get('mobile'))
    if not mobile or len(mobile) != 10:
        return jsonify(error_response('Valid 10-digit mobile number is required')[0]), 400

    existing_member = find_member_by_mobile(mobile)
    if existing_member:
        return jsonify(error_response(
            f'Mobile number already registered as investor {existing_member.investor_id}'
        )[0]), 409
    if data.get('aadhar_number') and Member.query.filter_by(aadhar_number=str(data['aadhar_number'])).first():
        return jsonify(error_response('Aadhar number already registered')[0]), 409

    adviser = Adviser.query.filter_by(adviser_code=data['adviser_code'], is_active=True).first()
    if not adviser:
        return jsonify(error_response('Invalid Adviser Code')[0]), 400

    if not branch_id and adviser.branch_id:
        branch_id = adviser.branch_id

    dob = safe_date(data.get('date_of_birth'))
    age = calculate_age(dob) if dob else None
    nominee_age = safe_decimal(data.get('nominee_age'))

    investor_id = generate_investor_id()

    try:
        member = Member(
            investor_id      = investor_id,
            salutation       = data.get('salutation'),
            full_name        = str(data['full_name']).strip(),
            father_spouse_name = data.get('father_spouse_name'),
            date_of_birth    = dob,
            age              = int(age) if age else None,
            gender           = safe_enum(data.get('gender'), ['Male','Female','Other']),
            marital_status   = safe_enum(data.get('marital_status'), ['Single','Married','Divorced','Widowed']),
            nationality      = data.get('nationality') or 'Indian',
            mobile           = mobile,
            phone_office     = data.get('phone_office') or None,
            phone_residence  = data.get('phone_residence') or None,
            email            = data.get('email') or None,
            is_senior_citizen= bool(data.get('is_senior_citizen', False)),
            is_special_roi   = bool(data.get('is_special_roi', False)),
            corr_address     = data.get('corr_address') or None,
            corr_state       = data.get('corr_state') or None,
            corr_city        = data.get('corr_city') or None,
            corr_pincode     = data.get('corr_pincode') or None,
            perm_address     = data.get('perm_address') or data.get('corr_address') or None,
            perm_state       = data.get('perm_state') or data.get('corr_state') or None,
            perm_city        = data.get('perm_city') or data.get('corr_city') or None,
            perm_pincode     = data.get('perm_pincode') or data.get('corr_pincode') or None,
            same_as_corr     = bool(data.get('same_as_corr', False)),
            aadhar_number    = str(data['aadhar_number']).strip(),
            pan_number       = data.get('pan_number') or None,
            passport_number  = data.get('passport_number') or None,
            voter_id         = data.get('voter_id') or None,
            driving_license  = data.get('driving_license') or None,
            verification_doc_type = data.get('verification_doc_type') or None,
            nominee_name     = data.get('nominee_name') or None,
            nominee_age      = int(nominee_age) if nominee_age else None,
            nominee_relationship = data.get('nominee_relationship') or None,
            nominee_address  = data.get('nominee_address') or None,
            nominee_state    = data.get('nominee_state') or None,
            nominee_city     = data.get('nominee_city') or None,
            nominee_pincode  = data.get('nominee_pincode') or None,
            bank_name        = data.get('bank_name') or None,
            account_number   = data.get('account_number') or None,
            ifsc_code        = data.get('ifsc_code') or None,
            bank_branch_name = data.get('bank_branch_name') or None,
            upi_id           = data.get('upi_id') or None,
            occupation       = data.get('occupation') or None,
            professional_details = data.get('professional_details') or None,
            annual_income    = safe_decimal(data.get('annual_income')),
            family_income    = safe_decimal(data.get('family_income')),
            adviser_code     = str(data['adviser_code']).strip(),
            promoter_post    = data.get('promoter_post') or None,
            member_type      = safe_enum(data.get('member_type', 'Investor'), ['Investor','Customer','Promoter Member'], 'Investor'),
            member_fees      = safe_decimal(data.get('member_fees')) or 10,
            promoter_fees    = safe_decimal(data.get('promoter_fees')) or 0,
            payment_mode     = safe_enum(data.get('payment_mode'), ['Cash','Cheque','DD','UPI','NEFT'], 'Cash'),
            cheque_dd_details= data.get('cheque_dd_details') or None,
            cheque_dd_date   = safe_date(data.get('cheque_dd_date')),
            reg_bank_name    = data.get('reg_bank_name') or None,
            company_account  = data.get('company_account') or None,
            date_of_joining  = safe_date(data.get('date_of_joining')) or date.today(),
            branch_id        = branch_id,
            approval_status  = 'Pending',
        )
        db.session.add(member)
        db.session.flush()

        # Auto-approve + generate DEFIN username/password on successful create
        from utils.investor_credentials import finalize_investor_registration
        identity = get_jwt_identity()
        creds, finalize_err = finalize_investor_registration(member, identity)
        if finalize_err:
            db.session.rollback()
            return jsonify(error_response(finalize_err)[0]), 400

        resp = member.to_dict()
        resp['credentials'] = creds
        msg = f'Investor created — ID: {investor_id}'
        if creds.get('password'):
            msg += f' — Username: {creds["username"]}'
        return jsonify(success_response(resp, msg)[0]), 201

    except Exception as e:
        db.session.rollback()
        print("Registration error:", traceback.format_exc())
        return jsonify(error_response(f'Registration failed: {str(e)}')[0]), 500


@registration_bp.route('/approve/<int:member_id>', methods=['POST'])
@jwt_required()
def approve_registration(member_id):
    claims = get_jwt()
    if claims.get('role') not in ('branchmanager', 'superadmin'):
        return jsonify(error_response('Unauthorized', 403)[0]), 403

    identity = get_jwt_identity()
    data = request.get_json() or {}
    action = data.get('action')
    member = Member.query.get_or_404(member_id)

    if action == 'approve':
        from utils.investor_credentials import finalize_investor_registration
        creds, err = finalize_investor_registration(member, identity)
        if err:
            return jsonify(error_response(err)[0]), 400
        msg = f'Registration approved for {member.full_name}'
        if creds.get('password'):
            msg += f' — Username: {creds["username"]}'
    elif action == 'reject':
        member.approval_status = 'Rejected'
        db.session.commit()
        msg = f'Registration rejected for {member.full_name}'
        creds = None
    else:
        return jsonify(error_response('Invalid action. Use approve or reject')[0]), 400

    resp = member.to_dict()
    if creds:
        resp['credentials'] = creds
    return jsonify(success_response(resp, msg)[0]), 200


@registration_bp.route('/pending', methods=['GET'])
@jwt_required()
def pending_registrations():
    claims    = get_jwt()
    branch_id = claims.get('branch_id')
    page      = request.args.get('page', 1, type=int)

    role  = claims.get('role', '')
    query = Member.query.filter_by(approval_status='Pending')
    if branch_id:
        query = query.filter_by(branch_id=branch_id)
    elif role == 'branchmanager':
        return jsonify(error_response('Branch not assigned', 403)[0]), 403

    result         = paginate_query(query.order_by(Member.created_at.desc()), page)
    result['items']= [m.to_dict() for m in result['items']]
    return jsonify(success_response(result)[0]), 200


@registration_bp.route('/list', methods=['GET'])
@jwt_required()
def list_investors():
    """List approved investors with optional date range filter"""
    try:
        claims    = get_jwt()
        branch_id = claims.get('branch_id')
        date_from = request.args.get('date_from')
        date_to   = request.args.get('date_to')
        page      = request.args.get('page', 1, type=int)

        query = Member.query.filter_by(approval_status='Approved')
        if branch_id and claims.get('role') == 'branchmanager':
            query = query.filter_by(branch_id=branch_id)

        if date_from:
            df = safe_date(date_from)
            if df:
                query = query.filter(Member.date_of_joining >= df)
        if date_to:
            dt = safe_date(date_to)
            if dt:
                query = query.filter(Member.date_of_joining <= dt)

        paginated = query.order_by(Member.date_of_joining.desc()).paginate(
            page=page, per_page=20, error_out=False)

        items = []
        for m in paginated.items:
            try:
                # Use a direct count instead of lazy load to avoid cascade issues
                has_plan = Investment.query.filter_by(
                    investor_id=m.investor_id,
                    approval_status='Approved'
                ).count() > 0
            except Exception:
                has_plan = False

            items.append({
                'id':             m.id,
                'investor_id':    m.investor_id,
                'full_name':      m.full_name,
                'mobile':         m.mobile,
                'email':          m.email,
                'corr_city':      m.corr_city,
                'corr_state':     m.corr_state,
                'adviser_code':   m.adviser_code,
                'member_type':    m.member_type,
                'date_of_joining':m.date_of_joining.isoformat() if m.date_of_joining else None,
                'approval_status':m.approval_status,
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
        return jsonify(error_response(f'Failed to list investors: {str(e)}')[0]), 500


@registration_bp.route('/<investor_id>', methods=['GET'])
@jwt_required()
def get_investor(investor_id):
    member = Member.query.filter_by(investor_id=investor_id).first()
    if not member:
        return jsonify(error_response('Investor not found', 404)[0]), 404
    return jsonify(success_response(member.to_dict())[0]), 200


@registration_bp.route('/<int:member_id>/blacklist', methods=['POST'])
@jwt_required()
def blacklist_investor(member_id):
    """Admin only — blacklist investor. Blacklisted investors cannot have new plans."""
    claims = get_jwt()
    if claims.get('role') != 'superadmin':
        return jsonify(error_response('Only Admin can blacklist investors', 403)[0]), 403
    member = Member.query.get_or_404(member_id)
    member.approval_status = 'Rejected'
    db.session.commit()
    return jsonify(success_response(member.to_dict(), f'{member.full_name} blacklisted')[0]), 200