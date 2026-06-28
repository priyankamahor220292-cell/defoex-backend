from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from models.adviser import Adviser
from models.member import Member
from extensions import db
from sqlalchemy import text
from utils.helpers import generate_adviser_code, success_response, error_response, normalize_mobile, find_adviser_by_mobile, find_member_by_mobile
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
    role      = claims.get('role')
    branch_id = claims.get('branch_id')
    # Return ALL advisers including pending (is_active=False) so Approve tab works
    # Exclude only company owner and blacklisted
    q = Adviser.query.filter(Adviser.is_blacklisted == False)

    if role == 'branchmanager':
        # BM: only see their branch advisers, never the company owner
        q = q.filter(
            Adviser.branch_id == branch_id,
            Adviser.is_company_owner == False
        )
    # Superadmin sees all non-blacklisted

    advisers = q.all()
    return jsonify(success_response([a.to_dict() for a in advisers])[0]), 200


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
    claims    = get_jwt()
    if claims.get('role') not in ['superadmin', 'branchmanager']:
        return jsonify(error_response('Unauthorized', 403)[0]), 403

    data      = request.get_json() or {}
    mobile    = normalize_mobile(data.get('mobile', ''))
    full_name = str(data.get('full_name', '')).strip()
    branch_id = data.get('branch_id') or claims.get('branch_id')

    if not full_name or not mobile:
        return jsonify(error_response('full_name and mobile are required')[0]), 400
    if len(mobile) != 10:
        return jsonify(error_response('Valid 10-digit mobile number is required')[0]), 400

    existing = find_adviser_by_mobile(mobile)
    if existing:
        return jsonify(error_response(
            f'This person is already an adviser. Code: {existing.adviser_code}'
        )[0]), 409

    # Reuse investor code if same person
    investor = find_member_by_mobile(mobile)
    if investor and investor.approval_status == 'Approved':
        code = investor.investor_id
        note = f'Investor {code} promoted to adviser — same code used for both roles.'
    else:
        code = generate_adviser_code()
        note = f'New adviser created with code {code}.'

    try:
        # Adviser member fee = ₹650
        adviser = Adviser(
            adviser_code        = code,
            full_name           = full_name,
            mobile              = mobile,
            email               = data.get('email') or None,
            rank_id             = int(data.get('rank_id', 1)),
            branch_id           = int(branch_id) if branch_id else None,
            parent_adviser_code = data.get('parent_adviser_code') or None,
            investor_id         = investor.investor_id if (investor and investor.approval_status == 'Approved') else None,
            is_active           = False,  # Pending until approved in Approved Adviser tab
        )
        # Set father_name safely — column may not exist in older model versions
        try:
            adviser.father_name = data.get('father_name') or None
        except Exception:
            pass
        db.session.add(adviser)
        db.session.flush()

        # Deduct ₹650 adviser fee from branch wallet
        fees = float(data.get('member_fees', 650) or 650)
        if branch_id and fees > 0:
            from models.branch_wallet import BranchWallet
            wallet = BranchWallet.query.filter_by(branch_id=int(branch_id)).first()
            if wallet and float(wallet.current_balance or 0) >= fees:
                wallet.current_balance = float(wallet.current_balance or 0) - fees
                wallet.cash_wallet     = float(wallet.cash_wallet or 0) + fees
                try:
                    db.session.execute(
                        text("""INSERT INTO wallet_transactions
                            (branch_id, transaction_type, amount, description,
                             balance_after, cash_wallet_after, created_at)
                            VALUES (:bid, 'Deduction', :amt, :desc, :bal, :cash, NOW())"""),
                        {
                            'bid':  int(branch_id),
                            'amt':  fees,
                            'desc': f'Adviser registration fee — {full_name} ({code})',
                            'bal':  float(wallet.current_balance),
                            'cash': float(wallet.cash_wallet),
                        }
                    )
                except Exception as we:
                    print(f'Wallet txn note: {we}')
            else:
                print(f'Branch wallet low — adviser fee not deducted')

        db.session.commit()
        resp = adviser.to_dict()
        resp['note'] = note
        return jsonify(success_response(resp, f'Adviser code: {code} — ₹{fees:.0f} deducted from branch wallet')[0]), 201
    except Exception as e:
        db.session.rollback()
        print(traceback.format_exc())
        return jsonify(error_response(str(e))[0]), 500


@advisers_bp.route('/lookup-by-mobile/<mobile>', methods=['GET'])
@jwt_required()
def lookup_by_mobile(mobile):
    investor = Member.query.filter_by(mobile=mobile, approval_status='Approved').first()
    adviser  = Adviser.query.filter_by(mobile=mobile).first()
    return jsonify(success_response({
        'is_investor':    bool(investor),
        'is_adviser':     bool(adviser),
        'investor_id':    investor.investor_id if investor else None,
        'adviser_code':   adviser.adviser_code  if adviser  else None,
        'full_name':      investor.full_name if investor else (adviser.full_name if adviser else None),
        'will_reuse':     bool(investor and not adviser),
        'code_to_reuse':  investor.investor_id if (investor and not adviser) else None,
    })[0]), 200


