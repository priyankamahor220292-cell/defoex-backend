from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from models.adviser import Adviser
from extensions import db
from utils.helpers import generate_adviser_code, success_response, error_response

advisers_bp = Blueprint('advisers', __name__, url_prefix='/api/advisers')


@advisers_bp.route('/', methods=['GET'])
@jwt_required()
def list_advisers():
    claims = get_jwt()
    branch_id = claims.get('branch_id')
    query = Adviser.query.filter_by(is_active=True)
    if branch_id and claims.get('role') == 'branchmanager':
        query = query.filter_by(branch_id=branch_id)
    return jsonify(success_response([a.to_dict() for a in query.all()])[0]), 200


@advisers_bp.route('/<code>', methods=['GET'])
@jwt_required()
def get_adviser(code):
    adviser = Adviser.query.filter_by(adviser_code=code).first()
    if not adviser:
        return jsonify(error_response('Adviser not found', 404)[0]), 404
    return jsonify(success_response(adviser.to_dict())[0]), 200


@advisers_bp.route('/', methods=['POST'])
@jwt_required()
def create_adviser():
    claims = get_jwt()
    if claims.get('role') not in ['superadmin', 'branchmanager']:
        return jsonify(error_response('Unauthorized', 403)[0]), 403

    data = request.get_json()
    code = generate_adviser_code()
    adviser = Adviser(
        adviser_code=code,
        full_name=data['full_name'],
        mobile=data['mobile'],
        email=data.get('email'),
        rank_id=data.get('rank_id', 1),
        branch_id=data.get('branch_id') or claims.get('branch_id'),
        parent_adviser_code=data.get('parent_adviser_code')
    )
    db.session.add(adviser)
    db.session.commit()
    return jsonify(success_response(adviser.to_dict(), f'Adviser created with code {code}')[0]), 201


@advisers_bp.route('/<int:adviser_id>', methods=['PUT'])
@jwt_required()
def update_adviser(adviser_id):
    claims = get_jwt()
    if claims.get('role') != 'superadmin':
        return jsonify(error_response('Unauthorized', 403)[0]), 403

    adviser = Adviser.query.get_or_404(adviser_id)
    data = request.get_json()
    for field in ['full_name', 'mobile', 'email', 'rank_id', 'is_active']:
        if field in data:
            setattr(adviser, field, data[field])
    db.session.commit()
    return jsonify(success_response(adviser.to_dict(), 'Adviser updated')[0]), 200
