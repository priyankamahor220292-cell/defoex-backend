from extensions import db
from datetime import datetime
from utils.helpers import branch_manager_display_name

class Branch(db.Model):
    __tablename__ = 'branches'

    id = db.Column(db.Integer, primary_key=True)
    branch_code = db.Column(db.String(20), unique=True, nullable=False)
    branch_name = db.Column(db.String(200), nullable=False)
    address = db.Column(db.Text)
    city = db.Column(db.String(100))
    state = db.Column(db.String(100))
    pincode = db.Column(db.String(10))
    manager_name = db.Column(db.String(200))
    manager_email = db.Column(db.String(150))
    manager_mobile = db.Column(db.String(15))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'branch_code': self.branch_code,
            'branch_name': self.branch_name,
            'address': self.address,
            'city': self.city,
            'state': self.state,
            'pincode': self.pincode,
            'manager_name': branch_manager_display_name(self.manager_name),
            'manager_email': self.manager_email,
            'manager_mobile': self.manager_mobile,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
