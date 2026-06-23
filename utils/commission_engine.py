"""
Commission Engine
==================
Triggered after Investment Plan is Approved.

Structure (from flowchart):
- Investment Plan Done
  ├── Direct Commission  → paid to the direct adviser
  └── Upper Rank Commission → paid to each adviser above (trickle up chain)
  └── 0% → COMPANY CODE WALLET (remainder goes to company)

MIS Commission Rates (% of monthly_amount):
  Rank SR  (1) : 3Y=7%,  5Y=9%,   7Y=10%
  Rank SO  (2) : 3Y=7%,  5Y=9%,   7Y=10%
  Rank SD  (3) : 3Y=7%,  5Y=9%,   7Y=10%
  Rank SI  (4) : 3Y=7%,  5Y=9%,   7Y=10%
  Rank DO  (5) : 3Y=8%,  5Y=10%,  7Y=11%
  Rank RO  (6) : 3Y=8%,  5Y=10%,  7Y=11%
  Rank ZO  (7) : 3Y=9%,  5Y=11%,  7Y=12%
  Rank EM  (8) : 3Y=9%,  5Y=11%,  7Y=12%
  Rank EM I(9) : 3Y=10%, 5Y=12%,  7Y=13%
  Rank EM II(10): 3Y=11%,5Y=13%,  7Y=14%
  Rank EM R(11): 3Y=12%, 5Y=14%,  7Y=15%
  Rank EM C(12): 3Y=13%, 5Y=15%,  7Y=16%
  House 1 (13) : 3Y=13%, 5Y=15%,  7Y=16%
  House 2 (14) : 3Y=13.5%,5Y=15.5%,7Y=16.5%
  House 3 (15) : 3Y=14%, 5Y=16%,  7Y=17%
  House 4 (16) : 3Y=14.5%,5Y=16%,7Y=17%
  House 5 (17) : 3Y=14.5%,5Y=16%,7Y=17%
  House 6 (18) : 3Y=14.5%,5Y=16%,7Y=17%
  House 7 (19) : 3Y=14.5%,5Y=16%,7Y=17%
  House 8 (20) : 3Y=14.5%,5Y=16.5%,7Y=17.5%

SIS Commission Rates (% of total_investment_amount):
  Ranks 1-4  : 3Y=7%,  5Y=9%,  7Y=10%
  Ranks 5-6  : 3Y=8%,  5Y=10%, 7Y=11%
  Ranks 7-8  : 3Y=9%,  5Y=11%, 7Y=12%
  Ranks 9-10 : 3Y=10%, 5Y=12%, 7Y=13%
  Ranks 11-12: 3Y=12%, 5Y=14%, 7Y=15%
  Ranks 13-14: 3Y=13%, 5Y=15%, 7Y=16%
  Ranks 15-16: 3Y=14%, 5Y=16%, 7Y=17%
  Ranks 17-20: 3Y=14.5%,5Y=16.5%,7Y=17.5%

Upper Rank Commission = difference between ranks
  e.g. House 8 direct adviser gets 14.5%
       their promoter at House 8 also gets difference (0% if same rank)
       promoter at higher rank gets their rate minus direct adviser's rate
"""

