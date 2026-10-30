from __future__ import annotations


class DatasetError(Exception):
    """A dataset operation failed. `hint` tells the user what to do next."""

    def __init__(self, code: str, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        return f"{self.message} ({self.hint})" if self.hint else self.message
