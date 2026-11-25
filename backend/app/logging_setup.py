"""Logging with secret redaction.

Gemini passes the API key in the request URL, and provider/LiteLLM error text
is logged on failures. This filter masks every configured key in every log
record (ours and LiteLLM's) before it is written anywhere.
"""
from __future__ import annotations

import logging

from .config import settings

_LITELLM_LOGGERS = ("LiteLLM", "LiteLLM Router", "LiteLLM Proxy", "litellm")


class RedactSecrets(logging.Filter):
    def __init__(self, secrets: list[str]):
        super().__init__()
        # Longest first, so a key that contains another key is fully masked.
        self._secrets = sorted({s for s in secrets if s}, key=len, reverse=True)

    def redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, "***")
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        if self._secrets:
            try:
                message = record.getMessage()
            except Exception:
                message = str(record.msg)
            record.msg = self.redact(message)
            record.args = ()
            if record.exc_text:
                record.exc_text = self.redact(record.exc_text)
        return True


def configure_logging() -> RedactSecrets:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    redactor = RedactSecrets([slot.api_key for slot in settings.keys])
    for name in ("", *_LITELLM_LOGGERS):
        logger = logging.getLogger(name)
        if redactor not in logger.filters:
            logger.addFilter(redactor)
        for handler in logger.handlers:
            if redactor not in handler.filters:
                handler.addFilter(redactor)
    return redactor
