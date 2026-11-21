"""Local request limits, independent of the provider's unknown remaining quota."""


class RequestBudgetExceeded(RuntimeError):
    """A local guard stopped a request before it was sent."""

