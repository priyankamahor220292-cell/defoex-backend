"""Branch wallet deductions: panel limit (current_balance) ↓, cash_wallet ↑."""

from extensions import db
from models.branch_wallet import BranchWallet, WalletTransaction


def ensure_branch_wallet(branch_id):
    wallet = BranchWallet.query.filter_by(branch_id=int(branch_id)).first()
    if not wallet:
        wallet = BranchWallet(
            branch_id=int(branch_id),
            current_balance=0,
            cash_wallet=0,
        )
        db.session.add(wallet)
        db.session.flush()
    return wallet


def wallet_reference_exists(reference_id):
    if not reference_id:
        return False
    return WalletTransaction.query.filter_by(reference_id=str(reference_id)).first() is not None


def deduct_branch_wallet(branch_id, amount, description, reference_id=None, created_by=None):
    """
    Deduct amount from branch panel limit (current_balance).
    Add same amount to cash_wallet (cash collected at branch).
    Returns (result_dict, error_message).
    """
    amount = float(amount or 0)
    if amount <= 0:
        wallet = BranchWallet.query.filter_by(branch_id=int(branch_id)).first()
        return {
            'amount': 0,
            'skipped': True,
            'current_balance': float(wallet.current_balance or 0) if wallet else 0,
            'cash_wallet': float(wallet.cash_wallet or 0) if wallet else 0,
        }, None

    if reference_id and wallet_reference_exists(reference_id):
        wallet = ensure_branch_wallet(branch_id)
        return {
            'amount': amount,
            'skipped': True,
            'already_deducted': True,
            'current_balance': float(wallet.current_balance or 0),
            'cash_wallet': float(wallet.cash_wallet or 0),
        }, None

    wallet = ensure_branch_wallet(branch_id)
    bal = float(wallet.current_balance or 0)
    if bal < amount:
        return None, (
            f'Insufficient branch wallet balance. '
            f'Required ₹{amount:,.0f}, available ₹{bal:,.0f}'
        )

    wallet.current_balance = bal - amount
    wallet.cash_wallet = float(wallet.cash_wallet or 0) + amount

    txn = WalletTransaction(
        branch_id=int(branch_id),
        transaction_type='Deduction',
        amount=amount,
        description=description,
        reference_id=str(reference_id) if reference_id else None,
        balance_after=wallet.current_balance,
        cash_wallet_after=wallet.cash_wallet,
        created_by=int(created_by) if created_by else None,
    )
    db.session.add(txn)

    return {
        'amount': amount,
        'current_balance': float(wallet.current_balance),
        'cash_wallet': float(wallet.cash_wallet),
    }, None
