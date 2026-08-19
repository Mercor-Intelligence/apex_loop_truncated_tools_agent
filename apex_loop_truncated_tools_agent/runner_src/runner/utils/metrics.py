"""No-op metrics surface for the standalone benchmark runner."""

from typing import Any


def distribution(*args: Any, **kwargs: Any) -> None:
    return None


def increment(*args: Any, **kwargs: Any) -> None:
    return None
