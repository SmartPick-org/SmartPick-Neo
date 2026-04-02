"""
PDF -> Markdown -> JSON v3 -> Digest 통합 파이프라인

사용법:
  python -m scripts.pipeline
  python -m scripts.pipeline --company shinhan
  python -m scripts.pipeline --company shinhan --filename "신한카드 Mr.Life.pdf"
  python -m scripts.pipeline --out-dir ./custom_results
"""

import os
import argparse
import sys
import json
import re
from pathlib import Path

from scripts.pdf_markdown_extractor import PDFMarkdownExtractor
import scripts.generate_json_v3 as gen_j3
import scripts.generate_digest as gen_digest

ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = ROOT / "datasets" / "pdfs"

def main():
    parser = argparse.ArgumentParser(description="PDF -> Markdown -> JSON v3 -> Digest 통합 파이프라인")
    parser.add_argument("--out-dir", type=str, help="결과물 저장 폴더 (기본: datasets)")
    parser.add_argument("--company", type=str, help="특정 카드사만 처리 (예: kb, shinhan, hyundai)")
    parser.add_argument("--filename", type=str, help="특정 PDF 파일만 처리 (예: '신한카드 Mr.Life.pdf')")
    
    args = parser.parse_args()
    
    # 0. 결과물 저장할 폴더 설정
    if args.out_dir:
        out_base = Path(args.out_dir).resolve()
    else:
        out_base = ROOT / "datasets"
        
    md_dir = out_base / "markdown_upstage"
    json_dir = out_base / "json_v3"
    digest_dir = out_base / "digest"
    
    # generate_json_v3, generate_digest 스크립트 내부의 전역 변수 동적 수정
    gen_j3.MD_DIR = md_dir
    gen_j3.DST_DIR = json_dir
    gen_digest.SRC_DIR = json_dir
    gen_digest.DST_DIR = digest_dir
    
    # 1. 대상 PDF 찾기
    target_pdfs = []
    
    if args.company:
        comp_dir = PDF_DIR / args.company
        if not comp_dir.exists():
            print(f"[ERROR] 카드사 폴더가 존재하지 않습니다: {comp_dir}")
            sys.exit(1)
            
        if args.filename:
            pdf_path = comp_dir / args.filename
            if not pdf_path.suffix:
                pdf_path = pdf_path.with_suffix('.pdf')
                
            if not pdf_path.exists():
                print(f"[ERROR] PDF 파일이 존재하지 않습니다: {pdf_path}")
                sys.exit(1)
            target_pdfs.append(pdf_path)
        else:
            target_pdfs.extend(list(comp_dir.glob("*.pdf")))
    else:
        # 모든 카드사 폴더 순회
        if PDF_DIR.exists():
            for comp_dir in sorted(PDF_DIR.iterdir()):
                if comp_dir.is_dir():
                    target_pdfs.extend(list(comp_dir.glob("*.pdf")))
        else:
            print(f"[ERROR] PDF 기본 폴더가 존재하지 않습니다: {PDF_DIR}")
            sys.exit(1)
            
    if not target_pdfs:
        print("[INFO] 처리할 PDF 파일이 없습니다.")
        sys.exit(0)
        
    print(f"총 {len(target_pdfs)}개의 PDF 파일을 처리합니다.\n")
    
    affected_card_keys = set()
    
    # =========================================================================
    # Step 1: PDF -> Markdown 추출
    # =========================================================================
    print("=== [Step 1] PDF -> Markdown 추출 ===")
    for pdf_path in target_pdfs:
        comp_name = pdf_path.parent.name
        print(f"  추출 중: [{comp_name}] {pdf_path.name}")
        
        try:
            result = PDFMarkdownExtractor.extract(str(pdf_path))
            md_text = result.get("markdown", "")
            
            if not md_text:
                print(f"    [WARN] 추출된 마크다운이 비어있습니다. 에러: {result.get('parse_error', '없음')}")
                continue
                
            out_md_dir = md_dir / comp_name
            out_md_dir.mkdir(parents=True, exist_ok=True)
            out_md_path = out_md_dir / f"{pdf_path.stem}.md"
            
            out_md_path.write_text(md_text, encoding="utf-8")
            
            try:
                rel_path = out_md_path.relative_to(ROOT)
                print(f"    → 저장 완료: {rel_path}")
            except ValueError:
                print(f"    → 저장 완료: {out_md_path}")
            
            # 파일이 저장된 후 그룹핑을 위해 card_key 식별
            card_key = gen_j3.normalize_card_key(comp_name, out_md_path.name)
            affected_card_keys.add(card_key)
            
        except Exception as e:
            print(f"    [ERROR] 추출 실패: {e}")

    if not affected_card_keys:
        print("\n[INFO] 성공적으로 추출된 텍스트가 없어 프로세스를 종료합니다.")
        sys.exit(0)

    # =========================================================================
    # Step 2: Markdown -> JSON v3 생성
    # =========================================================================
    print("\n=== [Step 2] Markdown -> JSON v3 변환 ===")
    
    # 갱신된 파일을 바탕으로 그룹 정보를 가져옴
    md_groups = gen_j3.group_markdown_files()
    
    # 이번 대상 PDF 추출로 인해 영향을 받은 카드 그룹만 필터링
    target_groups = {k: v for k, v in md_groups.items() if k in affected_card_keys}
    
    print(f"총 {len(target_groups)}개 카드 묶음을 JSON으로 변환합니다.")
    generated_jsons = []
    
    for card_key, group in sorted(target_groups.items()):
        comp_name = group["company"]
        files_count = len(group["files"])
        print(f"  변환 중: [{card_key}] ({files_count}개 마크다운 병합)")
        
        result_json = gen_j3.convert_card(card_key, group)
        if result_json:
            out_json_dir = json_dir / comp_name
            out_json_dir.mkdir(parents=True, exist_ok=True)
            
            card_id = result_json.get("card_meta", {}).get("card_id", card_key)
            safe_name = re.sub(r"[^\w\-]", "_", card_id)
            out_json_path = out_json_dir / f"{safe_name}.json"
            
            out_json_path.write_text(
                json.dumps(result_json, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            
            try:
                rel_path = out_json_path.relative_to(ROOT)
                print(f"    → 저장 완료: {rel_path}")
            except ValueError:
                print(f"    → 저장 완료: {out_json_path}")
                
            generated_jsons.append(out_json_path)
        else:
            print(f"    [ERROR] JSON 생성에 실패했습니다: {card_key}")

    if not generated_jsons:
        print("\n[INFO] 생성된 JSON 파일이 없어 프로세스를 종료합니다.")
        sys.exit(0)

    # =========================================================================
    # Step 3: JSON v3 -> Digest.md 생성
    # =========================================================================
    print("\n=== [Step 3] JSON v3 -> Digest 마크다운 생성 ===")
    print(f"총 {len(generated_jsons)}개의 JSON 데이터를 요약합니다.")
    
    for json_path in generated_jsons:
        comp_name = json_path.parent.name
        print(f"  요약 중: [{comp_name}] {json_path.name}")
        
        digest_text = gen_digest.generate_digest(json_path, use_sub_category=True)
        if digest_text:
            out_digest_dir = digest_dir / comp_name
            out_digest_dir.mkdir(parents=True, exist_ok=True)
            out_digest_path = out_digest_dir / f"{json_path.stem}.md"
            
            out_digest_path.write_text(digest_text, encoding="utf-8")
            
            try:
                rel_path = out_digest_path.relative_to(ROOT)
                print(f"    → 저장 완료: {rel_path}")
            except ValueError:
                print(f"    → 저장 완료: {out_digest_path}")
        else:
            print(f"    [ERROR] 다이제스트 생성에 실패했습니다: {json_path.name}")
            
    print("\n=== [완료] 모든 데이터 처리 파이프라인이 종료되었습니다. ===")

if __name__ == "__main__":
    main()
