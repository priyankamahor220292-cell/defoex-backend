from extensions import db
from datetime import date
from utils.datetime_utils import now_ist, isoformat_ist

class Member(db.Model):
    __tablename__ = 'members'

    id = db.Column(db.Integer, primary_key=True)
    investor_id = db.Column(db.String(30), unique=True, nullable=False)

    # Personal Info
    salutation = db.Column(db.String(10))  # Mr/Mrs/Ms/Dr
    full_name = db.Column(db.String(200), nullable=False)
    father_spouse_name = db.Column(db.String(200))
    date_of_birth = db.Column(db.Date)
    age = db.Column(db.Integer)
    gender = db.Column(db.String(10))
    marital_status = db.Column(db.String(20))
    nationality = db.Column(db.String(50), default='Indian')
    mobile = db.Column(db.String(15), unique=True, nullable=False)
    phone_office = db.Column(db.String(15))
    phone_residence = db.Column(db.String(15))
    email = db.Column(db.String(150))
    is_senior_citizen = db.Column(db.Boolean, default=False)
    is_special_roi = db.Column(db.Boolean, default=False)

    # Correspondence Address
    corr_address = db.Column(db.Text)
    corr_state = db.Column(db.String(100))
    corr_city = db.Column(db.String(100))
    corr_pincode = db.Column(db.String(10))

    # Permanent Address (may be same as correspondence)
    perm_address = db.Column(db.Text)
    perm_state = db.Column(db.String(100))
    perm_city = db.Column(db.String(100))
    perm_pincode = db.Column(db.String(10))
    same_as_corr = db.Column(db.Boolean, default=False)

    # KYC / Documents
    aadhar_number = db.Column(db.String(20), unique=True)
    pan_number = db.Column(db.String(20))
    passport_number = db.Column(db.String(30))
    voter_id = db.Column(db.String(30))
    driving_license = db.Column(db.String(30))
    ration_card = db.Column(db.String(30))
    verification_doc_type = db.Column(db.String(50))

    # Nominee Info
    nominee_name = db.Column(db.String(200))
    nominee_age = db.Column(db.Integer)
    nominee_relationship = db.Column(db.String(50))
    nominee_address = db.Column(db.Text)
    nominee_state = db.Column(db.String(100))
    nominee_city = db.Column(db.String(100))
    nominee_pincode = db.Column(db.String(10))
    nominee_same_as_member = db.Column(db.Boolean, default=False)

    # Bank Details
    bank_name = db.Column(db.String(100))
    account_number = db.Column(db.String(30))
    ifsc_code = db.Column(db.String(20))
    bank_branch_name = db.Column(db.String(100))
    upi_id = db.Column(db.String(100))

    # Income Info
    occupation = db.Column(db.String(100))
    professional_details = db.Column(db.Text)
    annual_income = db.Column(db.Numeric(15, 2))
    family_income = db.Column(db.Numeric(15, 2))

    # Registration Info
    adviser_code = db.Column(db.String(30), nullable=False)
    promoter_post = db.Column(db.String(100))
    member_type = db.Column(db.String(30), default='Investor')
    member_fees = db.Column(db.Numeric(10, 2), default=10)
    promoter_fees = db.Column(db.Numeric(10, 2), default=0)
    payment_mode = db.Column(db.String(20), default='Cash')
    cheque_dd_details = db.Column(db.String(100))
    cheque_dd_date = db.Column(db.Date)
    reg_bank_name = db.Column(db.String(100))
    company_account = db.Column(db.String(100))
    date_of_joining = db.Column(db.Date, default=date.today)

    # Status
    branch_id = db.Column(db.Integer, db.ForeignKey('branches.id'))
    approval_status = db.Column(db.String(20), default='Pending')
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=now_ist)
    updated_at = db.Column(db.DateTime, default=now_ist, onupdate=now_ist)

    branch = db.relationship('Branch', backref='members', lazy=True)
    investments = db.relationship('Investment', backref='member', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'investor_id': self.investor_id,
            'salutation': self.salutation,
            'full_name': self.full_name,
            'father_spouse_name': self.father_spouse_name,
            'date_of_birth': self.date_of_birth.isoformat() if self.date_of_birth else None,
            'age': self.age,
            'gender': self.gender,
            'marital_status': self.marital_status,
            'nationality': self.nationality,
            'mobile': self.mobile,
            'email': self.email,
            'is_senior_citizen': self.is_senior_citizen,
            'corr_address': self.corr_address,
            'corr_state': self.corr_state,
            'corr_city': self.corr_city,
            'corr_pincode': self.corr_pincode,
            'perm_address': self.perm_address,
            'perm_state': self.perm_state,
            'perm_city': self.perm_city,
            'perm_pincode': self.perm_pincode,
            'aadhar_number': self.aadhar_number,
            'pan_number': self.pan_number,
            'nominee_name': self.nominee_name,
            'nominee_age': self.nominee_age,
            'nominee_relationship': self.nominee_relationship,
            'bank_name': self.bank_name,
            'account_number': self.account_number,
            'ifsc_code': self.ifsc_code,
            'occupation': self.occupation,
            'annual_income': float(self.annual_income) if self.annual_income else None,
            'adviser_code': self.adviser_code,
            'member_type': self.member_type,
            'member_fees': float(self.member_fees) if self.member_fees else None,
            'payment_mode': self.payment_mode,
            'date_of_joining': self.date_of_joining.isoformat() if self.date_of_joining else None,
            'branch_id': self.branch_id,
            'approval_status': self.approval_status,
            'is_active': self.is_active,
            'created_at': isoformat_ist(self.created_at)
        }