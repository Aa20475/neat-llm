"""Small, versioned pure tools. Workers get no host filesystem or shell access."""

from decimal import Decimal, ROUND_HALF_UP, localcontext

from langchain_core.tools import tool


def _decimal(value: str) -> Decimal:
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("Use a decimal string of at most 40 characters")
    number = Decimal(value)
    if not number.is_finite() or number.copy_abs() > Decimal("1e12") or number.as_tuple().exponent < -12:
        raise ValueError("Decimal outside supported range")
    return number


@tool
def decimal_product(a: str, b: str) -> str:
    """Multiply two decimal strings exactly; return two places, rounding ROUND_HALF_UP."""
    with localcontext() as context:
        context.prec = 60
        return format((_decimal(a) * _decimal(b)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f")


@tool
def decimal_sum(values: list[str]) -> str:
    """Sum up to 100 decimal strings; return two places, rounding ROUND_HALF_UP."""
    if len(values) > 100:
        raise ValueError("At most 100 values")
    with localcontext() as context:
        context.prec = 60
        return format(sum((_decimal(value) for value in values), Decimal(0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f")


TOOLS = {item.name: item for item in (decimal_product, decimal_sum)}
