"""Exception types that map to CLI exit codes (see contracts/cli.md)."""


class DocreaderError(Exception):
    """Base error. Carries the exit code and a one-line Russian message with a hint."""

    exit_code: int = 1

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return self.message


class UserError(DocreaderError):
    """User error (exit code 1): missing path, unknown id, unconfirmed deletion."""

    exit_code = 1


class EnvironmentProblem(DocreaderError):
    """Environment error (exit code 2): data folder, database or settings problem."""

    exit_code = 2
