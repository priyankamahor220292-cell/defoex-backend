from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models.notification import Notification
from extensions import db
from utils.helpers import success_response

notifications_bp = Blueprint('notifications', __name__, url_prefix='/api/notifications')


@notifications_bp.route('/', methods=['GET'])
@jwt_required()
def list_notifications():
    identity = get_jwt_identity()
    notifs = Notification.query.filter_by(user_id=int(identity))\
        .order_by(Notification.created_at.desc()).limit(50).all()
    unread = Notification.query.filter_by(user_id=int(identity), is_read=False).count()
    return jsonify(success_response({
        'items': [n.to_dict() for n in notifs],
        'unread_count': unread
    })[0]), 200


@notifications_bp.route('/mark-read', methods=['POST'])
@jwt_required()
def mark_read():
    identity = get_jwt_identity()
    Notification.query.filter_by(user_id=int(identity), is_read=False).update({'is_read': True})
    db.session.commit()
    return jsonify(success_response(message='All notifications marked as read')[0]), 200
