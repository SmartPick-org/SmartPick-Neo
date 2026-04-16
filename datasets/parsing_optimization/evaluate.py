#!/usr/bin/env python3
"""
PDF Parsing Optimization Pipeline — Evaluation Script

For every PDF in version0/, extracts a reference text, then uses solar-pro2
to evaluate each available version (1–6) on:
  • Information coverage — is all content from the original PDF present?
  • Table quality      — are all tables well represented?

Results are saved to results/ as a JSON file and a Markdown report.

Usage:
    python evaluate.py                       # all versions, all PDFs
    python evaluate.py --versions 1 3 6     # selected versions
    python evaluate.py --pdf "Mr.Life"      # PDFs matching substring
    python evaluate.py --versions 5 6 --pdf "Discount"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from cost_tracker import CostTracker

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

BASE_DIR = Path(__file__).parent
VERSION0_DIR = BASE_DIR / "version0"
RESULTS_DIR = BASE_DIR / "results"

VERSION_LABELS: dict[int, str] = {
    1: "Version 1 — Upstage → Markdown",
    2: "Version 2 — Datalab → Markdown",
    3: "Version 3 — Upstage → HTML → Markdown",
    4: "Version 4 — Datalab → HTML → Markdown",
    5: "Version 5 — Upstage → HTML + LLM tables → Markdown",
    6: "Version 6 — Hand-crafted (gold standard)",
}

# ─────────────────────────────────────────────────────────────
# Reference extraction
# ─────────────────────────────────────────────────────────────

def extract_reference(pdf_path: Path) -> str:
    """
    Extract the full text of a PDF as markdown using pymupdf4llm.
    This serves as the ground-truth reference for evaluation.
    """
    import pymupdf4llm  # pip install pymupdf4llm

    content = pymupdf4llm.to_markdown(str(pdf_path))
    if isinstance(content, list):
        content = "\n\n".join(str(c) for c in content if c)
    return content.strip()


# ─────────────────────────────────────────────────────────────
# File matching
# ─────────────────────────────────────────────────────────────

def _normalise(text: str) -> str:
    """Lowercase, collapse whitespace/underscores/hyphens for fuzzy matching."""
    text = text.lower()
    text = re.sub(r"[_\-]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _score_match(pdf_stem: str, md_stem: str) -> int:
    """
    Return a match score between a PDF stem and a markdown file stem.
    Higher is better; 0 means no overlap.
    """
    a = _normalise(pdf_stem)
    b = _normalise(md_stem)
    if a == b:
        return 1000
    if b in a or a in b:
        return 500
    # Word-overlap score
    words_a = set(a.split())
    words_b = set(b.split())
    common = words_a & words_b
    # Discard very short words that appear everywhere
    common = {w for w in common if len(w) > 1}
    return len(common)


def find_version_file(version_dir: Path, pdf_stem: str) -> Path | None:
    """Find the best-matching .md file in version_dir for the given PDF stem."""
    candidates = list(version_dir.glob("*.md"))
    if not candidates:
        return None
    scored = [(c, _score_match(pdf_stem, c.stem)) for c in candidates]
    scored.sort(key=lambda x: x[1], reverse=True)
    best_file, best_score = scored[0]
    return best_file if best_score > 0 else None


# ─────────────────────────────────────────────────────────────
# Smart truncation
# ─────────────────────────────────────────────────────────────

def _smart_sample(text: str, max_chars: int = 6000) -> str:
    """
    Return a representative sample of text by taking beginning, middle,
    and end sections.  Includes markers so the LLM knows the document
    was sampled.
    """
    if len(text) <= max_chars:
        return text
    chunk = max_chars // 3
    mid_start = len(text) // 2 - chunk // 2
    beginning = text[:chunk]
    middle = text[mid_start: mid_start + chunk]
    end = text[-chunk:]
    return (
        beginning
        + "\n\n[... MIDDLE SECTION OMITTED FOR BREVITY ...]\n\n"
        + middle
        + "\n\n[... END SECTION OMITTED FOR BREVITY ...]\n\n"
        + end
    )


# ─────────────────────────────────────────────────────────────
# LLM evaluation
# ─────────────────────────────────────────────────────────────

EVAL_SYSTEM = (
    "You are an expert evaluator of Korean credit card document parsing. "
    "Always respond with valid JSON and nothing else."
)

EVAL_PROMPT = """\
You are evaluating how well a parsed document version captures the content of a Korean credit card terms PDF.

