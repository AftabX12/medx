class AIClientError(Exception):
    """Base class for AI client errors."""


class RateLimitExhausted(AIClientError):
    """Raised when the provider has no remaining budget (402) or backoff is exhausted.

    Callers may fall back to a local engine (e.g. Marker OCR) when they see this.
    """


class ModelUnavailable(AIClientError):
    """Raised when the requested model ID is not served by the provider."""


class OutputParseError(AIClientError):
    """Raised when the model's output can't be parsed as valid JSON against the schema."""

    def __init__(self, message: str, raw_text: str = "") -> None:
        super().__init__(message)
        self.raw_text = raw_text