# ── MIS Commission Rates ──────────────────────────────────────────
MIS_RATES = {
    1:  {'3Y': 7.0,  '5Y': 9.0,  '7Y': 10.0},
    2:  {'3Y': 7.0,  '5Y': 9.0,  '7Y': 10.0},
    3:  {'3Y': 7.0,  '5Y': 9.0,  '7Y': 10.0},
    4:  {'3Y': 7.0,  '5Y': 9.0,  '7Y': 10.0},
    5:  {'3Y': 8.0,  '5Y': 10.0, '7Y': 11.0},
    6:  {'3Y': 8.0,  '5Y': 10.0, '7Y': 11.0},
    7:  {'3Y': 9.0,  '5Y': 11.0, '7Y': 12.0},
    8:  {'3Y': 9.0,  '5Y': 11.0, '7Y': 12.0},
    9:  {'3Y': 10.0, '5Y': 12.0, '7Y': 13.0},
    10: {'3Y': 11.0, '5Y': 13.0, '7Y': 14.0},
    11: {'3Y': 12.0, '5Y': 14.0, '7Y': 15.0},
    12: {'3Y': 13.0, '5Y': 15.0, '7Y': 16.0},
    13: {'3Y': 13.0, '5Y': 15.0, '7Y': 16.0},
    14: {'3Y': 13.5, '5Y': 15.5, '7Y': 16.5},
    15: {'3Y': 14.0, '5Y': 16.0, '7Y': 17.0},
    16: {'3Y': 14.5, '5Y': 16.0, '7Y': 17.0},
    17: {'3Y': 14.5, '5Y': 16.0, '7Y': 17.0},
    18: {'3Y': 14.5, '5Y': 16.0, '7Y': 17.0},
    19: {'3Y': 14.5, '5Y': 16.0, '7Y': 17.0},
    20: {'3Y': 14.5, '5Y': 16.5, '7Y': 17.5},
}

# ── SIS Commission Rates ──────────────────────────────────────────
SIS_RATES = {
    1:  {'3Y': 7.0,  '5Y': 9.0,  '7Y': 10.0},
    2:  {'3Y': 7.0,  '5Y': 9.0,  '7Y': 10.0},
    3:  {'3Y': 7.0,  '5Y': 9.0,  '7Y': 10.0},
    4:  {'3Y': 7.0,  '5Y': 9.0,  '7Y': 10.0},
    5:  {'3Y': 8.0,  '5Y': 10.0, '7Y': 11.0},
    6:  {'3Y': 8.0,  '5Y': 10.0, '7Y': 11.0},
    7:  {'3Y': 9.0,  '5Y': 11.0, '7Y': 12.0},
    8:  {'3Y': 9.0,  '5Y': 11.0, '7Y': 12.0},
    9:  {'3Y': 10.0, '5Y': 12.0, '7Y': 13.0},
    10: {'3Y': 11.0, '5Y': 13.0, '7Y': 14.0},
    11: {'3Y': 12.0, '5Y': 14.0, '7Y': 15.0},
    12: {'3Y': 13.0, '5Y': 15.0, '7Y': 16.0},
    13: {'3Y': 13.0, '5Y': 15.0, '7Y': 16.0},
    14: {'3Y': 13.5, '5Y': 15.5, '7Y': 16.5},
    15: {'3Y': 14.0, '5Y': 16.0, '7Y': 17.0},
    16: {'3Y': 14.5, '5Y': 16.5, '7Y': 17.5},
    17: {'3Y': 14.5, '5Y': 16.5, '7Y': 17.5},
    18: {'3Y': 14.5, '5Y': 16.5, '7Y': 17.5},
    19: {'3Y': 14.5, '5Y': 16.5, '7Y': 17.5},
    20: {'3Y': 14.5, '5Y': 16.5, '7Y': 17.5},
}

RANK_NAMES = {
    1:'SR', 2:'SO', 3:'SD', 4:'SI', 5:'DO', 6:'RO', 7:'ZO',
    8:'EM', 9:'EM I', 10:'EM II', 11:'EM R', 12:'EM C',
    13:'House 1', 14:'House 2', 15:'House 3', 16:'House 4',
    17:'House 5', 18:'House 6', 19:'House 7', 20:'House 8',
}


def get_rate(plan_type, rank_id, tenure):
    """Get commission rate % for a given plan type, rank and tenure."""
    rates = MIS_RATES if plan_type == 'MIS' else SIS_RATES
    rank_rates = rates.get(rank_id, rates[1])
    return rank_rates.get(tenure, 0.0)


