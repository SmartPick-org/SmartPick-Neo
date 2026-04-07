import asyncio
import functools
import time
from typing import Any, Callable, TypeVar

from loguru import logger
from pycircuitbreaker import CircuitBreaker, CircuitBreakerException
from pycircuitbreaker.pycircuitbreaker import CircuitBreakerState
from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    stop_after_attempt,
    wait_exponential,
)
import httpx

from app.core import config

T = TypeVar("T")

# -----------------------------------------------------------------------
# Global Circuit Breaker instance
# -----------------------------------------------------------------------
llm_circuit_breaker = CircuitBreaker(
    error_threshold=config.LLM_CB_FAILURE_THRESHOLD,
    recovery_timeout=config.LLM_CB_RECOVERY_TIMEOUT,
)

def is_retryable(exception: Exception) -> bool:
    """
    Determine if the exception is worth retrying.
    Retry ONLY for:
    - Timeout errors (httpx or asyncio)
    - 5xx Server errors
    - 429 Too Many Requests
    """
    if isinstance(exception, (httpx.TimeoutException, asyncio.TimeoutError, TimeoutError)):
        return True
    
    if isinstance(exception, httpx.HTTPStatusError):
        status = exception.response.status_code
        if status == 429 or 500 <= status < 600:
            return True
    
    return False

def with_resilience(func: Callable[..., Any]):
    """
    Refactored Resilience Wrapper (Production Grade)
    Structure: Circuit Breaker -> Retry Loop -> Timeout -> LLM Call
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        # 1. Check Circuit Breaker State (Fail-fast if OPEN)
        if llm_circuit_breaker.state == CircuitBreakerState.OPEN:
            logger.error("[RESILIENCE] Circuit is OPEN. Fast-failing request.")
            raise CircuitBreakerException("Circuit Breaker is OPEN")

        # 2. Execute with Retry Logic
        try:
            result = await _exec_with_retry(func, *args, **kwargs)
            # Success -> Update CB
            llm_circuit_breaker._handle_success()
            return result
        except Exception as e:
            # Final failure after all retries or non-retryable error
            # Update CB if it wasn't a CircuitBreakerException itself
            if not isinstance(e, CircuitBreakerException):
                llm_circuit_breaker._handle_error(e)
            
            logger.error(f"[RESILIENCE] Final request failure: {repr(e)}")
            raise e

    async def _exec_with_retry(inner_func, *args, **kwargs):
        """Handle tenacity retry loop and explicit timeouts."""
        start_time = time.perf_counter()
        
        # tenacity retry predicate
        def retry_predicate(retry_state):
            if retry_state.outcome.failed:
                exc = retry_state.outcome.exception()
                return is_retryable(exc)
            return False

        max_attempts = config.LLM_MAX_RETRIES + 1
        
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            retry=retry_predicate,
            before_sleep=before_sleep_log(logger, "WARNING"),
            reraise=True,
        ):
            with attempt:
                attempt_num = attempt.retry_state.attempt_number
                try:
                    # 3. Enforce explicit request-level timeout
                    async with asyncio.timeout(config.LLM_TIMEOUT):
                        res = await inner_func(*args, **kwargs)
                        
                        latency = time.perf_counter() - start_time
                        logger.info(f"[RESILIENCE] Attempt {attempt_num} success. Latency: {latency:.2f}s")
                        return res
                        
                except Exception as e:
                    retry_will_happen = is_retryable(e) and attempt_num < max_attempts
                    logger.warning(
                        f"[RESILIENCE] Attempt {attempt_num} failed: {repr(e)}. "
                        f"Retryable: {is_retryable(e)}, Will retry: {retry_will_happen}"
                    )
                    raise e
                    
    return wrapper
