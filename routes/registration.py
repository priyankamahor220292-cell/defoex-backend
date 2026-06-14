from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from models.member import Member
from models.adviser import Adviser
from extensions import db
from utils.helpers import (
    generate_investor_id, calculate_age,
    success_response, error_response, paginate_query
)
from datetime import datetime, date

registration_bp = Blueprint('registration', __name__, url_prefix='/api/registration')


def safe_date(val):
    """Parse date string safely, return None if invalid"""
    if not val:
        return None
    try:
        # handle both YYYY-MM-DD and MM/DD/YYYY
        if '/' in str(val):
            return datetime.strptime(val, '%m/%d/%Y').date()
        return date.fromisoformat(str(val))
    except Exception:
        return None


def safe_decimal(val):
    """Convert to decimal safely, return None if invalid"""
    if val is None or val == '' or val == 'null':
        return None
    try:
        return float(val)
    except Exception:
        return None


def safe_enum(val, allowed, default=None):
    """Return val if in allowed list, else default"""
    if val and val in allowed:
        return val
    return default


@registration_bp.route('/check-adviser', methods=['POST'])
@jwt_required()
def check_adviser():
    data = request.get_json() or {}
    code = data.get('adviser_code', '').strip()
    if not code:
        return jsonify(error_response('Adviser code required')[0]), 400
    adviser = Adviser.query.filter_by(adviser_code=code, is_active=True).first()
    if not adviser:
        return jsonify(error_response('Adviser ID not found or inactive', 404)[0]), 404
    return jsonify(success_response(adviser.to_dict(), 'Adviser found')[0]), 200


@registration_bp.route('/new', methods=['POST'])
@jwt_required()
def new_registration():
    claims = get_jwt()
    branch_id = claims.get('branch_id')
    data = request.get_json() or {}

    # Validate required
    required = ['adviser_code', 'full_name', 'mobile', 'aadhar_number']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify(error_response(f"Missing required fields: {', '.join(missing)}")[0]), 400

    # Check uniqueness
    if Member.query.filter_by(mobile=str(data['mobile'])).first():
        return jsonify(error_response('Mobile number already registered')[0]), 409
    if data.get('aadhar_number') and Member.query.filter_by(aadhar_number=str(data['aadhar_number'])).first():
        return jsonify(error_response('Aadhar number already registered')[0]), 409

    # Validate adviser
    adviser = Adviser.query.filter_by(adviser_code=data['adviser_code'], is_active=True).first()
    if not adviser:
        return jsonify(error_response('Invalid Adviser ID')[0]), 400

    # Parse dates
    dob = safe_date(data.get('date_of_birth'))
    age = calculate_age(dob) if dob else (safe_decimal(data.get('age')) or None)
    nominee_age = safe_decimal(data.get('nominee_age'))

    investor_id = generate_investor_id()

    try:
        member = Member(
            investor_id=investor_id,
            salutation=data.get('salutation'),
            full_name=str(data['full_name']).strip(),
            father_spouse_name=data.get('father_spouse_name'),
            date_of_birth=dob,
            age=int(age) if age else None,
            gender=safe_enum(data.get('gender'), ['Male','Female','Other']),
            marital_status=safe_enum(data.get('marital_status'), ['Single','Married','Divorced','Widowed']),
            nationality=data.get('nationality') or 'Indian',
            mobile=str(data['mobile']).strip(),
            phone_office=data.get('phone_office') or None,
            phone_residence=data.get('phone_residence') or None,
            email=data.get('email') or None,
            is_senior_citizen=bool(data.get('is_senior_citizen', False)),
            is_special_roi=bool(data.get('is_special_roi', False)),

            corr_address=data.get('corr_address') or None,
            corr_state=data.get('corr_state') or None,
            corr_city=data.get('corr_city') or None,
            corr_pincode=data.get('corr_pincode') or None,

            perm_address=data.get('perm_address') or data.get('corr_address') or None,
            perm_state=data.get('perm_state') or data.get('corr_state') or None,
            perm_city=data.get('perm_city') or data.get('corr_city') or None,
            perm_pincode=data.get('perm_pincode') or data.get('corr_pincode') or None,
            same_as_corr=bool(data.get('same_as_corr', False)),

            aadhar_number=str(data['aadhar_number']).strip(),
            pan_number=data.get('pan_number') or None,
            passport_number=data.get('passport_number') or None,
            voter_id=data.get('voter_id') or None,
            driving_license=data.get('driving_license') or None,
            verification_doc_type=data.get('verification_doc_type') or None,

            nominee_name=data.get('nominee_name') or None,
            nominee_age=int(nominee_age) if nominee_age else None,
            nominee_relationship=data.get('nominee_relationship') or None,
            nominee_address=data.get('nominee_address') or None,
            nominee_state=data.get('nominee_state') or None,
            nominee_city=data.get('nominee_city') or None,
            nominee_pincode=data.get('nominee_pincode') or None,
            nominee_same_as_member=bool(data.get('nominee_same_as_member', False)),

            bank_name=data.get('bank_name') or None,
            account_number=data.get('account_number') or None,
            ifsc_code=data.get('ifsc_code') or None,
            bank_branch_name=data.get('bank_branch_name') or None,
            upi_id=data.get('upi_id') or None,

            occupation=data.get('occupation') or None,
            professional_details=data.get('professional_details') or None,
            annual_income=safe_decimal(data.get('annual_income')),
            family_income=safe_decimal(data.get('family_income')),

            adviser_code=str(data['adviser_code']).strip(),
            promoter_post=data.get('promoter_post') or None,
            member_type=safe_enum(data.get('member_type'), ['Customer','Promoter Member'], 'Customer'),
            member_fees=safe_decimal(data.get('member_fees')) or 10,
            promoter_fees=safe_decimal(data.get('promoter_fees')) or 0,
            payment_mode=safe_enum(data.get('payment_mode'), ['Cash','Cheque','DD','UPI','NEFT'], 'Cash'),
            cheque_dd_details=data.get('cheque_dd_details') or None,
            cheque_dd_date=safe_date(data.get('cheque_dd_date')),
            reg_bank_name=data.get('reg_bank_name') or None,
            company_account=data.get('company_account') or None,
            date_of_joining=safe_date(data.get('date_of_joining')) or date.today(),

            branch_id=branch_id,
            approval_status='Pending'
        )

        db.session.add(member)
        db.session.commit()
        return jsonify(success_response(member.to_dict(), 'Registration submitted for approval')[0]), 201

    except Exception as e:
        db.session.rollback()
        import traceback
        print("Registration error:", traceback.format_exc())
        return jsonify(error_response(f'Registration failed: {str(e)}')[0]), 500


