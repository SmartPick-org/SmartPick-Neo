from pathlib import Path

from app.domain.models import CardData


class DigestRepository:
    def __init__(self, digest_dir: Path):
        self.digest_dir = digest_dir

    def get_digest(self, card: CardData) -> str:
        card_meta = card.get("card_meta", {})
        card_id = card_meta.get("card_id", "")
        company = card_meta.get("card_company", "")

        company_dir_map = {
            "KB국민카드": "kb",
            "신한카드": "shinhan",
            "현대카드": "hyundai",
        }
        company_dir = company_dir_map.get(company, "")
        if company_dir:
            digest_dir = self.digest_dir / company_dir
            if digest_dir.exists():
                for md_file in digest_dir.glob("*.md"):
                    if card_id.replace("_", "") in md_file.stem.replace("_", "").replace(" ", "").lower():
                        return md_file.read_text(encoding="utf-8")

        card_name = card_meta.get("card_name", "알 수 없음")
        return f"# {card_name}\n(digest 파일 없음)"