The ORIGINAL REFERENCE was extracted directly from the PDF.
The PARSED VERSION is one automated or manual processing of that same PDF.

## Critical evaluation rules

**Format is irrelevant. Logic and completeness are everything.**

- A markdown table, a bullet list, and a natural language paragraph are all equally valid
  as long as the information and its relationships are correctly expressed.
- Do NOT penalise a version for presenting information in prose instead of a table.
- DO penalise a version if the logical relationships between pieces of information are lost.

**Pay special attention to conditional relationships**, especially those originally expressed
through merged table cells. A common failure mode is:

  Original table: columns A, B, C where column C is a merged cell spanning rows 1–3,
  meaning condition C applies to benefits A1/B1, A2/B2, and A3/B3.

  Bad parse: shows C only once at the end, making it look like a standalone item
  rather than a condition on all three benefits → this is an information error, not a format error.

  Good parse: expresses — in any format — that condition C applies to each of the three benefits.

## Criteria

Return a JSON object with exactly these keys:

{{
  "information_coverage_score": <integer 0–10>,
  "information_coverage_notes": "<which facts or sections are missing or present — be specific>",
  "logical_accuracy_score": <integer 0–10>,
  "logical_accuracy_notes": "<are relationships, conditions, and applicability correctly expressed? cite specific examples of errors or correct representations>",
  "overall_assessment": "<1–2 sentence summary>",
  "total_score": <average of the two scores, one decimal>
}}

## Scoring guide (applies to both criteria)
  10 = perfect
   8 = minor omissions or negligible errors
   6 = noticeable gaps or a few logical errors but core content intact
   4 = significant information loss or multiple logical errors
   2 = major portions missing or logic largely broken
   0 = completely missing or unreadable

---
## ORIGINAL REFERENCE (from PDF via pymupdf4llm)
{reference}

