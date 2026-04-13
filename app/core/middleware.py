import time
import uuid
import json
from typing import Callable, Awaitable
from fastapi import Request, Response
from loguru import logger
from app.utils.masking import mask_dict, mask_pii

async def logging_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """
    모든 요청/응답을 구조화하여 기록하고, Request ID를 주입하는 미들웨어.
    """
    # 1. Request ID 생성 및 추출
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    
    # 2. Context 바인딩 (이후 logger.info 호출 시 extra 데이터로 삽입됨)
    context_logger = logger.bind(
        request_id=request_id,
        method=request.method,
        path=request.url.path,
    )
    
    # 3. Request Body 안전하게 읽기
    # 요청의 body는 stream이므로, 한 번 읽으면 소진됩니다. 
    # 따라서 바이트로 읽은 다음 내부 receive 몽키패치를 통해 다시 주입합니다.
    body_bytes = await request.body()
    
    async def receive():
        return {"type": "http.request", "body": body_bytes}
    
    request._receive = receive  # 재주입
    
    # Truncate 및 마스킹 처리 (로깅 용량 및 식별정보 노출 방지)
    query_params = dict(request.query_params)
    body_str = body_bytes.decode("utf-8", errors="replace") if body_bytes else ""
    
    if len(body_str) > 2000:
        body_str = body_str[:2000] + "...(truncated)"
    
    safe_body = body_str
    if safe_body:
        try:
            # JSON인 경우 깊은 복사 마스킹
            parsed_body = json.loads(safe_body)
            safe_body = mask_dict(parsed_body)
        except json.JSONDecodeError:
            # 그 외는 단순 텍스트 마스킹
            safe_body = mask_pii(safe_body)
    
    context_logger.info(
        "Request Started",
        query_params=query_params,
        request_body=safe_body
    )
    
    # 4. Latency 측정 및 다음 흐름 호출
    start_time = time.perf_counter()
    try:
        response = await call_next(request)
        latency_ms = (time.perf_counter() - start_time) * 1000
        
        # 5. Response 로깅
        context_logger.info(
            "Request Finished",
            status_code=response.status_code,
            latency_ms=round(latency_ms, 2)
        )
        
        # 응답 헤더에 Request ID 추가 (클라이언트/서버 상호 디버깅 용이)
        response.headers["X-Request-ID"] = request_id
        return response
        
    except Exception as e:
        latency_ms = (time.perf_counter() - start_time) * 1000
        context_logger.exception(
            "Request Failed with Exception",
            latency_ms=round(latency_ms, 2)
        )
        raise e
