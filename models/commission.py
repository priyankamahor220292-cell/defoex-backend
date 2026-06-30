from extensions import db
from utils.datetime_utils import now_ist, isoformat_ist

# Commission rates from the chart
MIS_COMMISSION_RATES = {
    'SR':      {'3Y': 7,    '5Y': 9,    '7Y': 11},
    'SO':      {'3Y': 7.5,  '5Y': 9.5,  '7Y': 11.5},
    'SD':      {'3Y': 8,    '5Y': 10,   '7Y': 12},
    'SI':      {'3Y': 8.5,  '5Y': 10.5, '7Y': 12.5},
    'DO':      {'3Y': 9,    '5Y': 11,   '7Y': 13},
    'RO':      {'3Y': 9.5,  '5Y': 11.5, '7Y': 13.5},
    'ZO':      {'3Y': 10,   '5Y': 12,   '7Y': 14},
    'EM':      {'3Y': 10.5, '5Y': 12.5, '7Y': 14.5},
    'EM I':    {'3Y': 11,   '5Y': 13,   '7Y': 15},
    'EM II':   {'3Y': 11.5, '5Y': 13.5, '7Y': 15.5},
    'EM R':    {'3Y': 12,   '5Y': 14,   '7Y': 16},
    'EM C':    {'3Y': 12.5, '5Y': 14.5, '7Y': 16.5},
    'House 1': {'3Y': 13,   '5Y': 15,   '7Y': 17},
    'House 2': {'3Y': 13.5, '5Y': 15.5, '7Y': 17.5},
    'House 3': {'3Y': 14,   '5Y': 16,   '7Y': 18},
    'House 4': {'3Y': 14.5, '5Y': 16.5, '7Y': 18.5},
    'House 5': {'3Y': 15,   '5Y': 17,   '7Y': 19},
    'House 6': {'3Y': 15.5, '5Y': 17.5, '7Y': 19.5},
    'House 7': {'3Y': 16,   '5Y': 18,   '7Y': 20},
    'House 8': {'3Y': 16.5, '5Y': 18.5, '7Y': 20.5},
}

SIS_COMMISSION_RATES = {
    'SR':      {'3Y': 8,    '5Y': 12,   '7.5Y': 16},
    'SO':      {'3Y': 8.5,  '5Y': 12.5, '7.5Y': 16.5},
    'SD':      {'3Y': 9,    '5Y': 13,   '7.5Y': 17},
    'SI':      {'3Y': 9.5,  '5Y': 13.5, '7.5Y': 17.5},
    'DO':      {'3Y': 10,   '5Y': 14,   '7.5Y': 18},
    'RO':      {'3Y': 10.5, '5Y': 14.5, '7.5Y': 18.5},
    'ZO':      {'3Y': 11,   '5Y': 15,   '7.5Y': 19},
    'EM':      {'3Y': 11.5, '5Y': 15.5, '7.5Y': 19.5},
    'EM I':    {'3Y': 12,   '5Y': 16,   '7.5Y': 20},
    'EM II':   {'3Y': 12.5, '5Y': 16.5, '7.5Y': 20.5},
    'EM R':    {'3Y': 13,   '5Y': 17,   '7.5Y': 21},
    'EM C':    {'3Y': 13.5, '5Y': 17.5, '7.5Y': 21.5},
    'House 1': {'3Y': 14,   '5Y': 18,   '7.5Y': 22},
    'House 2': {'3Y': 14.5, '5Y': 18.5, '7.5Y': 22.5},
    'House 3': {'3Y': 15,   '5Y': 19,   '7.5Y': 23},
    'House 4': {'3Y': 15.5, '5Y': 19.5, '7.5Y': 23.5},
    'House 5': {'3Y': 16,   '5Y': 20,   '7.5Y': 24},
    'House 6': {'3Y': 16.5, '5Y': 20.5, '7.5Y': 24.5},
    'House 7': {'3Y': 17,   '5Y': 21,   '7.5Y': 25},
    'House 8': {'3Y': 17.5, '5Y': 21.5, '7.5Y': 25.5},
}

class Commission(db.Model):
    __tablename__ = 'commissions'

    id = db.Column(db.Integer, primary_key=True)
    investment_id = db.Column(db.Integer, db.ForeignKey('investments.id'), nullable=False)
    adviser_code = db.Column(db.String(30), nullable=False)
    adviser_rank = db.Column(db.String(20))
    plan_type = db.Column(db.String(10))
    plan_tenure = db.Column(db.String(10))
    investment_amount = db.Column(db.Numeric(15, 2))
    commission_rate = db.Column(db.Numeric(5, 2))
    commission_amount = db.Column(db.Numeric(15, 2))
    status = db.Column(db.String(20), default='Pending')
    paid_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=now_ist)

    def to_dict(self):
        ctype = getattr(self, 'commission_type', None) or 'Direct'
        display_type = 'Team Benefits' if ctype in ('Team', 'Upper Rank') else (
            'Direct Benefits' if ctype == 'Direct' else ctype
        )
        return {
            'id': self.id,
            'investment_id': self.investment_id,
            'adviser_code': self.adviser_code,
            'adviser_rank': self.adviser_rank,
            'plan_type': self.plan_type,
            'plan_tenure': self.plan_tenure,
            'investment_amount': float(self.investment_amount) if self.investment_amount else None,
            'base_amount': float(self.investment_amount) if self.investment_amount else None,
            'commission_rate': float(self.commission_rate) if self.commission_rate else None,
            'commission_amount': float(self.commission_amount) if self.commission_amount else None,
            'commission_type': ctype,
            'benefit_type': display_type,
            'status': self.status,
            'paid_at': isoformat_ist(self.paid_at),
            'created_at': isoformat_ist(self.created_at),
        }