from extensions import db
from werkzeug.security import generate_password_hash, check_password_hash
from utils.helpers import branch_manager_display_name
from utils.datetime_utils import now_ist, isoformat_ist

class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(200), nullable=False)
    mobile = db.Column(db.String(15))
    role = db.Column(db.String(20), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=now_ist)
    updated_at = db.Column(db.DateTime, default=now_ist, onupdate=now_ist)

    branch = db.relationship('Branch', backref='users', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        full_name = self.full_name
        if self.role == 'branchmanager':
            full_name = branch_manager_display_name(full_name)
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'full_name': full_name,
            'mobile': self.mobile,
            'role': self.role,
            'branch_id': self.branch_id,
            'is_active': self.is_active,
            'created_at': isoformat_ist(self.created_at)
        }