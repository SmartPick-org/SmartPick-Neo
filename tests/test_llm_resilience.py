import asyncio
import httpx
import pytest
from unittest.mock import AsyncMock
from app.core.resilience import with_resilience, llm_circuit_breaker
from app.core import config
from pycircuitbreaker import CircuitBreakerException, CircuitBreakerState

# Mock config for testing
config.LLM_MAX_RETRIES = 2
config.LLM_CB_FAILURE_THRESHOLD = 3
config.LLM_TIMEOUT = 1.0

@pytest.mark.asyncio
async def test_retry_on_500_error():
    """500 에러 발생 시 재시도가 정상적으로 이루어지는지 확인 (최대 3회 시도)"""
    request = httpx.Request("GET", "http://test.com")
    response = httpx.Response(500, request=request, content=b"Server Error")
    error = httpx.HTTPStatusError("500 Error", request=request, response=response)
    
    # State reset
    llm_circuit_breaker._strategy._error_count = 0
    llm_circuit_breaker._strategy._state = CircuitBreakerState.CLOSED

    mock_func = AsyncMock(side_effect=error)
    resilient_func = with_resilience(mock_func)
    
    with pytest.raises(httpx.HTTPStatusError):
        await resilient_func()
    
    # Initial (1) + Retries (2) = 3 attempts
    assert mock_func.call_count == 3

@pytest.mark.asyncio
async def test_no_retry_on_400_error():
    """400 Bad Request 발생 시 재시도 없이 즉시 종료되는지 확인"""
    request = httpx.Request("GET", "http://test.com")
    response = httpx.Response(400, request=request, content=b"Bad Request")
    error = httpx.HTTPStatusError("400 Error", request=request, response=response)
    
    llm_circuit_breaker._strategy._error_count = 0
    llm_circuit_breaker._strategy._state = CircuitBreakerState.CLOSED

    mock_func = AsyncMock(side_effect=error)
    resilient_func = with_resilience(mock_func)
    
    with pytest.raises(httpx.HTTPStatusError):
        await resilient_func()
    
    # Should fail in 1st attempt
    assert mock_func.call_count == 1

@pytest.mark.asyncio
async def test_explicit_timeout_protection():
    """asyncio.timeout에 의해 호출이 강제 중단되는지 확인"""
    llm_circuit_breaker._strategy._error_count = 0
    llm_circuit_breaker._strategy._state = CircuitBreakerState.CLOSED

    async def slow_func(*args, **kwargs):
        await asyncio.sleep(2.0) # > config.LLM_TIMEOUT(1.0)
        return "too slow"
    
    resilient_func = with_resilience(slow_func)
    
    with pytest.raises(asyncio.TimeoutError):
        await resilient_func()

@pytest.mark.asyncio
async def test_circuit_breaker_wraps_retry_loop():
    """서킷 브레이커가 재시도 루프 전체를 감싸는지 확인 (재시도가 CB 카운트를 중복으로 올리지 않음)"""
    # Threshold=3 이므로, 3번의 큰(resilient) 실패 후 OPEN 되어야 함
    llm_circuit_breaker._strategy._error_threshold = 3
    llm_circuit_breaker._strategy._error_count = 0
    llm_circuit_breaker._strategy._state = CircuitBreakerState.CLOSED
    
    request = httpx.Request("GET", "http://test.com")
    response = httpx.Response(500, request=request, content=b"Server Error")
    error = httpx.HTTPStatusError("500 Error", request=request, response=response)
    
    mock_func = AsyncMock(side_effect=error)
    resilient_func = with_resilience(mock_func)
    
    # 1st resilient call (3 internal attempts)
    with pytest.raises(httpx.HTTPStatusError):
        await resilient_func()
    assert llm_circuit_breaker._strategy._error_count == 1

    # 2nd resilient call
    with pytest.raises(httpx.HTTPStatusError):
        await resilient_func()
    assert llm_circuit_breaker._strategy._error_count == 2

    # 3rd resilient call -> Should OPEN the circuit (error_count=3 >= error_threshold=3)
    with pytest.raises(httpx.HTTPStatusError):
        await resilient_func()
    
    # pycircuitbreaker status logic depends on when threshold is HIT.
    # It seems after 3rd error, count becomes 3 and it triggers OPEN.
    assert llm_circuit_breaker.state == CircuitBreakerState.OPEN
    
    # 4th resilient call -> Should fast-fail with CircuitBreakerException
    with pytest.raises(CircuitBreakerException):
        await resilient_func()
