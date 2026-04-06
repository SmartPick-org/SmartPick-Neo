from pathlib import Path

from fastapi import APIRouter

from app.core.config import get_llm
from app.repositories.card_repo import DatasetCardRepository
from app.repositories.digest_repo import DigestRepository
from app.schemas.recommend import QARequest, QAResponse, RecommendRequest, RecommendResponse
from app.services.card_service import CardRecommendService
from app.services.explain_service import ExplainService


router = APIRouter(prefix="/cards", tags=["cards"])

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASETS_DIR = PROJECT_ROOT / "datasets" / "json_v3"
DIGEST_DIR = PROJECT_ROOT / "datasets" / "digest"


@router.post("/recommend", response_model=RecommendResponse)
def recommend_cards(payload: RecommendRequest) -> RecommendResponse:
    card_repo = DatasetCardRepository(DATASETS_DIR)
    digest_repo = DigestRepository(DIGEST_DIR)
    recommend_service = CardRecommendService(card_repo)
    explain_service = ExplainService(get_llm())

    filtered = recommend_service.filter_cards(payload.total_budget, payload.category_spending)
    calc_results = recommend_service.calculate_benefits(filtered, payload.total_budget, payload.category_spending)
    ranked = recommend_service.rank_top(calc_results, top_n=3)

    # 모든 상위 카드의 Digest를 로드하여 상세 설명 생성에 대비
    digests = [digest_repo.get_digest(card.get("_card_data", {})) for card in ranked]
    top_digest = digests[0] if digests else ""

    explanation = explain_service.explain(payload.total_budget, payload.category_spending, ranked, top_digest)
    recommended_cards = explain_service.build_recommended_cards(ranked, explanation, digests)

    return RecommendResponse(recommended_cards=recommended_cards, explanation=explanation)


@router.post("/qa", response_model=QAResponse)
def answer_qa(payload: QARequest) -> QAResponse:
    explain_service = ExplainService(get_llm())
    answer = explain_service.answer_qa(payload.raw_data, payload.question)
    return QAResponse(answer=answer)
