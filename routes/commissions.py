from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from models.commission import Commission
from extensions import db
from utils.helpers import success_response, error_response

commissions_bp = Blueprint('commissions', __name__, url_prefix='/api/commissions')


@commissions_bp.route('/', methods=['GET'])
@jwt_required()
def list_commissions():
    claims = get_jwt()
    page = request.args.get('page', 1, type=int)
    adviser_code = request.args.get('adviser_code')
    status = request.args.get('status')

    query = Commission.query
    if adviser_code:
        query = query.filter_by(adviser_code=adviser_code)
    if status:
        query = query.filter_by(status=status)

    paginated = query.order_by(Commission.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return jsonify(success_response({
        'items': [c.to_dict() for c in paginated.items],
        'total': paginated.total,
        'pages': paginated.pages
    })[0]), 200


@commissions_bp.route('/chart', methods=['GET'])
@jwt_required()
def commission_chart():
    """Return commission rate chart"""
    from models.commission import MIS_COMMISSION_RATES, SIS_COMMISSION_RATES
    return jsonify(success_response({
        'mis': MIS_COMMISSION_RATES,
        'sis': SIS_COMMISSION_RATES
    })[0]), 200
