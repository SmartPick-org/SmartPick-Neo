import re
from typing import Optional, List, Pattern, Tuple
from apps.backend.crawler.config import TARGET_CARDS, CARD_NAME_MAPPING


class CardMatcher:
    def __init__(self):
        self.target_cards = TARGET_CARDS
        self.mapping = CARD_NAME_MAPPING
        self.patterns: dict[str, List[Tuple[str, Pattern]]] = {}
        self._compile_patterns()

    def _compile_patterns(self):
        """Pre-compile regex patterns for efficiency."""
        for company, cards in self.target_cards.items():
            # Sort cards by length descending to match longest specific names first
            # (e.g. "Deep Dream Platinum+" before "Deep Dream")
            sorted_cards = sorted(cards, key=len, reverse=True)

            self.patterns[company] = []
            for card in sorted_cards:
                # Regex construction:
                # 1. Escape special chars (like + in Platinum+)
                # 2. Allow flexible whitespace (spaces become \s*)
                # 3. Handle specific suffixes like Edition2
                escaped = re.escape(card)
                pattern_str = escaped.replace(r"\ ", r"\s*")

                if "Edition2" in card:
                    pattern_str = pattern_str.replace(r"\(", r"\s*\(").replace(
                        r"\)", r"\)"
                    )

                self.patterns[company].append(
                    (card, re.compile(pattern_str, re.IGNORECASE))
                )

    def normalize_card_name(self, raw_name: str) -> str:
        """Normalize card name using the mapping config."""
        if not raw_name:
            return ""
        for key, value in self.mapping.items():
            if key.lower() in raw_name.lower():
                return value
        return raw_name

    def match_card(self, company: str, text_content: str) -> Optional[str]:
        """
        Identify if a text matches one of the target cards.
        Returns the official card name if found, else None.
        """
        if not text_content or company not in self.patterns:
            return None

        # 1. Direct normalized check first
        normalized_text = self.normalize_card_name(text_content)

        # 2. Regex match against official list (longest first)
        for official_name, pattern in self.patterns[company]:
            if pattern.search(normalized_text) or pattern.search(text_content):
                return official_name

        return None

    def find_best_match(self, company: str, candidates: List[str]) -> Optional[str]:
        """
        Check a list of candidate strings (e.g., [filename, title, link_text])
        and return the first confident match.
        """
        for text in candidates:
            if not text:
                continue
            match = self.match_card(company, text)
            if match:
                return match
        return None
