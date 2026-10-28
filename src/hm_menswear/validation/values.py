"""No imputation: required formats and exact source-unit prices."""

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import lru_cache

ARTICLE = re.compile(r"[0-9]{10}\Z")
CUSTOMER = re.compile(r"[0-9a-f]{64}\Z")
ASCII_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")


@lru_cache(maxsize=8192)
def valid_date(token):
    try:
        return (
            bool(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", token))
            and date.fromisoformat(token).isoformat() == token
        )
    except ValueError:
        return False


@lru_cache(maxsize=8192)
def valid_price(token):
    try:
        if not ASCII_DECIMAL.fullmatch(token):
            return False
        value = Decimal(token)
        if not value.is_finite() or value < 0:
            return False
        parts = value.as_tuple()
        # Bound the written decimal encoding to PostgreSQL numeric's storage sizes.
        # This is a conservative encoding contract (also for zero), not a price cap.
        return parts.exponent >= -16383 and len(parts.digits) + parts.exponent <= 131072
    except InvalidOperation:
        return False


def customer_metadata(row):
    fn, active, club, news, age = row[1:6]
    if fn not in ("", "1.0") or active not in ("", "1.0"):
        return False
    if age:
        if not valid_price(age):
            return False
        try:
            number = Decimal(age)
            if (
                not number.is_finite()
                or number < 0
                or number != number.to_integral_value()
                or number > 2147483647
            ):
                return False
        except InvalidOperation:
            return False
    return True
