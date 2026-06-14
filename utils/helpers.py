import random
import string
from datetime import date, datetime

def generate_investor_id():
    """Generate unique investor ID like INV20260001"""
    year = datetime.now().year
    rand = ''.join(random.choices(string.digits, k=6))
    return f"INV{year}{rand}"

def generate_adviser_code():
    """Generate unique adviser code like ADV20260001"""
    year = datetime.now().year
    rand = ''.join(random.choices(string.digits, k=6))
    return f"ADV{year}{rand}"

def generate_irn():
    """Generate Investment Reference Number like IRN202600001"""
    year = datetime.now().year
    rand = ''.join(random.choices(string.digits, k=5))
    return f"IRN{year}{rand}"

def calculate_age(dob):
    """Calculate age from date of birth"""
    if not dob:
        return None
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

def success_response(data=None, message="Success", status_code=200):
    response = {'success': True, 'message': message}
    if data is not None:
        response['data'] = data
    return response, status_code

def error_response(message="Error", status_code=400, errors=None):
    response = {'success': False, 'message': message}
    if errors:
        response['errors'] = errors
    return response, status_code

def paginate_query(query, page, per_page=20):
    paginated = query.paginate(page=page, per_page=per_page, error_out=False)
    return {
        'items': paginated.items,
        'total': paginated.total,
        'pages': paginated.pages,
        'current_page': paginated.page,
        'per_page': paginated.per_page,
        'has_next': paginated.has_next,
        'has_prev': paginated.has_prev
    }
