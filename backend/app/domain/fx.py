"""FX conversion (Phase 11): a pure, generic currency conversion helper.

No hardcoded currency pairs, no assumed 1:1, no fabricated rate. This
module never looks up or fetches a rate itself — that is
repositories/price_repository.py and services/price_service.py's job.
It only applies a rate a caller has already obtained, so the
multiplication itself is defined and tested in exactly one place instead
of being inlined ad hoc across services (see FINANCIAL_RULES.md, "FX
Conversion").
"""

from decimal import Decimal


def convert(value: Decimal, rate: Decimal) -> Decimal:
    """Converts `value` (denominated in a base currency) into a quote
    currency, where `rate` = quote-currency units per 1 base-currency
    unit (see models/fx_rate.py). Same-currency conversion never calls
    this at all — see FINANCIAL_RULES.md, "same currency needs no FX
    lookup"."""
    return value * rate
