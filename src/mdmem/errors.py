class MdMemError(Exception):
    """Base error for mdmem."""


class NotFoundError(MdMemError):
    pass


class ConflictError(MdMemError):
    """Raised when a caller's expected_updated stamp no longer matches the
    file on disk (spec §16: optimistic concurrency via the `updated` stamp)."""

    def __init__(self, id: str, expected: str | None, actual: str):
        self.id = id
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"conflict on '{id}': expected updated={expected!r}, actual={actual!r}. "
            "Re-read the file and retry."
        )


class ValidationError(MdMemError):
    pass
