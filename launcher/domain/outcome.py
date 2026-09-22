"""Typed operation outcomes.

Call sites used to pass ``(title, text)`` string pairs through signals,
which made it easy to drop context (which game? what to do next?) and
impossible to handle kinds of failure differently. New code returns an
``Outcome`` instead; the UI renders it through ``launcher.ui.errors``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Error:
    """A failure with enough context to present and to act on."""

    title: str
    detail: str = ""
    #: What the user can try next, in one sentence.
    hint: str = ""
    #: Machine-readable kind, e.g. "missing-executable" or "no-space".
    kind: str = ""


@dataclass(frozen=True)
class Outcome(Generic[T]):
    """Either a value or an Error. Construct via Ok/Err."""

    value: T | None = None
    error: Error | None = None
    _ok: bool = True

    @property
    def ok(self) -> bool:
        return self._ok

    def unwrap(self) -> T:
        """The value, or raise KeyError carrying the Error."""
        if not self._ok or self.error is not None:
            raise KeyError(self.error)
        assert self.value is not None
        return self.value


def Ok(value: T) -> Outcome[T]:
    return Outcome(value=value, _ok=True)


def Err(
    title: str, detail: str = "", *, hint: str = "", kind: str = ""
) -> Outcome[None]:
    return Outcome(value=None, error=Error(title, detail, hint=hint, kind=kind), _ok=False)


@dataclass
class Block:
    """One reason an operation cannot proceed."""

    title: str
    detail: str = ""
    hint: str = ""
    kind: str = ""
    actions: tuple[str, ...] = field(default_factory=tuple)
