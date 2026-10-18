"""Versioned arithmetic and sandboxed Python tools for roots and workers."""

from decimal import Decimal, ROUND_HALF_UP, localcontext

from langchain_core.tools import tool

from company.python_runner import run_python


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


@tool
async def python_execute(code: str, files: dict[str, str] | None = None) -> dict:
    """Write and execute Python code in a fresh, isolated /work/main.py.

    Use for algorithms, data processing, simulations, and running assertions/tests.
    Optional files maps relative paths to text contents (e.g. data.csv or helper.py).
    Python standard library only; no pip, network, project files, or credentials.
    You can read/write /work during execution. Each call starts empty: print any
    results or file contents you need to keep, then revise/resubmit code to iterate.
    A final expression is displayed automatically (like a notebook); None is silent.
    Returns stdout, stderr, exit_code, status, and truncation flags. Limits: 10s
    wall, 5s CPU, 256 MiB memory, 16 MiB workspace, 4,000 bytes per output stream.
    """
    return await run_python(code, files)


TOOLS = {item.name: item for item in (decimal_product, decimal_sum, python_execute)}
