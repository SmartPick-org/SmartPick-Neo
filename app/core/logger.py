import logging
import os
import sys
import json
from loguru import logger
from datetime import datetime

# --- Intercept Standard Logging ---
class InterceptHandler(logging.Handler):
    """
    Standard logging 메시지를 Loguru로 전달하는 핸들러.
    이를 통해 uvicorn, fastapi 등의 내부 로그를 통합 관리합니다.
    """
    def emit(self, record):
        # Get corresponding Loguru level if it exists
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

def json_formatter(record):
    """
    CloudWatch, ELK 등에 적합한 단일 라인 JSON 포맷터.
    ISO8601 타임스탬프와 Request ID를 포함합니다.
    """
    subset = {
        "timestamp": record["time"].isoformat(),
        "level": record["level"].name,
        "name": record["name"],
        "message": record["message"],
    }
    
    # request_id가 context에 바인딩되어 있으면 포함
    if "request_id" in record["extra"]:
        subset["request_id"] = record["extra"]["request_id"]
        
    # 기타 extra 데이터 포함
    extra = {k: v for k, v in record["extra"].items() if k != "request_id"}
    if extra:
        subset["context"] = extra
        
    # 예외 정보 포함 (문자열로 변환)
    if record["exception"]:
        subset["exception"] = f"{record['exception'].type}: {record['exception'].value}"

    return json.dumps(subset, ensure_ascii=False)

def init_logger():
    """
    환경 변수(ENV)에 따른 로깅 전략 설정:
    - production: stdout JSON Stream (파일 저장 안함)
    - development: stdout + (선택적) 파일 저장
    """
    env = os.getenv("ENV", "production").lower()
    
    # 1. 기존 핸들러 제거
    logger.remove()
    
    # 2. 로깅 레벨 설정
    log_level = "INFO" if env == "production" else "DEBUG"

    # 3. 환경별 Sink 설정
    if env == "production":
        # 운영 환경: JSON 구조화 로깅 (stdout Only)
        # Loguru의 format 인자에 함수를 사용하면 반환된 문자열이 필드 대체를 시도하므로, 
        # 커스텀 싱크 함수를 직접 사용하여 JSON을 출력합니다.
        def log_sink(message):
            sys.stdout.write(json_formatter(message.record) + "\n")

        logger.add(
            log_sink,
            level=log_level,
            backtrace=False,
            diagnose=False
        )
    else:
        # 개발 환경: 가독성이 좋은 텍스트 로깅 + 파일 백업
        logger.add(
            sys.stdout,
            colorize=True,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
            level=log_level
        )
        
        os.makedirs("logs", exist_ok=True)
        
        def file_sink(message):
            # 파일에는 항상 JSON으로 기록
            log_file = f"logs/dev_{datetime.now().strftime('%Y-%m-%d')}.log"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json_formatter(message.record) + "\n")

        logger.add(
            file_sink,
            level="DEBUG"
        )

    # 4. Standard Library Logging Interception
    # uvicorn 및 기타 라이브러리 로그를 Loguru로 통합
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    
    # 특정 라이브러리 로거들을 InterceptHandler로 강제 연결
    for logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error", "fastapi"):
        mod_logger = logging.getLogger(logger_name)
        mod_logger.handlers = [InterceptHandler()]
        mod_logger.propagate = False

    logger.info(f"Logging initialized in {env} mode (Level: {log_level})")
