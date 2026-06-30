"""India Standard Time (IST, Asia/Kolkata) helpers."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')


def now_ist():
    """Current local time in India — naive datetime for DB columns."""
    return datetime.now(IST).replace(tzinfo=None)


def today_ist():
    """Today's date in India."""
    return datetime.now(IST).date()


def isoformat_ist(dt):
    """Serialize a naive IST datetime for API responses (+05:30)."""
    if dt is None:
        return None
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return dt.isoformat()
    if not isinstance(dt, datetime):
        return str(dt)
    return dt.strftime('%Y-%m-%dT%H:%M:%S') + '+05:30'