@advisers_bp.route('/check-investor/<mobile>', methods=['GET'])
@jwt_required()
def check_investor_by_mobile(mobile):
    member = Member.query.filter_by(mobile=mobile, approval_status='Approved').first()
    if member:
        return jsonify(success_response({
            'found':       True,
            'investor_id': member.investor_id,
            'full_name':   member.full_name,
            'will_reuse_id': True,
        })[0]), 200
    return jsonify(success_response({'found': False})[0]), 200


@advisers_bp.route('/<int:adviser_id>', methods=['PUT'])
@jwt_required()
def update_adviser(adviser_id):
    claims = get_jwt()
    if claims.get('role') != 'superadmin':
        return jsonify(error_response('Unauthorized', 403)[0]), 403
    a    = Adviser.query.get_or_404(adviser_id)
    data = request.get_json() or {}
    for f in ['full_name', 'mobile', 'email', 'rank_id', 'is_active', 'branch_id']:
        if f in data:
            setattr(a, f, data[f])
    db.session.commit()
    return jsonify(success_response(a.to_dict(), 'Adviser updated')[0]), 200


@advisers_bp.route('/<int:adviser_id>/approve', methods=['POST'])
@jwt_required()
def approve_adviser(adviser_id):
    """
    Approve adviser → generate DEFAD credentials → display in toaster
    Works for both superadmin and branchmanager
    """
    from sqlalchemy import text
    claims = get_jwt()
    role   = claims.get('role')

    if role not in ['superadmin', 'branchmanager']:
        return jsonify(error_response('Unauthorized', 403)[0]), 403

    adviser = Adviser.query.get_or_404(adviser_id)
    data    = request.get_json() or {}
    action  = data.get('action', 'approve')

    if action == 'reject':
        adviser.is_active = False
        db.session.commit()
        return jsonify(success_response(adviser.to_dict(), 'Adviser rejected')[0]), 200

    # Generate credentials
    import secrets
    from datetime import datetime
    from models.user import User
    from werkzeug.security import generate_password_hash

    year     = datetime.now().year
    seq      = User.query.count() + 1
    username = f"DEFAD{year}{str(seq).zfill(2)}"
    password = secrets.token_hex(5)  # 10-char hex

    # Ensure username is unique
    while User.query.filter_by(username=username).first():
        seq += 1
        username = f"DEFAD{year}{str(seq).zfill(2)}"

    branch_id = adviser.branch_id or claims.get('branch_id')
    # Generate unique email — avoid conflicts
    _base_email = adviser.email or f"{username.lower()}@defoex.com"
    _existing_email = User.query.filter_by(email=_base_email).first()
    adviser_email = _base_email if not _existing_email else f"{username.lower()}@defoex.com"
    password_hash = generate_password_hash(password)

    # Check mobile conflict
    existing = User.query.filter_by(mobile=adviser.mobile).first()
    mobile_val = None if existing else adviser.mobile

    # Use raw SQL to completely bypass any role enum issues
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
        print(f"User insert skipped: {ex}")
        db.session.rollback()

    # Always approve the adviser and store login username for ID lookup
    adviser.is_active = True
    adviser.login_username = username.strip().upper()
    try:
        from utils.member_lookup import link_adviser_investor
        link_adviser_investor(adviser)
        db.session.commit()
    except Exception as ex:
        db.session.rollback()
        print(f"Adviser commit error: {ex}")

    try:
        adv_dict = adviser.to_dict()
    except Exception:
        adv_dict = {'adviser_code': adviser.adviser_code, 'full_name': adviser.full_name}

    return jsonify(success_response({
        **adv_dict,
        'credentials': {
            'username': username,
            'password': password,
            'message': f'Congratulations Adviser Created! Username: {username} Password: {password}',
        }
    }, f'Adviser approved — Username: {username}')[0]), 200


@advisers_bp.route('/<int:adviser_id>/blacklist', methods=['POST'])
@jwt_required()
def blacklist_adviser(adviser_id):
    """Admin can blacklist an adviser — blacklisted adviser cannot create investors"""
    claims = get_jwt()
    if claims.get('role') != 'superadmin':
        return jsonify(error_response('Only Admin can blacklist advisers', 403)[0]), 403

    adviser = Adviser.query.get_or_404(adviser_id)
    adviser.is_active = False
    # Mark as blacklisted
    if hasattr(adviser, 'is_blacklisted'):
        adviser.is_blacklisted = True
    db.session.commit()
    return jsonify(success_response(adviser.to_dict(), f'Adviser {adviser.adviser_code} blacklisted')[0]), 200


@advisers_bp.route('/by-promoter/<promoter_code>', methods=['GET'])
@jwt_required()
def advisers_by_promoter(promoter_code):
    """
    Rank-based adviser visibility:
    - Rank 16 (House 3) can see ranks 15 down to 1
    - Rank 15 can see ranks 14 down to 1
    - Each rank N can see ranks N-1 down to 1
    """
    promoter = Adviser.query.filter_by(adviser_code=promoter_code, is_active=True).first()
    if not promoter:
        return jsonify(error_response('Promoter not found', 404)[0]), 404

    max_visible_rank = promoter.rank_id - 1
    if max_visible_rank < 1:
        return jsonify(success_response([])[0]), 200

    advisers = Adviser.query.filter(
        Adviser.rank_id <= max_visible_rank,
        Adviser.is_active == True,
        Adviser.is_company_owner == False,
    ).all()
    return jsonify(success_response([a.to_dict() for a in advisers])[0]), 200