@registration_bp.route('/approve/<int:member_id>', methods=['POST'])
@jwt_required()
def approve_registration(member_id):
    claims = get_jwt()
    if claims.get('role') not in ['branchmanager', 'superadmin']:
        return jsonify(error_response('Unauthorized', 403)[0]), 403

    identity = get_jwt_identity()
    data = request.get_json() or {}
    action = data.get('action')

    member = Member.query.get_or_404(member_id)

    if action == 'approve':
        member.approval_status = 'Approved'
        member.approved_by = int(identity)
        member.approved_at = datetime.utcnow()
        msg = f'Registration approved for {member.full_name}'
    elif action == 'reject':
        member.approval_status = 'Rejected'
        msg = f'Registration rejected for {member.full_name}'
    else:
        return jsonify(error_response('Invalid action. Use approve or reject')[0]), 400

    db.session.commit()
    return jsonify(success_response(member.to_dict(), msg)[0]), 200


@registration_bp.route('/pending', methods=['GET'])
@jwt_required()
def pending_registrations():
    claims = get_jwt()
    branch_id = claims.get('branch_id')
    page = request.args.get('page', 1, type=int)

    query = Member.query.filter_by(approval_status='Pending')
    if branch_id:
        query = query.filter_by(branch_id=branch_id)

    result = paginate_query(query.order_by(Member.created_at.desc()), page)
    result['items'] = [m.to_dict() for m in result['items']]
    return jsonify(success_response(result)[0]), 200


@registration_bp.route('/list', methods=['GET'])
@jwt_required()
def list_investors():
    claims = get_jwt()
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

    result = paginate_query(query.order_by(Member.date_of_joining.desc()), page)

    items = []
    for m in result['items']:
        has_plan = len(m.investments) > 0
        d = m.to_dict()
        d['status'] = 'Active' if has_plan else 'Not Active'
        items.append(d)

    result['items'] = items
    return jsonify(success_response(result)[0]), 200


@registration_bp.route('/<investor_id>', methods=['GET'])
@jwt_required()
def get_investor(investor_id):
    member = Member.query.filter_by(investor_id=investor_id).first()
    if not member:
        return jsonify(error_response('Investor not found', 404)[0]), 404
    return jsonify(success_response(member.to_dict())[0]), 200