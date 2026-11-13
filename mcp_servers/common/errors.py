"""Transport-independent tool failures for clients and servers."""


class ToolFailure(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        retryable: bool = False,
        retry_after: float | None = None,
    ):
        super().__init__(message)
        self.code, self.message = code, message
        self.retryable, self.retry_after = retryable, retry_after
