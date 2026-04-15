"""
Upstage PDF -> Markdown -> Digest 파이프라인

새로운 카드 PDF를 Upstage API로 마크다운 추출 후 Digest 요약본을 생성합니다.

사용법:
  python -m scripts.upstage_pipeline --date April14
  python -m scripts.upstage_pipeline --date April14 --step digest
  python -m scripts.upstage_pipeline --date April14 --filename "신한카드 Mr.Life"
  python -m scripts.upstage_pipeline --date April14 --filename samsung_hanwha_eagles samsung_id_energy samsung_id_global
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

PDF_BASE = ROOT / "datasets" / "new_pdfs"
MD_BASE = ROOT / "datasets" / "upstage_md"
DIGEST_BASE = ROOT / "datasets" / "digest"


def extract_with_upstage(file_path: str) -> str:
    from langchain_upstage import UpstageDocumentParseLoader
    import re

    loader = UpstageDocumentParseLoader(
        file_path,
        output_format="markdown",
        split="element",
    )
    docs = loader.load()
    if not docs:
        return ""

    md_text = "\n\n".join(doc.page_content for doc in docs)

    md_text = re.sub(r"([^\n])(#+ )", r"\1\n\n\2", md_text)
    md_text = re.sub(r"([^\n])([*-] )", r"\1\n\n\2", md_text)
    md_text = re.sub(r"([^\n])([*·] )", r"\1\n\n\2", md_text)
    md_text = re.sub(r"\n{3,}", "\n\n", md_text)
    return md_text.strip()


def main():
    parser = argparse.ArgumentParser(description="Upstage PDF -> Markdown -> Digest 파이프라인")
    parser.add_argument("--date", type=str, required=True, help="처리할 날짜 폴더명 (예: April14)")
    parser.add_argument(
        "--step",
        type=str,
        choices=["markdown", "digest"],
        default="markdown",
        help="시작 단계 (기본: markdown). 'digest'로 지정하면 PDF->MD를 건너뜁니다.",
    )
    parser.add_argument("--filename", type=str, nargs="+", help="처리할 파일명 키워드 (확장자 제외, 여러 개 공백으로 구분)")
    args = parser.parse_args()

    if not os.getenv("UPSTAGE_API_KEY"):
        print("[ERROR] UPSTAGE_API_KEY 환경변수가 설정되지 않았습니다. .env 파일을 확인하세요.")
        sys.exit(1)

    pdf_dir = PDF_BASE / args.date
    md_dir = MD_BASE / args.date
    digest_dir = DIGEST_BASE / args.date

    step_idx = {"markdown": 1, "digest": 2}[args.step]

    # =========================================================================
    # Step 1: PDF -> Markdown (Upstage)
    # =========================================================================
    step1_success = 0
    step1_failures = []

    if step_idx <= 1:
        print(f"=== [Step 1] PDF -> Markdown (Upstage) ===")

        if not pdf_dir.exists():
            print(f"[ERROR] PDF 폴더가 존재하지 않습니다: {pdf_dir}")
            sys.exit(1)

        pdf_files = sorted(pdf_dir.glob("*.pdf"))
        if args.filename:
            pdf_files = [f for f in pdf_files if any(kw.lower() in f.stem.lower() for kw in args.filename)]

        if not pdf_files:
            print("[INFO] 처리할 PDF 파일이 없습니다.")
            sys.exit(0)

        md_dir.mkdir(parents=True, exist_ok=True)
        print(f"총 {len(pdf_files)}개의 PDF 파일을 처리합니다.\n")

        for pdf_path in tqdm(pdf_files, desc="1. PDF -> Markdown"):
            try:
                md_text = extract_with_upstage(str(pdf_path))
                if not md_text:
                    step1_failures.append((pdf_path.name, "Upstage가 빈 결과를 반환했습니다."))
                    continue

                out_path = md_dir / f"{pdf_path.stem}.md"
                out_path.write_text(md_text, encoding="utf-8")
                step1_success += 1

            except Exception as e:
                step1_failures.append((pdf_path.name, str(e)))

        print(f"\nStep 1 완료 — 성공: {step1_success}, 실패: {len(step1_failures)}")
        for fname, err in step1_failures:
            print(f"  [실패] {fname}: {err}")

        if step1_success == 0:
            print("[INFO] 성공적으로 추출된 마크다운이 없어 프로세스를 종료합니다.")
            sys.exit(0)
    else:
        print("=== [Step 1] 건너뜀 ===")

    # =========================================================================
    # Step 2: Markdown -> Digest
    # =========================================================================
    from scripts.generate_digest import generate_digest_from_markdown

    step2_success = 0
    step2_failures = []

    print(f"\n=== [Step 2] Markdown -> Digest ===")

    if not md_dir.exists():
        print(f"[ERROR] 마크다운 폴더가 존재하지 않습니다: {md_dir}")
        sys.exit(1)

    md_files = sorted(md_dir.glob("*.md"))
    if args.filename:
        md_files = [f for f in md_files if any(kw.lower() in f.stem.lower() for kw in args.filename)]

    if not md_files:
        print("[INFO] 처리할 마크다운 파일이 없습니다.")
        sys.exit(0)

    digest_dir.mkdir(parents=True, exist_ok=True)
    print(f"총 {len(md_files)}개의 마크다운 파일을 처리합니다.\n")

    for md_path in tqdm(md_files, desc="2. Markdown -> Digest"):
        try:
            digest_text = generate_digest_from_markdown(md_path)
            if not digest_text:
                step2_failures.append((md_path.name, "Digest 생성 실패"))
                continue

            out_path = digest_dir / f"{md_path.stem}.md"
            out_path.write_text(digest_text, encoding="utf-8")
            step2_success += 1

        except Exception as e:
            step2_failures.append((md_path.name, str(e)))

    print(f"\nStep 2 완료 — 성공: {step2_success}, 실패: {len(step2_failures)}")
    for fname, err in step2_failures:
        print(f"  [실패] {fname}: {err}")

    print("\n=== [완료] 파이프라인 요약 ===")
    print(f"1. PDF -> Markdown : 성공 {step1_success}건 | 실패 {len(step1_failures)}건")
    print(f"2. Markdown -> Digest: 성공 {step2_success}건 | 실패 {len(step2_failures)}건")
    print(f"\n출력 위치:")
    print(f"  Markdown : {md_dir}")
    print(f"  Digest   : {digest_dir}")


if __name__ == "__main__":
    main()
