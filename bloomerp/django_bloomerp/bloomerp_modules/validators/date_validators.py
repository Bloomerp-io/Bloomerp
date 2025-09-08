
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import date


def is_before_today(value):
    """
    Validator to ensure a date is before today.
    Used for date of birth validation.
    """
    if isinstance(value, date):
        today = timezone.now().date()
        if value >= today:
            raise ValidationError(
                'Date must be before today.',
                code='date_not_before_today'
            )
    else:
        raise ValidationError(
            'Value must be a date.',
            code='invalid_date_type'
        )