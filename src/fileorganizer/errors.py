"""Exception types. Messages are short English sentences: reason + next step."""


class FileOrganizerError(Exception):
    """Base class."""


class RuleError(FileOrganizerError):
    """Invalid rules."""


class PreflightError(FileOrganizerError):
    """A check failed BEFORE any file was moved (CLI exit code 2)."""

    def __init__(self, message: str, problems: list[str] | None = None):
        super().__init__(message)
        self.problems = list(problems or [])


class LockBusyError(PreflightError):
    """Another instance holds the root lock."""


class JournalError(FileOrganizerError):
    """The run journal could not be written."""
