from extensions import db
from datetime import datetime

ADMIN_WALLET_LIMIT   = 10_00_00_00_000   # ₹100 Crore
ADMIN_LOW_THRESHOLD  = 10_00_00_000      # ₹10 Crore
BRANCH_LOW_THRESHOLD = 10_000            # ₹10,000


class BranchWallet(db.Model):
    __tablename__ = 'branch_wallets'
    __table_args__ = {'extend_existing': True}

    id                    = db.Column(db.Integer, primary_key=True)
    branch_id             = db.Column(db.Integer, db.ForeignKey('branches.id'), unique=True, nullable=False)
    current_balance       = db.Column(db.Numeric(18, 2), default=0)
    cash_wallet           = db.Column(db.Numeric(18, 2), default=0)
    low_balance_threshold = db.Column(db.Numeric(18, 2), default=BRANCH_LOW_THRESHOLD)
    updated_at            = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    branch = db.relationship('Branch', backref='wallet', uselist=False, lazy=True)

    @property
    def is_low_balance(self):
        return float(self.current_balance or 0) <= float(self.low_balance_threshold or BRANCH_LOW_THRESHOLD)

    def to_dict(self):
        bal  = float(self.current_balance or 0)
        cash = float(self.cash_wallet or 0)
        thr  = float(self.low_balance_threshold or BRANCH_LOW_THRESHOLD)
        return {
            'id':                    self.id,
            'branch_id':             self.branch_id,
            'current_balance':       bal,
            'cash_wallet':           cash,
            'low_balance_threshold': thr,
            'is_low_balance':        bal <= thr,
            'updated_at':            self.updated_at.isoformat() if self.updated_at else None,
        }


class AdminWallet(db.Model):
    __tablename__ = 'admin_wallet'
    __table_args__ = {'extend_existing': True}

    id                    = db.Column(db.Integer, primary_key=True)
    total_limit           = db.Column(db.Numeric(18, 2), default=ADMIN_WALLET_LIMIT)
    total_distributed     = db.Column(db.Numeric(18, 2), default=0)
    total_returned        = db.Column(db.Numeric(18, 2), default=0)
    low_balance_threshold = db.Column(db.Numeric(18, 2), default=ADMIN_LOW_THRESHOLD)
    updated_at            = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at            = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def available_balance(self):
        return float(self.total_limit or 0) - float(self.total_distributed or 0) + float(self.total_returned or 0)

    @property
    def is_low_balance(self):
        return self.available_balance <= float(self.low_balance_threshold or ADMIN_LOW_THRESHOLD)

    def to_dict(self):
        limit = float(self.total_limit or 0)
        dist  = float(self.total_distributed or 0)
        ret   = float(self.total_returned or 0)
        avail = limit - dist + ret
        used  = dist - ret
        return {
            'id':                    self.id,
            'total_limit':           limit,
            'total_distributed':     dist,
            'total_returned':        ret,
            'available_balance':     avail,
            'used_amount':           used,
            'used_pct':              round(used / limit * 100, 2) if limit > 0 else 0,
            'is_low_balance':        self.is_low_balance,
            'low_balance_threshold': float(self.low_balance_threshold or ADMIN_LOW_THRESHOLD),
        }


class WalletTransaction(db.Model):
    __tablename__ = 'wallet_transactions'
    __table_args__ = {'extend_existing': True}

    id                = db.Column(db.Integer, primary_key=True)
    branch_id         = db.Column(db.Integer, db.ForeignKey('branches.id'), nullable=False)
    transaction_type  = db.Column(db.String(20), nullable=False)
    amount            = db.Column(db.Numeric(18, 2), nullable=False)
    description       = db.Column(db.String(255))
    reference_id      = db.Column(db.String(50))
    balance_after     = db.Column(db.Numeric(18, 2))
    cash_wallet_after = db.Column(db.Numeric(18, 2))
    created_by        = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at        = db.Column(db.DateTime, default=datetime.utcnow)

    branch = db.relationship('Branch', backref='transactions', lazy=True)

    def to_dict(self):
        return {
            'id':                self.id,
            'branch_id':         self.branch_id,
            'branch_name':       self.branch.branch_name if self.branch else None,
            'transaction_type':  self.transaction_type,
            'amount':            float(self.amount) if self.amount else 0,
            'description':       self.description,
            'reference_id':      self.reference_id,
            'balance_after':     float(self.balance_after)     if self.balance_after     else 0,
            'cash_wallet_after': float(self.cash_wallet_after) if self.cash_wallet_after else 0,
            'created_at':        self.created_at.isoformat() if self.created_at else None,
        }