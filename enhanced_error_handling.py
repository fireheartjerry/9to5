"""Enhanced error handling -- re-exports the canonical error_handling module.

The implementation lives in ``error_handling``; this module provides the
``enhanced_error_handling`` name required by the deliverable spec.
"""
from error_handling import (  # noqa: F401
    LOG,
    MAX_RETRIES,
    RETRY_DELAY_SECONDS,
    RetryExhausted,
    retryTask,
)
