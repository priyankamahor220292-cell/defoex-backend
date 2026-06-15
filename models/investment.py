from extensions import db
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from decimal import Decimal, ROUND_HALF_UP

# MIS Plan definitions with exact fraction arithmetic
# 3Y: 4200/3600 = 7/6  → 16.67% ROI
# 5Y: 8000/6000 = 4/3  → 33.33% ROI
# 7Y: 11400/8400 = 19/14 → 35.71% ROI
MIS_PLANS = {
    '3Y': {'months': 36, 'roi_num': 7,  'roi_den': 6,  'roi_pct': '16.67', 'roi_display': '16.67%'},
    '5Y': {'months': 60, 'roi_num': 4,  'roi_den': 3,  'roi_pct': '33.33', 'roi_display': '33.33%'},
    '7Y': {'months': 84, 'roi_num': 19, 'roi_den': 14, 'roi_pct': '35.71', 'roi_display': '35.71%'},
}


class Investment(db.Model):
    __tablename__ = 'investments'

    id              = db.Column(db.Integer, primary_key=True)
    irn             = db.Column(db.String(30), unique=True, nullable=False)
    investor_id     = db.Column(db.String(30), db.ForeignKey('members.investor_id'), nullable=False)
    branch_id       = db.Column(db.Integer, db.ForeignKey('branches.id'))

    plan_type       = db.Column(db.Enum('MIS', 'SIS', name='plan_type_enum'), default='MIS')
    plan_tenure     = db.Column(db.Enum('3Y', '5Y', '7Y', name='plan_tenure_enum'), nullable=False)
    plan_name       = db.Column(db.String(60))

    investment_date = db.Column(db.Date, default=date.today)
    due_date        = db.Column(db.Date)
    maturity_date   = db.Column(db.Date)

    monthly_amount          = db.Column(db.Numeric(12, 2), nullable=False)
    total_investment_amount = db.Column(db.Numeric(15, 2))
    total_maturity_amount   = db.Column(db.Numeric(15, 2))
    roi_percentage          = db.Column(db.Numeric(6, 2))
    plan_fee                = db.Column(db.Numeric(10, 2), default=0)

    payment_mode    = db.Column(db.Enum('Cash', 'Cheque', 'DD', 'UPI', 'NEFT', name='payment_mode_inv_enum'), default='Cash')
    company_account = db.Column(db.String(100))

    installments_paid  = db.Column(db.Integer, default=0)
    total_installments = db.Column(db.Integer)

    adviser_code    = db.Column(db.String(30))

    approval_status = db.Column(db.Enum('Pending', 'Approved', 'Rejected', name='approval_status_inv_enum'), default='Pending')
    approved_by     = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approved_at     = db.Column(db.DateTime, nullable=True)

    status          = db.Column(db.Enum('Active', 'Completed', 'Cancelled', name='inv_status_enum'), default='Active')
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at      = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    branch       = db.relationship('Branch', backref='investments', lazy=True)
    installments = db.relationship('Installment', backref='investment', lazy=True)

    def calculate_plan(self):
        plan = MIS_PLANS.get(self.plan_tenure)
        if not plan:
            return
        months   = plan['months']
        monthly  = Decimal(str(self.monthly_amount))
        total    = monthly * months
        maturity = (total * plan['roi_num']) / plan['roi_den']
        maturity = int(maturity.to_integral_value(rounding=ROUND_HALF_UP))

        self.total_installments        = months
        self.total_investment_amount   = total
        self.total_maturity_amount     = maturity
        self.roi_percentage            = Decimal(plan['roi_pct'])
        self.maturity_date             = self.investment_date + relativedelta(months=months)
        self.due_date                  = self.investment_date + relativedelta(months=1)
        self.plan_name                 = f"MIS{self.plan_tenure}{int(self.monthly_amount)}"

    def to_dict(self):
        try:
            roi_pct = float(self.roi_percentage) if self.roi_percentage else None
            roi_display = f"{roi_pct:.2f}%" if roi_pct else MIS_PLANS.get(self.plan_tenure, {}).get('roi_display')
        except Exception:
            roi_pct     = None
            roi_display = MIS_PLANS.get(self.plan_tenure, {}).get('roi_display')

        return {
            'id':                      self.id,
            'irn':                     self.irn,
            'investor_id':             self.investor_id,
            'branch_id':               self.branch_id,
            'plan_type':               self.plan_type,
            'plan_tenure':             self.plan_tenure,
            'plan_name':               self.plan_name,
            'investment_date':         self.investment_date.isoformat() if self.investment_date else None,
            'due_date':                self.due_date.isoformat() if self.due_date else None,
            'maturity_date':           self.maturity_date.isoformat() if self.maturity_date else None,
            'monthly_amount':          float(self.monthly_amount) if self.monthly_amount else None,
            'total_investment_amount': float(self.total_investment_amount) if self.total_investment_amount else None,
            'total_maturity_amount':   float(self.total_maturity_amount) if self.total_maturity_amount else None,
            'roi_percentage':          roi_pct,
            'roi_display':             roi_display,
            'plan_fee':                float(self.plan_fee) if self.plan_fee else 0,
            'payment_mode':            self.payment_mode,
            'installments_paid':       self.installments_paid or 0,
            'total_installments':      self.total_installments,
            'adviser_code':            self.adviser_code,
            'approval_status':         self.approval_status,
            'status':                  self.status,
            'created_at':              self.created_at.isoformat() if self.created_at else None,
        }


class Installment(db.Model):
    __tablename__ = 'installments'

    id                 = db.Column(db.Integer, primary_key=True)
    investment_id      = db.Column(db.Integer, db.ForeignKey('investments.id'), nullable=False)
    investor_id        = db.Column(db.String(30))
    installment_number = db.Column(db.Integer, nullable=False)
    due_date           = db.Column(db.Date)
    paid_date          = db.Column(db.Date)
    amount             = db.Column(db.Numeric(12, 2))
    payment_mode       = db.Column(db.String(20))
    status             = db.Column(db.Enum('Pending', 'Paid', 'Overdue', name='installment_status_enum'), default='Pending')
    created_at         = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id':                  self.id,
            'investment_id':       self.investment_id,
            'investor_id':         self.investor_id,
            'installment_number':  self.installment_number,
            'due_date':            self.due_date.isoformat() if self.due_date else None,
            'paid_date':           self.paid_date.isoformat() if self.paid_date else None,
            'amount':              float(self.amount) if self.amount else None,
            'payment_mode':        self.payment_mode,
            'status':              self.status,
        }