import pdfplumber
import os
import re
from typing import Dict, Any, Optional


class PDFExtractor:
    @staticmethod
    def extract(file_path: str) -> Dict[str, Any]:
        """
        Extract text and metadata from a PDF file.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"PDF file not found: {file_path}")

        file_size = os.path.getsize(file_path)
        text_content = []
        page_count = 0

        try:
            with pdfplumber.open(file_path) as pdf:
                page_count = len(pdf.pages)
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        text_content.append(text)

            full_text = "\n".join(text_content)
            normalized_text = PDFExtractor._normalize_text(full_text)

            return {
                "file_size_bytes": file_size,
                "page_count": page_count,
                "text": normalized_text,
                "ocr_required": False,  # Placeholder logic
            }

        except Exception as e:
            print(f"Error extracting text from {file_path}: {e}")
            return {
                "file_size_bytes": file_size,
                "page_count": 0,
                "text": "",
                "error": str(e),
            }

    @staticmethod
    def _normalize_text(text: str) -> str:
        """
        Clean extracted text:
        - Normalize unicode
        - Collapse multiple spaces/newlines
        """
        if not text:
            return ""

        # Replace multiple whitespace characters with a single space
        text = re.sub(r"\s+", " ", text)
        return text.strip()
