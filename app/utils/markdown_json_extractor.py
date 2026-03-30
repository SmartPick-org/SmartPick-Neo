import re
from typing import Any, Dict, List

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field


class BenefitChunk(BaseModel):
    category: str = Field(default="General")
    content: str = Field(default="")
    conditions: str = Field(default="")


class CardExtraction(BaseModel):
    card_name: str
    card_company: str
    annual_fee: int = 0
    min_performance: int = 0
    major_categories: str = "General"
    benefits_summary: str = ""
    chunks: List[BenefitChunk] = Field(default_factory=list)


class MarkdownJSONExtractor:
    def __init__(
        self,
        model: str = "solar-pro2",
        max_input_chars: int = 18000,
        max_chunks: int = 12,
    ):
        self.max_input_chars = max_input_chars
        self.max_chunks = max_chunks
        self.llm = None
        self.init_error = ""
        try:
            self.llm = init_chat_model(model=model, temperature=0.0)
        except Exception as exc:
            self.init_error = str(exc)

    def extract(
        self,
        markdown: str,
        card_company: str,
        fallback_card_name: str,
    ) -> Dict[str, Dict[str, Any]]:
        if not markdown.strip():
            return self._heuristic_chunk_map("", card_company, fallback_card_name)

        model_obj: CardExtraction | None = None
        try:
            model_obj = self._extract_with_structured_output(
                markdown=markdown,
                card_company=card_company,
                fallback_card_name=fallback_card_name,
            )
        except Exception:
            model_obj = None

        if model_obj is None:
            return self._heuristic_chunk_map(markdown, card_company, fallback_card_name)

        return self._to_chunk_map(model_obj)

    def _extract_with_structured_output(
        self,
        markdown: str,
        card_company: str,
        fallback_card_name: str,
    ) -> CardExtraction:
        if self.llm is None:
            raise RuntimeError(self.init_error or "LLM is not initialized")

        payload = self._truncate_markdown(markdown)
        structured_llm = self.llm.with_structured_output(CardExtraction)

        system_prompt = f"""
당신은 신용카드 PDF/Markdown을 정형 JSON으로 변환하는 추출기입니다.

반드시 아래 규칙을 지키세요.
1) 데이터에 없는 값은 추측하지 말고 기본값 사용:
   - annual_fee: 0
   - min_performance: 0
   - major_categories: "General"
   - benefits_summary: ""
2) chunks는 혜택 단위로 분리하고, 각 chunk는 category/content/conditions를 포함하세요.
3) card_company는 "{card_company}"를 우선 사용하세요.
4) card_name을 찾기 어렵다면 "{fallback_card_name}"를 사용하세요.
5) 원문 언어(한국어)를 유지하세요.
"""

        raw = structured_llm.invoke(
            [
                SystemMessage(content=system_prompt.strip()),
                HumanMessage(content=payload),
            ]
        )
        if isinstance(raw, CardExtraction):
            return raw
        if isinstance(raw, dict):
            return CardExtraction.model_validate(raw)
        raise RuntimeError("Structured output parsing failed")

    def _truncate_markdown(self, markdown: str) -> str:
        if len(markdown) <= self.max_input_chars:
            return markdown
        half = max(2000, self.max_input_chars // 2)
        return markdown[:half] + "\n\n[...중간 생략...]\n\n" + markdown[-half:]

    def _to_chunk_map(self, model_obj: CardExtraction) -> Dict[str, Dict[str, Any]]:
        chunks = model_obj.chunks[: self.max_chunks]
        if not chunks:
            chunks = [BenefitChunk(category="General", content=model_obj.benefits_summary)]

        out: Dict[str, Dict[str, Any]] = {}
        for idx, item in enumerate(chunks, start=1):
            out[f"chunk{idx}"] = {
                "card_name": model_obj.card_name,
                "card_company": model_obj.card_company,
                "annual_fee": int(model_obj.annual_fee or 0),
                "min_performance": int(model_obj.min_performance or 0),
                "major_categories": model_obj.major_categories or "General",
                "benefits_summary": model_obj.benefits_summary or "",
                "category": (item.category or "General").strip(),
                "content": (item.content or "").strip(),
                "conditions": (item.conditions or "").strip(),
            }
        return out

    def _heuristic_chunk_map(
        self,
        markdown: str,
        card_company: str,
        fallback_card_name: str,
    ) -> Dict[str, Dict[str, Any]]:
        annual_fee = self._extract_annual_fee(markdown)
        min_perf = self._extract_min_performance(markdown)
        summary = self._extract_summary(markdown)
        content = self._extract_content(markdown)
        return {
            "chunk1": {
                "card_name": fallback_card_name,
                "card_company": card_company,
                "annual_fee": annual_fee,
                "min_performance": min_perf,
                "major_categories": "General",
                "benefits_summary": summary,
                "category": "General",
                "content": content,
                "conditions": "",
            }
        }

    def _extract_annual_fee(self, markdown: str) -> int:
        if not markdown:
            return 0
        match = re.search(r"연회비[^0-9]{0,30}(\d[\d,]{2,})", markdown)
        if not match:
            return 0
        return int(match.group(1).replace(",", ""))

    def _extract_min_performance(self, markdown: str) -> int:
        if not markdown:
            return 0

        million_match = re.search(
            r"전월[^0-9]{0,30}(\d{1,3}(?:,\d{3})?)\s*원\s*이상",
            markdown,
        )
        if million_match:
            return int(million_match.group(1).replace(",", ""))

        manwon_match = re.search(r"전월[^0-9]{0,30}(\d{1,3})\s*만원\s*이상", markdown)
        if manwon_match:
            return int(manwon_match.group(1)) * 10000

        return 0

    def _extract_summary(self, markdown: str) -> str:
        text = self._to_plain_text(markdown)
        return text[:220].strip()

    def _extract_content(self, markdown: str) -> str:
        text = self._to_plain_text(markdown)
        return text[:1500].strip()

    def _to_plain_text(self, markdown: str) -> str:
        text = markdown or ""
        text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
