class Cancelled(Exception):
    """Raised by a reporter to stop a running parse."""


class Reporter:
    """No-op progress sink. Services call it; a job subclass records it (and may raise Cancelled)."""

    def set_title(self, title: str) -> None: ...

    def update(self, stage: str, done: int = 0, total: int = 0, message: str = "") -> None: ...

    def log(self, message: str) -> None: ...
