#!/usr/bin/env python3
"""
PDF Parsing Optimization Pipeline — JSON Generation Script

For every markdown file in each version directory (1–6), generates a JSON
using the same LLM prompt as the chosen scripts/generate_json_vN.py.

Output: datasets/parsing_optimization/json/version{N}/{slug}.json

Usage:
    python generate_json_versions.py                    # all versions, default schema
    python generate_json_versions.py --schema 5         # use v5 prompt/validator
    python generate_json_versions.py --versions 1 6
    python generate_json_versions.py --pdf "Mr.Life"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# ── Paths ────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
PROJECT_ROOT = BASE_DIR.parents[1]

sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

# ── Shared project imports ───────────────────────────────────
from scripts.sub_categories import build_prompt_block
from app.utils.md_table_refine import fix_markdown_text
from cost_tracker import CostTracker

JSON_OUT_DIR = BASE_DIR / "json"
MAX_MARKDOWN_CHARS = 15_000

# ─────────────────────────────────────────────────────────────
# ★ JSON schema version selector
#
# Change this constant to switch the generation schema globally,
# or pass --schema N on the command line to override per run.
#
# Supported values: 3, 4, 5
# ─────────────────────────────────────────────────────────────
DEFAULT_SCHEMA_VERSION: int = 4


def _load_schema(schema_version: int) -> tuple:
    """
    Lazily import the prompt, parse function, and validator
    for the requested JSON schema version.

    Returns: (prompt_str, parse_json_response_fn, validate_fn)
    """
    if schema_version == 3:
        from scripts.generate_json_v3 import (
            CONVERT_V3_PROMPT as prompt,
            parse_json_response,
            validate_v3 as validate,
        )
    elif schema_version == 4:
        from scripts.generate_json_v4 import (
            CONVERT_V4_PROMPT as prompt,
            parse_json_response,
            validate_v4 as validate,
        )
    elif schema_version == 5:
        from scripts.generate_json_v5 import (
            CONVERT_V5_PROMPT as prompt,
            parse_json_response,
            validate_v5 as validate,
        )
    else:
        raise ValueError(
            f"Unsupported schema version: {schema_version}. Choose 3, 4, or 5."
        )
    return prompt, parse_json_response, validate


# ─────────────────────────────────────────────────────────────
# Company detection from markdown filename
# ─────────────────────────────────────────────────────────────

def _detect_company(content: str) -> tuple[str, str] | None:
    """
    Detect the card company from the markdown file's text content.
    Searches for known company keywords; returns (company_en, company_kr) or None.
    """
    checks = [
        (["신한카드", "신한은행", "Shinhan"],      "shinhan", "신한카드"),
        (["현대카드", "Hyundai Card"],              "hyundai", "현대카드"),
        (["삼성카드", "Samsung Card"],              "samsung", "삼성카드"),
        (["KB국민카드", "KB카드", "국민카드"],      "kb",      "KB국민카드"),
        (["롯데카드", "Lotte Card"],                "lotte",   "롯데카드"),
        (["우리카드", "Woori Card"],                "woori",   "우리카드"),
        (["하나카드", "Hana Card"],                 "hana",    "하나카드"),
        (["농협카드", "NH카드", "NH농협"],          "nh",      "NH농협카드"),
    ]
    for keywords, company_en, company_kr in checks:
        if any(kw in content for kw in keywords):
            return company_en, company_kr
    return None


def _to_slug(stem: str) -> str:
    """Convert a markdown file stem to a filesystem-safe slug."""
    slug = stem.replace(" ", "_").replace("+", "plus")
    # Remove characters that are awkward in filenames
    for ch in ["(", ")", "/", "\\", ":", "*", "?", '"', "<", ">", "|"]:
        slug = slug.replace(ch, "_")
    return slug


# ─────────────────────────────────────────────────────────────
# LLM call
# ─────────────────────────────────────────────────────────────

def _generate_json(
    markdown: str,
    company_kr: str,
    *,
    prompt_str: str,
    parse_fn,
    tracker: CostTracker,
    version: int,
    pdf_name: str,
) -> dict | None:
    """Call solar-pro2 with the chosen schema prompt; return parsed dict or None."""
    from openai import OpenAI

    client = OpenAI(
        api_key=os.environ["UPSTAGE_API_KEY"],
        base_url="https://api.upstage.ai/v1/solar",
    )

    # Apply table normalisation (same as generate_json_vN.py scripts)
    markdown = fix_markdown_text(markdown)

    # Truncate to token-safe length
    if len(markdown) > MAX_MARKDOWN_CHARS:
        markdown = markdown[:MAX_MARKDOWN_CHARS] + "\n\n... (이하 생략)"

    prompt = prompt_str.format(
        company=company_kr,
        markdown_content=markdown,
        sub_category_rules=build_prompt_block(),
    )

    try:
        resp = client.chat.completions.create(
            model="solar-pro2",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        if resp.usage:
            tracker.log_solar_llm(
                version=version,
                pdf=pdf_name,
                purpose="json generation",
                input_tokens=resp.usage.prompt_tokens,
                output_tokens=resp.usage.completion_tokens,
                phase="process",
            )
        raw = resp.choices[0].message.content.strip()
        return parse_fn(raw)
    except Exception as exc:
        print(f"LLM call failed: {exc}")
        return None


# ─────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────

def run(
    versions: list[int] | None = None,
    pdf_filter: str | None = None,
    schema_version: int = DEFAULT_SCHEMA_VERSION,
) -> None:
    prompt_str, parse_fn, validate_fn = _load_schema(schema_version)
    print(f"Using JSON schema version: v{schema_version}")

    tracker = CostTracker()
    target_versions = sorted(versions or [1, 2, 3, 4, 5, 6])

    for ver in target_versions:
        version_dir = BASE_DIR / f"version{ver}"
        md_files = sorted(version_dir.glob("*.md"))

        if pdf_filter:
            md_files = [f for f in md_files if pdf_filter.lower() in f.name.lower()]

        if not md_files:
            print(f"\nVersion {ver}: no markdown files — skipping")
            continue

        out_dir = JSON_OUT_DIR / f"version{ver}"
        out_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n{'='*60}")
        print(f"Version {ver} — generating JSON for {len(md_files)} file(s)")
        print("=" * 60)

        for md_path in md_files:
            print(f"  {md_path.name} ... ", end="", flush=True)

            markdown = md_path.read_text(encoding="utf-8")

            company_info = _detect_company(markdown)
            if not company_info:
                print("SKIPPED (could not detect card company from file content)")
                continue
            _, company_kr = company_info

            result = _generate_json(
                markdown,
                company_kr,
                prompt_str=prompt_str,
                parse_fn=parse_fn,
                tracker=tracker,
                version=ver,
                pdf_name=md_path.name,
            )

            if result is None:
                print("FAILED")
                continue

            validate_fn(result)  # prints warnings in-place

            slug = _to_slug(md_path.stem)
            out_path = out_dir / f"{slug}.json"
            out_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            card_name = result.get("card_meta", {}).get("card_name", "?")
            print(f"OK → json/version{ver}/{out_path.name}  [{card_name}]")

    tracker.print_report()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate JSON from each parsing version's markdown files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--versions",
        nargs="+",
        type=int,
        choices=range(1, 7),
        metavar="N",
        help="Parsing versions to process (default: all 1–6)",
    )
    parser.add_argument(
        "--pdf",
        metavar="FILTER",
        help="Only process files whose name contains FILTER",
    )
    parser.add_argument(
        "--schema",
        type=int,
        choices=[3, 4, 5],
        default=DEFAULT_SCHEMA_VERSION,
        metavar="N",
        help=f"JSON schema version to use: 3, 4, or 5 (default: {DEFAULT_SCHEMA_VERSION})",
    )
    args = parser.parse_args()
    run(versions=args.versions, pdf_filter=args.pdf, schema_version=args.schema)


if __name__ == "__main__":
    main()
