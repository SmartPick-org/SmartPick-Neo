from functools import lru_cache
from fastapi import Depends

from app.core.config import DATASETS_DIR, DIGEST_DIR, get_llm
from app.repositories.card_repo import DatasetCardRepository, CardRepository
from app.repositories.digest_repo import DigestRepository
from app.services.card_service import CardRecommendService
from app.services.explain_service import ExplainService


@lru_cache()
def get_card_repository() -> CardRepository:
    """
    CardRepository 인스턴스를 캐싱하여 반환합니다.
    최초 호출 시에만 생성하며, 이후 요청에서는 동일 인스턴스를 재사용합니다.
    """
    return DatasetCardRepository(DATASETS_DIR)


@lru_cache()
def get_digest_repository() -> DigestRepository:
    """
    DigestRepository 인스턴스를 캐싱하여 반환합니다.
    """
    return DigestRepository(DIGEST_DIR)


def get_recommend_service(
    card_repo: CardRepository = Depends(get_card_repository),
) -> CardRecommendService:
    """
    CardRecommendService를 생성하여 반환합니다.
    Repository는 주입(Injection)받아 사용합니다.
    """
    return CardRecommendService(card_repo)


def get_explain_service(
    llm=Depends(get_llm),
) -> ExplainService:
    """
    ExplainService를 생성하여 반환합니다.
    LLM 클라이언트는 캐싱된 get_llm()을 통해 주입받습니다.
    """
    return ExplainService(llm)
