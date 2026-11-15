"""Small Python functions exposed to the model as tools."""

import math


def finite_number(value: float) -> float:
    """Require a finite numeric value; reject booleans and strings."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Expected a number.")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Expected a finite number.")
    return number


def multiply(a: float, b: float) -> float:
    """Multiply two finite numbers.

    Args:
        a: First number.
        b: Second number.
    """
    return finite_number(finite_number(a) * finite_number(b))


# Your first contribution: define add(a: float, b: float) with a docstring,
# validate its inputs/result with finite_number, then add it to this list.
TOOLS = [multiply]
