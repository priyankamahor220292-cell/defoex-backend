from extensions import db
from datetime import datetime

class BranchWallet(db.Model):
    __tablename__ = 'branch_wallets'

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), unique=True, nullable=False)
    current_balance = db.Column(db.Numeric(15, 2), default=0)  # Admin-assigned limit
    cash_wallet = db.Column(db.Numeric(15, 2), default=0)       # Accumulated from investments
    low_balance_threshold = db.Column(db.Numeric(15, 2), default=10000)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    branch = db.relationship('Branch', backref='wallet', uselist=False, lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'branch_id': self.branch_id,
            'current_balance': float(self.current_balance) if self.current_balance else 0,
            'cash_wallet': float(self.cash_wallet) if self.cash_wallet else 0,
            'is_low_balance': float(self.current_balance or 0) <= float(self.low_balance_threshold or 10000),
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class WalletTransaction(db.Model):
    __tablename__ = 'wallet_transactions'

    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False)
    transaction_type = db.Column(db.Enum('TopUp', 'Deduction', 'CashIn'), nullable=False)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    description = db.Column(db.String(255))
    reference_id = db.Column(db.String(50))  # investment IRN or topup reference
    balance_after = db.Column(db.Numeric(15, 2))
    cash_wallet_after = db.Column(db.Numeric(15, 2))
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'branch_id': self.branch_id,
            'transaction_type': self.transaction_type,
            'amount': float(self.amount) if self.amount else None,
            'description': self.description,
            'reference_id': self.reference_id,
            'balance_after': float(self.balance_after) if self.balance_after else None,
            'cash_wallet_after': float(self.cash_wallet_after) if self.cash_wallet_after else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
