from extensions import db
from utils.datetime_utils import now_ist, isoformat_ist

class Notification(db.Model):
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text)
    notification_type = db.Column(db.String(20), default='Info')
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=now_ist)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'branch_id': self.branch_id,
            'title': self.title,
            'message': self.message,
            'notification_type': self.notification_type,
            'is_read': self.is_read,
            'created_at': isoformat_ist(self.created_at)
        }