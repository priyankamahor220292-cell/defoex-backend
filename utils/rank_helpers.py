"""Adviser rank helpers — promoter rank N → new adviser may be assigned ranks 1 through N-1."""

from models.adviser import RANKS

RANK_NAMES = RANKS


def rank_label(rank_id):
    name = RANKS.get(int(rank_id or 1), 'SR')
    return f'{int(rank_id)}. {name}'


def max_allowed_rank_for_promoter(promoter_rank_id):
    """
    Promoter on rank N may register advisers at ranks 1 .. N-1.
    Returns (max_allowed_rank_id, error_message).
    """
    try:
        pr = int(promoter_rank_id or 0)
    except (TypeError, ValueError):
        return None, 'Invalid promoter rank'

    max_rank = pr - 1
    if max_rank < 1:
        return None, (
            f'Promoter is on rank {pr} ({RANKS.get(pr, "?")}). '
            'Cannot register a downline adviser at this rank level.'
        )
    return max_rank, None


def allowed_ranks_for_promoter(promoter_rank_id):
    """Return list of rank ids 1 .. N-1 for promoter rank N."""
    max_rank, err = max_allowed_rank_for_promoter(promoter_rank_id)
    if err:
        return [], err
    return list(range(1, max_rank + 1)), None


def allowed_rank_for_promoter(promoter_rank_id):
    """Backward-compatible alias — returns highest assignable rank (N-1)."""
    return max_allowed_rank_for_promoter(promoter_rank_id)


def validate_assigned_rank(promoter_rank_id, assigned_rank_id):
    max_rank, err = max_allowed_rank_for_promoter(promoter_rank_id)
    if err:
        return err
    try:
        assigned = int(assigned_rank_id or 0)
    except (TypeError, ValueError):
        return 'Invalid rank selection'
    if assigned < 1 or assigned > max_rank:
        return (
            f'Promoter rank {promoter_rank_id} ({RANKS.get(int(promoter_rank_id), "?")}) '
            f'may only assign ranks 1 to {max_rank}.'
        )
    return None
