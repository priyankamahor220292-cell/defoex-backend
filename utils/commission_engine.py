"""
Commission Engine
==================
Triggered after Investment Plan is Approved.

CASE 1 — DEFOEX CODE (Rank 20 / company owner): flat 2% on every investment.
CASE 2 — Direct Benefits: direct adviser receives full rank rate on their investors.
CASE 3 — Team Benefits: upline advisers receive rank differential on downline business.

Rates follow the MIS / SIS commission charts (models.commission).
"""

from models.adviser import RANKS as RANK_ID_TO_NAME
from models.commission import MIS_COMMISSION_RATES, SIS_COMMISSION_RATES

COMPANY_CODE_FLAT_RATE = 2.0  # DEFOEX CODE — flat 2% every investment

RANK_NAMES = RANK_ID_TO_NAME


def _chart_to_rank_id(chart):
    out = {}
    for rank_id, name in RANK_ID_TO_NAME.items():
        if name in chart:
            out[rank_id] = chart[name]
    return out


MIS_RATES = _chart_to_rank_id(MIS_COMMISSION_RATES)
SIS_RATES = _chart_to_rank_id(SIS_COMMISSION_RATES)


def _normalize_tenure(plan_type, tenure):
    t = (tenure or '3Y').strip().upper()
    if plan_type == 'SIS' and t == '7Y':
        return '7.5Y'
    return t


def get_rate(plan_type, rank_id, tenure):
    """Get commission rate % for a given plan type, rank and tenure."""
    rates = MIS_RATES if plan_type == 'MIS' else SIS_RATES
    rank_rates = rates.get(rank_id, rates.get(1, {}))
    key = _normalize_tenure(plan_type, tenure)
    return float(rank_rates.get(key, rank_rates.get('3Y', 0.0)) or 0.0)


def calc_direct_commission(plan_type, tenure, base_amount, rank_id):
    """
    Direct Benefits (CASE 2) = base_amount × rank rate / 100
    MIS base = monthly_amount; SIS base = total_investment_amount
    """
    rate = get_rate(plan_type, rank_id, tenure)
    amount = round(base_amount * rate / 100, 2)
    return rate, amount


def calc_team_commission(plan_type, tenure, base_amount, lower_rank_id, upper_rank_id):
    """
    Team Benefits (CASE 3) = rank differential × base_amount / 100
    """
    upper_rate = get_rate(plan_type, upper_rank_id, tenure)
    lower_rate = get_rate(plan_type, lower_rank_id, tenure)
    diff_rate = max(0.0, upper_rate - lower_rate)
    amount = round(base_amount * diff_rate / 100, 2)
    return diff_rate, amount


def calc_company_flat_commission(base_amount):
    """CASE 1 — DEFOEX CODE flat 2% on every approved investment."""
    amount = round(base_amount * COMPANY_CODE_FLAT_RATE / 100, 2)
    return COMPANY_CODE_FLAT_RATE, amount


# Backward-compatible alias
calc_upper_rank_commission = calc_team_commission


def calculate_all_commissions(investment, adviser_chain):
    """
    Build commission records for one approved investment.

    adviser_chain: direct adviser first, promoters after, company owner last (if present).
    """
    plan_type = investment.get('plan_type', 'MIS')
    tenure = investment.get('plan_tenure', '3Y')

    base = float(investment.get('monthly_amount', 0)) if plan_type == 'MIS' \
        else float(investment.get('total_investment_amount', 0))

    records = []
    prev_rate = 0.0
    company_handled = False

    for i, adviser in enumerate(adviser_chain):
        if adviser.get('is_company_owner'):
            rate, amount = calc_company_flat_commission(base)
            if amount > 0:
                records.append({
                    'adviser_code': adviser['adviser_code'],
                    'adviser_name': adviser.get('full_name', ''),
                    'adviser_rank_id': adviser.get('rank_id', 20),
                    'adviser_rank': RANK_NAMES.get(adviser.get('rank_id', 20), 'House 8'),
                    'commission_type': 'Company Flat',
                    'plan_type': plan_type,
                    'plan_tenure': tenure,
                    'base_amount': base,
                    'commission_rate': rate,
                    'commission_amount': amount,
                    'status': 'Pending',
                })
            company_handled = True
            break

        rank_id = adviser.get('rank_id', 1)
        rate = get_rate(plan_type, rank_id, tenure)

        if i == 0:
            comm_rate = rate
            comm_amount = round(base * rate / 100, 2)
            comm_type = 'Direct'
        else:
            comm_rate = max(0.0, rate - prev_rate)
            comm_amount = round(base * comm_rate / 100, 2)
            comm_type = 'Team'

        if comm_rate > 0 and comm_amount > 0:
            records.append({
                'adviser_code': adviser['adviser_code'],
                'adviser_name': adviser.get('full_name', ''),
                'adviser_rank_id': rank_id,
                'adviser_rank': RANK_NAMES.get(rank_id, 'SR'),
                'commission_type': comm_type,
                'plan_type': plan_type,
                'plan_tenure': tenure,
                'base_amount': base,
                'commission_rate': comm_rate,
                'commission_amount': comm_amount,
                'status': 'Pending',
            })

        prev_rate = max(prev_rate, rate)

    if not company_handled:
        owner = next((a for a in adviser_chain if a.get('is_company_owner')), None)
        if owner is None:
            pass  # processor may append company owner from DB

    return records


def get_commission_example(plan_type, tenure, monthly_amount, rank_id):
    rate, amount = calc_direct_commission(plan_type, tenure, monthly_amount, rank_id)
    rank_name = RANK_NAMES.get(rank_id, 'SR')
    base_label = 'monthly' if plan_type == 'MIS' else 'lump sum'
    return {
        'plan': f'{plan_type} {tenure}',
        'base_amount': monthly_amount,
        'base_label': base_label,
        'rank': f'{rank_name} (Rank {rank_id})',
        'rate': f'{rate}%',
        'commission': amount,
        'formula': f'₹{monthly_amount:,.0f} × {rate}% = ₹{amount:,.2f}',
    }