---
## PARSED VERSION
{parsed}
"""


def evaluate_version(
    client,
    reference: str,
    parsed_content: str,
    version_label: str,
    max_chars: int = 6000,
    tracker: CostTracker | None = None,
    tracker_version: str = "",
    tracker_pdf: str = "",
) -> dict:
    ref_sample = _smart_sample(reference, max_chars)
    parsed_sample = _smart_sample(parsed_content, max_chars)

    prompt = EVAL_PROMPT.format(reference=ref_sample, parsed=parsed_sample)

    try:
        resp = client.chat.completions.create(
            model="solar-pro2",
            messages=[
                {"role": "system", "content": EVAL_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )
        if tracker and resp.usage:
            tracker.log_solar_llm(
                version=tracker_version,
                pdf=tracker_pdf,
                purpose="evaluation",
                input_tokens=resp.usage.prompt_tokens,
                output_tokens=resp.usage.completion_tokens,
                phase="evaluate",
            )
        raw = resp.choices[0].message.content.strip()
        # Extract JSON even if the model wraps it in markdown code fences
        json_match = re.search(r"\{[\s\S]*\}", raw)
        if json_match:
            result = json.loads(json_match.group())
        else:
            result = json.loads(raw)
    except Exception as exc:
        result = {
            "information_coverage_score": None,
            "table_quality_score": None,
            "total_score": None,
            "overall_assessment": f"Evaluation failed: {exc}",
            "error": str(exc),
        }

    result["version_label"] = version_label
    return result


# ─────────────────────────────────────────────────────────────
# Report generation
# ─────────────────────────────────────────────────────────────

def _build_report(all_results: dict[str, list[dict]], timestamp: str) -> str:
    lines: list[str] = []
    lines.append("# PDF Parsing Version Comparison Report\n")
    lines.append(f"**Generated:** {timestamp}\n\n")
    lines.append(
        "Evaluation performed by solar-pro2 comparing each version against "
        "reference text extracted with pymupdf4llm.\n\n"
    )
    lines.append("---\n\n")

    for pdf_name, results in sorted(all_results.items()):
        lines.append(f"## {pdf_name}\n\n")

        # Summary table
        lines.append("| Version | Info Coverage | Logical Accuracy | Total |\n")
        lines.append("|---------|:-------------:|:----------------:|:-----:|\n")

        sorted_results = sorted(
            results,
            key=lambda r: r.get("total_score") or 0,
            reverse=True,
        )
        for r in sorted_results:
            ic = r.get("information_coverage_score")
            la = r.get("logical_accuracy_score")
            tot = r.get("total_score")
            ic_str = f"{ic}/10" if ic is not None else "—"
            la_str = f"{la}/10" if la is not None else "—"
            tot_str = f"{tot}/10" if tot is not None else "—"
            lines.append(f"| {r['version_label']} | {ic_str} | {la_str} | {tot_str} |\n")

        lines.append("\n### Detailed Notes\n\n")
        for r in results:
            lines.append(f"**{r['version_label']}**\n\n")
            if "error" in r:
                lines.append(f"> Error: {r['error']}\n\n")
            else:
                lines.append(
                    f"- **Info coverage:** {r.get('information_coverage_notes', '—')}\n"
                )
                lines.append(
                    f"- **Logical accuracy:** {r.get('logical_accuracy_notes', '—')}\n"
                )
                lines.append(
                    f"- **Overall:** {r.get('overall_assessment', '—')}\n"
                )
            lines.append("\n")

        lines.append("---\n\n")

    return "".join(lines)


# ─────────────────────────────────────────────────────────────
# Main runner
# ─────────────────────────────────────────────────────────────

def run(versions: list[int] | None = None, pdf_filter: str | None = None) -> None:
    from openai import OpenAI

    client = OpenAI(
        api_key=os.environ["UPSTAGE_API_KEY"],
        base_url="https://api.upstage.ai/v1/solar",
    )
    tracker = CostTracker()

    pdf_files = sorted(VERSION0_DIR.glob("*.pdf"))
    if pdf_filter:
        pdf_files = [p for p in pdf_files if pdf_filter.lower() in p.name.lower()]
    if not pdf_files:
        print("No PDF files found in version0/")
        sys.exit(1)

    target_versions = sorted(versions or list(VERSION_LABELS.keys()))
    all_results: dict[str, list[dict]] = {}

    for pdf_path in pdf_files:
        print(f"\n{'='*60}")
        print(f"PDF: {pdf_path.name}")
        print("=" * 60)

        print("  Extracting reference text from PDF ... ", end="", flush=True)
        try:
            reference = extract_reference(pdf_path)
            print(f"OK ({len(reference):,} chars)")
        except Exception as exc:
            print(f"FAILED: {exc} — skipping this PDF")
            continue

        results: list[dict] = []

        for ver in target_versions:
            label = VERSION_LABELS.get(ver, f"Version {ver}")
            version_dir = BASE_DIR / f"version{ver}"

            md_path = find_version_file(version_dir, pdf_path.stem)
            if md_path is None:
                print(f"  {label}: no matching file in {version_dir.name}/ — skipped")
                continue

            try:
                parsed_content = md_path.read_text(encoding="utf-8")
            except Exception as exc:
                print(f"  {label}: could not read {md_path.name}: {exc}")
                continue

            print(
                f"  Evaluating {label} (matched → {md_path.name}) ... ",
                end="",
                flush=True,
            )
            result = evaluate_version(
                client,
                reference,
                parsed_content,
                label,
                tracker=tracker,
                tracker_version=f"eval_v{ver}",
                tracker_pdf=pdf_path.name,
            )
            results.append(result)

            score = result.get("total_score")
            score_str = f"{score}/10" if score is not None else "error"
            print(f"Score: {score_str}")

        all_results[pdf_path.stem] = results

    if not all_results:
        print("No results to save.")
        return

    RESULTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = RESULTS_DIR / f"comparison_{timestamp}.json"
    json_path.write_text(
        json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    report = _build_report(all_results, datetime.now().isoformat(timespec="seconds"))
    report_path = RESULTS_DIR / f"comparison_{timestamp}.md"
    report_path.write_text(report, encoding="utf-8")

    print(f"\nResults saved:")
    print(f"  JSON   → {json_path.relative_to(BASE_DIR)}")
    print(f"  Report → {report_path.relative_to(BASE_DIR)}")

    tracker.print_report()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate PDF parsing versions with solar-pro2",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--versions",
        nargs="+",
        type=int,
        choices=list(VERSION_LABELS.keys()),
        metavar="N",
        help="Versions to evaluate (default: all 1–6)",
    )
    parser.add_argument(
        "--pdf",
        metavar="FILTER",
        help="Only evaluate PDFs whose filename contains FILTER",
    )
    args = parser.parse_args()
    run(versions=args.versions, pdf_filter=args.pdf)


if __name__ == "__main__":
    main()