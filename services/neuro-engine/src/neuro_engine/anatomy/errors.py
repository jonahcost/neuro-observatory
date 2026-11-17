from __future__ import annotations


class AnatomyError(ValueError):
    """An anatomical input is missing, unreadable or fails validation.

    `code` is a stable kebab-case identifier; the message names the file (by
    relative or base name) and the rule, never voxel or vertex values.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
