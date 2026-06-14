from extensions import db
from datetime import datetime

RANKS = {
    1: 'SR',   # Senior Representative
    2: 'SO',   # Sales Officer
    3: 'SD',   # Sales Director
    4: 'SI',   # Sales Incharge
    5: 'DO',   # District Officer
    6: 'RO',   # Regional Officer
    7: 'ZO',   # Zonal Officer
    8: 'EM',   # Executive Member
    9: 'EM I', # Executive Member I
    10: 'EM II',
    11: 'EM R',
    12: 'EM C',
    13: 'House 1',
    14: 'House 2',
    15: 'House 3',
    16: 'House 4',
    17: 'House 5',
    18: 'House 6',
    19: 'House 7',
    20: 'House 8',  # Company Owner Rank
}

class Adviser(db.Model):
    __tablename__ = 'advisers'

    id = db.Column(db.Integer, primary_key=True)
    adviser_code = db.Column(db.String(20), unique=True, nullable=False)
    full_name = db.Column(db.String(200), nullable=False)
    mobile = db.Column(db.String(15), unique=True, nullable=False)
    email = db.Column(db.String(150))
    rank_id = db.Column(db.Integer, default=1)  # 1=SR ... 20=House8
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=True)
    parent_adviser_code = db.Column(db.String(20), nullable=True)  # upline adviser
    is_company_owner = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    branch = db.relationship('Branch', backref='advisers', lazy=True)

    @property
    def rank_name(self):
        return RANKS.get(self.rank_id, 'SR')

    def to_dict(self):
        return {
            'id': self.id,
            'adviser_code': self.adviser_code,
            'full_name': self.full_name,
            'mobile': self.mobile,
            'email': self.email,
            'rank_id': self.rank_id,
            'rank_name': self.rank_name,
            'branch_id': self.branch_id,
            'parent_adviser_code': self.parent_adviser_code,
            'is_company_owner': self.is_company_owner,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
