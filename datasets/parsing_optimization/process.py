#!/usr/bin/env python3
"""
PDF Parsing Optimization Pipeline — Processing Script

Runs PDF processing versions 1–5 on all PDFs in version0/ and saves
outputs to the corresponding version directories.

Versions:
  1  Upstage Document Parse → Markdown (direct)
  2  Datalab Document Parse → Markdown (direct)
  3  Upstage Document Parse → HTML → Markdown
  4  Datalab Document Parse → HTML → Markdown
  5  Upstage Document Parse → HTML → LLM table explanations → Markdown

Usage:
    python process.py                       # all versions, all PDFs
    python process.py --versions 1 3 5     # selected versions
    python process.py --pdf "Mr.Life"      # PDFs matching substring
    python process.py --versions 2 --pdf "Discount"

Notes:
  Versions 2 & 4 use the Datalab SDK (pip install datalab-python-sdk).
  The SDK handles async polling automatically; mode="accurate" is used
  for best results on complex Korean credit card PDFs.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

from cost_tracker import CostTracker

# Load .env from repo root
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

BASE_DIR = Path(__file__).parent
VERSION0_DIR = BASE_DIR / "version0"


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _get_pdf_files(pdf_filter: str | None = None) -> list[Path]:
    files = sorted(VERSION0_DIR.glob("*.pdf"))
    if pdf_filter:
        files = [f for f in files if pdf_filter.lower() in f.name.lower()]
    return files


def _count_pdf_pages(pdf_path: Path) -> int:
    import pdfplumber
    with pdfplumber.open(str(pdf_path)) as pdf:
        return len(pdf.pages)


def _save(version: int, pdf_path: Path, content: str) -> Path:
    out_dir = BASE_DIR / f"version{version}"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{pdf_path.stem}.md"
    out_path.write_text(content, encoding="utf-8")
    return out_path


def _html_to_markdown(html: str) -> str:
    """Convert HTML to markdown via html2text."""
    import html2text  # pip install html2text

    h = html2text.HTML2Text()
    h.ignore_links = False
    h.ignore_images = True
    h.body_width = 0        # no line-wrapping
    h.unicode_snob = True
    h.protect_links = False
    return h.handle(html).strip()


def _get_solar_client():
    """Return an OpenAI-compatible client pointed at Upstage solar-pro2."""
    from openai import OpenAI

    return OpenAI(
        api_key=os.environ["UPSTAGE_API_KEY"],
        base_url="https://api.upstage.ai/v1/solar",
    )


# ─────────────────────────────────────────────────────────────
# Version 1 — Upstage → Markdown
# ─────────────────────────────────────────────────────────────

def process_v1(pdf_path: Path, tracker: CostTracker | None = None) -> str:
    """Parse PDF directly to markdown using Upstage Document Parse API."""
    from langchain_upstage import UpstageDocumentParseLoader

    loader = UpstageDocumentParseLoader(
        str(pdf_path),
        output_format="markdown",
        split="page",
    )
    docs = loader.load()
    if tracker:
        tracker.log_upstage_parse(version=1, pdf=pdf_path.name, pages=len(docs))
    if not docs:
        return ""
    md = "\n\n".join(doc.page_content for doc in docs)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


# ─────────────────────────────────────────────────────────────
# Datalab shared helper  (used by v2 and v4)
# ─────────────────────────────────────────────────────────────

def _datalab_convert(pdf_path: Path, output_format: str):
    """
    Convert a PDF via the Datalab SDK.
    nest_asyncio is required because the SDK uses asyncio internally.
    """
    import nest_asyncio
    from datalab_sdk import DatalabClient, ConvertOptions

    nest_asyncio.apply()

    client = DatalabClient(api_key=os.environ["DATALAB_API_KEY"])
    options = ConvertOptions(
        output_format=output_format,
        mode="balanced",
        disable_image_extraction=True,
        disable_image_captions=True,
        skip_cache=True,
    )
    return client.convert(str(pdf_path), options=options)


# ─────────────────────────────────────────────────────────────
# Version 2 — Datalab → Markdown
# ─────────────────────────────────────────────────────────────

def process_v2(pdf_path: Path, tracker: CostTracker | None = None) -> str:
    """Parse PDF directly to markdown using Datalab Document Convert API."""
    result = _datalab_convert(pdf_path, output_format="markdown")
    if tracker:
        tracker.log_datalab_parse(
            version=2, pdf=pdf_path.name,
            pages=result.page_count or _count_pdf_pages(pdf_path),
        )
    if result.parse_quality_score is not None:
        print(f"[quality={result.parse_quality_score:.1f}/5.0] ", end="", flush=True)
    return result.markdown or ""


# ─────────────────────────────────────────────────────────────
# Version 3 — Upstage → HTML → Markdown
# ─────────────────────────────────────────────────────────────

def process_v3(pdf_path: Path, tracker: CostTracker | None = None) -> str:
    """Parse PDF to HTML with Upstage, then convert HTML → Markdown."""
    from langchain_upstage import UpstageDocumentParseLoader

    loader = UpstageDocumentParseLoader(
        str(pdf_path),
        output_format="html",
        split="page",
    )
    docs = loader.load()
    if tracker:
        tracker.log_upstage_parse(version=3, pdf=pdf_path.name, pages=len(docs))
    if not docs:
        return ""
    html = "\n".join(doc.page_content for doc in docs)
    return _html_to_markdown(html)


# ─────────────────────────────────────────────────────────────
# Version 4 — Datalab → HTML → Markdown
# ─────────────────────────────────────────────────────────────

def process_v4(pdf_path: Path, tracker: CostTracker | None = None) -> str:
    """Parse PDF to HTML with Datalab, then convert HTML → Markdown."""
    result = _datalab_convert(pdf_path, output_format="html")
    if tracker:
        tracker.log_datalab_parse(
            version=4, pdf=pdf_path.name,
            pages=result.page_count or _count_pdf_pages(pdf_path),
        )
    if result.parse_quality_score is not None:
        print(f"[quality={result.parse_quality_score:.1f}/5.0] ", end="", flush=True)
    return _html_to_markdown(result.html or "")


# ─────────────────────────────────────────────────────────────
# Version 5 — Upstage → HTML → LLM table explanations → Markdown
# ─────────────────────────────────────────────────────────────

def process_v5(pdf_path: Path, tracker: CostTracker | None = None) -> str:
    """
    1. Parse PDF → HTML via Upstage Document Parse.
    2. Locate every <table> element with BeautifulSoup.
    3. Send each table's HTML to solar-pro2 → natural-language description.
    4. Replace the <table> with a <p> containing the description.
    5. Convert the modified HTML → Markdown.
    """
    from langchain_upstage import UpstageDocumentParseLoader
    from bs4 import BeautifulSoup

    # Step 1 — PDF → HTML
    loader = UpstageDocumentParseLoader(
        str(pdf_path),
        output_format="html",
        split="page",
    )
    docs = loader.load()
    if tracker:
        tracker.log_upstage_parse(version=5, pdf=pdf_path.name, pages=len(docs))
    if not docs:
        return ""
    html = "\n".join(doc.page_content for doc in docs)

    # Step 2 — Replace tables
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")

    if tables:
        client = _get_solar_client()
        for idx, table in enumerate(tables, start=1):
            table_html = str(table)
            print(f"    → Table {idx}/{len(tables)}: asking solar-pro2 ...", end="", flush=True)
            try:
                resp = client.chat.completions.create(
                    model="solar-pro2",
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "당신은 문서 분석 전문가입니다. "
                                "한국 신용카드 약관 문서의 HTML 표를 받으면, "
                                "표에 담긴 모든 정보(수치, 조건, 혜택 등)를 빠짐없이 자연어로 설명하세요. "
                                "한국어로 작성하세요."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                "다음 HTML 표의 모든 정보를 자연어로 설명해주세요:\n\n"
                                + table_html
                            ),
                        },
                    ],
                    temperature=0.0,
                )
                description = resp.choices[0].message.content.strip()
                if tracker and resp.usage:
                    tracker.log_solar_llm(
                        version=5,
                        pdf=pdf_path.name,
                        purpose=f"table {idx} explanation",
                        input_tokens=resp.usage.prompt_tokens,
                        output_tokens=resp.usage.completion_tokens,
                    )
                p = soup.new_tag("p")
                p.string = description
                table.replace_with(p)
                print(f" done ({len(description)} chars)")
            except Exception as exc:
                print(f" FAILED ({exc}) — keeping original table")

    # Step 3 — HTML → Markdown
    return _html_to_markdown(str(soup))


# ─────────────────────────────────────────────────────────────
# Registry & runner
# ─────────────────────────────────────────────────────────────

VERSIONS: dict[int, tuple[str, object]] = {
    1: ("Upstage → Markdown", process_v1),
    2: ("Datalab → Markdown", process_v2),
    3: ("Upstage → HTML → Markdown", process_v3),
    4: ("Datalab → HTML → Markdown", process_v4),
    5: ("Upstage → HTML + LLM tables → Markdown", process_v5),
}


def run(versions: list[int] | None = None, pdf_filter: str | None = None) -> None:
    pdf_files = _get_pdf_files(pdf_filter)
    if not pdf_files:
        print("No PDF files found in version0/")
        sys.exit(1)

    target = sorted(versions or list(VERSIONS.keys()))
    tracker = CostTracker()

    for ver in target:
        label, processor = VERSIONS[ver]
        print(f"\n{'='*60}")
        print(f"Version {ver}: {label}")
        print("=" * 60)
        for pdf in pdf_files:
            print(f"  {pdf.name} ... ", end="", flush=True)
            try:
                md = processor(pdf, tracker)
                out = _save(ver, pdf, md)
                rel = out.relative_to(BASE_DIR)
                print(f"OK → {rel}  ({len(md):,} chars)")
            except Exception as exc:
                print(f"FAILED: {exc}")

    tracker.print_report()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run PDF parsing versions 1–5",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--versions",
        nargs="+",
        type=int,
        choices=list(VERSIONS.keys()),
        metavar="N",
        help="Version numbers to run (default: all 1–5)",
    )
    parser.add_argument(
        "--pdf",
        metavar="FILTER",
        help="Only process PDFs whose filename contains FILTER",
    )
    args = parser.parse_args()
    run(versions=args.versions, pdf_filter=args.pdf)


if __name__ == "__main__":
    main()