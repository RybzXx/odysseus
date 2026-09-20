"""Confirm that revenue increases at every group-price band boundary."""
from dataclasses import replace
from decimal import Decimal, ROUND_CEILING


GROUP_PRICING_POLICY_VERSION = "band-revenue-gap-450-v1"
PRICE_INCREMENT = Decimal("25")
MINIMUM_REVENUE_INCREASE = Decimal("450")


def confirm_group_revenue(rows):
    """Return audited copies, without reducing prices or counting FOC revenue.

    Each vehicle must have positive, nonoverlapping paying bands. For each
    higher band, its minimum revenue must exceed the previous maximum by $450.
    Apply the smallest $25 price increase that satisfies this condition.
    """
    confirmed = list(rows)
    vehicles = dict.fromkeys(row.vehicle for row in rows)
    for vehicle in vehicles:
        indices = sorted((i for i, row in enumerate(rows) if row.vehicle == vehicle),
                         key=lambda i: rows[i].min_pax - rows[i].foc_count)
        previous_max = None
        previous_revenue = None
        for index in indices:
            row = rows[index]
            counts = (row.min_pax, row.max_pax, row.foc_count)
            if any(type(count) is not int for count in counts) or row.foc_count < 0:
                raise ValueError("Group and FOC counts must be nonnegative integers.")
            lower = row.min_pax - row.foc_count
            upper = row.max_pax - row.foc_count
            if lower < 1 or upper < lower or (previous_max is not None and lower <= previous_max):
                raise ValueError("Paying guest bands must be positive and must not overlap.")
            price = Decimal(str(row.price_per_person))
            if not price.is_finite() or price <= 0:
                raise ValueError("Group prices must be finite and greater than zero.")
            calculated = row.calculated_price_per_person
            if calculated is None:
                calculated = row.price_per_person
            required_revenue = previous_revenue + MINIMUM_REVENUE_INCREASE if previous_revenue is not None else None
            if required_revenue is not None and price * lower < required_revenue:
                increments = (required_revenue / (lower * PRICE_INCREMENT)).to_integral_value(rounding=ROUND_CEILING)
                price = increments * PRICE_INCREMENT
            minimum = price * lower
            maximum = price * upper
            check = {
                "paying_min": lower, "paying_max": upper,
                "minimum_revenue": float(minimum), "maximum_revenue": float(maximum),
                "previous_maximum_revenue": float(previous_revenue) if previous_revenue is not None else None,
                "required_minimum_revenue": float(required_revenue) if required_revenue is not None else None,
                "revenue_increase": float(minimum - previous_revenue) if previous_revenue is not None else None,
                "increase_per_person": float(price - Decimal(str(calculated))),
                "passed": required_revenue is None or minimum >= required_revenue,
            }
            confirmed[index] = replace(row, price_per_person=float(price),
                                       calculated_price_per_person=calculated, revenue_check=check)
            previous_max, previous_revenue = upper, maximum
    return confirmed