def calc_direct_commission(plan_type, tenure, base_amount, rank_id):
    """
    Direct Commission = base_amount × rate / 100
    MIS: base_amount = monthly_amount
    SIS: base_amount = total_investment_amount (lump sum)
    """
    rate   = get_rate(plan_type, rank_id, tenure)
    amount = round(base_amount * rate / 100, 2)
    return rate, amount


def calc_upper_rank_commission(plan_type, tenure, base_amount, lower_rank_id, upper_rank_id):
    """
    Upper Rank Commission = difference between ranks
    Upper adviser gets: their_rate - direct_adviser_rate
    (they already received their direct commission from their own investors)
    """
    upper_rate = get_rate(plan_type, upper_rank_id, tenure)
    lower_rate = get_rate(plan_type, lower_rank_id, tenure)
    diff_rate  = max(0.0, upper_rate - lower_rate)
    amount     = round(base_amount * diff_rate / 100, 2)
    return diff_rate, amount


def calculate_all_commissions(investment, adviser_chain):
    """
    Calculate full commission chain for an investment.

    investment = {
        plan_type: 'MIS'|'SIS',
        plan_tenure: '3Y'|'5Y'|'7Y',
        monthly_amount: 1000,
        total_investment_amount: 36000,
        adviser_code: 'DFX-2026-000002',
    }

    adviser_chain = list of advisers from direct → company owner:
    [
        {'adviser_code':'DFX-2026-000002', 'rank_id':20, 'full_name':'...'},  # direct
        {'adviser_code':'DFX-2026-000001', 'rank_id':20, 'full_name':'Company Owner'},  # promoter
    ]

    Returns list of commission records to insert.
    """
    plan_type = investment.get('plan_type', 'MIS')
    tenure    = investment.get('plan_tenure', '3Y')

    # MIS base = monthly_amount, SIS base = total_investment_amount
    base = float(investment.get('monthly_amount', 0)) if plan_type == 'MIS' \
           else float(investment.get('total_investment_amount', 0))

    records = []
    prev_rate = 0.0

    for i, adviser in enumerate(adviser_chain):
        rank_id   = adviser.get('rank_id', 1)
        rate      = get_rate(plan_type, rank_id, tenure)

        if i == 0:
            # Direct adviser — full rate
            comm_rate   = rate
            comm_amount = round(base * rate / 100, 2)
            comm_type   = 'Direct'
        else:
            # Upper rank — difference only
            comm_rate   = max(0.0, rate - prev_rate)
            comm_amount = round(base * comm_rate / 100, 2)
            comm_type   = 'Upper Rank'

        if comm_rate > 0:
            records.append({
                'adviser_code':     adviser['adviser_code'],
                'adviser_name':     adviser.get('full_name', ''),
                'adviser_rank_id':  rank_id,
                'adviser_rank':     RANK_NAMES.get(rank_id, 'SR'),
                'commission_type':  comm_type,
                'plan_type':        plan_type,
                'plan_tenure':      tenure,
                'base_amount':      base,
                'commission_rate':  comm_rate,
                'commission_amount':comm_amount,
                'status':           'Pending',
            })

        prev_rate = max(prev_rate, rate)  # use highest rate seen so far

    return records


def get_commission_example(plan_type, tenure, monthly_amount, rank_id):
    """
    Human-readable commission example.
    e.g. "MIS 3Y, ₹1000/month, House 8 → 14.5% → ₹145 Direct Commission"
    """
    rate, amount = calc_direct_commission(plan_type, tenure, monthly_amount, rank_id)
    rank_name    = RANK_NAMES.get(rank_id, 'SR')
    base_label   = 'monthly' if plan_type == 'MIS' else 'lump sum'
    return {
        'plan':        f'{plan_type} {tenure}',
        'base_amount': monthly_amount,
        'base_label':  base_label,
        'rank':        f'{rank_name} (Rank {rank_id})',
        'rate':        f'{rate}%',
        'commission':  amount,
        'formula':     f'₹{monthly_amount:,.0f} × {rate}% = ₹{amount:,.2f}',
    }