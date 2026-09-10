from decimal import Decimal

from app.domain.fx import convert


def test_convert_applies_the_rate_exactly():
    # 100 USD at a rate of 49.50 EGP per USD -> 4950.00 EGP
    assert convert(Decimal("100"), Decimal("49.50")) == Decimal("4950.00")


def test_convert_preserves_decimal_precision_no_float_drift():
    result = convert(Decimal("3.33333333"), Decimal("11.11111111"))
    assert isinstance(result, Decimal)
    assert result == Decimal("3.33333333") * Decimal("11.11111111")


def test_convert_does_not_round():
    result = convert(Decimal("1"), Decimal("1.23456789"))
    assert result == Decimal("1.23456789")
