"""
PDF -> Markdown -> JSON v3 -> Digest 통합 파이프라인

사용법:
  python -m scripts.pipeline
  python -m scripts.pipeline --company shinhan
  python -m scripts.pipeline --company shinhan --filename "신한카드 Mr.Life.pdf"
  python -m scripts.pipeline --out-dir ./custom_results
  python -m scripts.pipeline --step json    # 기존 Markdown을 사용해 JSON 변환부터 수행
  python -m scripts.pipeline --step digest  # 기존 JSON을 사용해 Digest 변환만 수행
"""

import os
import argparse
import sys
import json
import re
from pathlib import Path
from tqdm import tqdm

from scripts.pdf_markdown_extractor import PDFMarkdownExtractor
import scripts.generate_json_v3 as gen_j3
import scripts.generate_digest as gen_digest
from app.utils.md_table_refine import fix_markdown_text

ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = ROOT / "datasets" / "pdfs"

def main():
    parser = argparse.ArgumentParser(description="PDF -> Markdown -> JSON v3 -> Digest 통합 파이프라인")
    parser.add_argument("--out-dir", type=str, help="결과물 저장 폴더 (기본: datasets)")
    parser.add_argument("--company", type=str, help="특정 카드사만 처리 (예: kb, shinhan, hyundai)")
    parser.add_argument("--filename", type=str, help="특정 파일명 키워드 (예: '신한카드 Mr.Life', PDF/MD 공통)")
    parser.add_argument("--step", type=str, choices=["markdown", "json", "digest"], default="markdown", 
                        help="시작할 단계를 지정합니다. (기본값: markdown)")
    
    args = parser.parse_args()
    
    # 0. 결과물 저장할 폴더 설정
    if args.out_dir:
        out_base = Path(args.out_dir).resolve()
    else:
        out_base = ROOT / "datasets"
        
    md_dir = out_base / "terms"
    json_dir = out_base / "json"
    digest_dir = out_base / "digest"
    
    # generate_json_v3, generate_digest 스크립트 내부의 전역 변수 동적 수정
    gen_j3.MD_DIR = md_dir
    gen_j3.DST_DIR = json_dir
    gen_digest.SRC_DIR = json_dir
    gen_digest.DST_DIR = digest_dir
    
    step_idx = {"markdown": 1, "json": 2, "digest": 3}[args.step]
    
    # 1. 대상 PDF 찾기
    target_pdfs = []
    affected_card_keys = set()
    step1_success = 0
    step1_failures = []
    
    if step_idx <= 1:
        if args.company:
            comp_dir = PDF_DIR / args.company
            if not comp_dir.exists():
                print(f"[ERROR] 카드사 폴더가 존재하지 않습니다: {comp_dir}")
                sys.exit(1)
                
            if args.filename:
                filename_to_search = args.filename if args.filename.lower().endswith('.pdf') else f"{args.filename}.pdf"
                found_files = list(comp_dir.rglob(filename_to_search))
                if not found_files:
                    print(f"[ERROR] PDF 파일이 존재하지 않습니다: {comp_dir} 하위의 '{filename_to_search}'")
                    sys.exit(1)
                target_pdfs.extend(found_files)
            else:
                target_pdfs.extend(list(comp_dir.rglob("*.pdf")))
        else:
            # 모든 카드사 폴더 순회
            if PDF_DIR.exists():
                for comp_dir in sorted(PDF_DIR.iterdir()):
                    if comp_dir.is_dir():
                        target_pdfs.extend(list(comp_dir.rglob("*.pdf")))
            else:
                print(f"[ERROR] PDF 기본 폴더가 존재하지 않습니다: {PDF_DIR}")
                sys.exit(1)
                
        if not target_pdfs:
            print("[INFO] 처리할 PDF 파일이 없습니다.")
            sys.exit(0)
            
        print(f"총 {len(target_pdfs)}개의 PDF 파일을 처리합니다.\n")
        
        # =========================================================================
        # Step 1: PDF -> Markdown 추출
        # =========================================================================
        print(f"=== [Step 1] PDF -> Markdown 추출 (시작 단계: {args.step}) ===")
        
        for pdf_path in tqdm(target_pdfs, desc="1. PDF -> Markdown"):
            try:
                rel_dir = pdf_path.parent.relative_to(PDF_DIR)
            except ValueError:
                rel_dir = Path(pdf_path.parent.name)
                
            comp_name = str(rel_dir.parts[0]) if rel_dir.parts else pdf_path.parent.name
            
            try:
                result = PDFMarkdownExtractor.extract(str(pdf_path))
                md_text = result.get("markdown", "")
                
                if not md_text:
                    err_msg = result.get('parse_error', '추출된 마크다운이 비어있음')
                    step1_failures.append((pdf_path.name, err_msg))
                    continue
                    
                # 마크다운 표 깨짐 복구 및 중첩 표 해체 반영
                try:
                    md_text = fix_markdown_text(md_text)
                except Exception as e:
                    tqdm.write(f"    [WARN] 마크다운 표 복구 중 오류 발생 ({pdf_path.name}): {e}")
                    
                out_md_dir = md_dir / rel_dir
                out_md_dir.mkdir(parents=True, exist_ok=True)
                out_md_path = out_md_dir / f"{pdf_path.stem}.md"
                
                out_md_path.write_text(md_text, encoding="utf-8")
                
                # 파일이 저장된 후 그룹핑을 위해 card_key 식별
                card_key = gen_j3.normalize_card_key(comp_name, out_md_path.name)
                affected_card_keys.add(card_key)
                step1_success += 1
                
            except Exception as e:
                step1_failures.append((pdf_path.name, str(e)))

        if not affected_card_keys:
            print(f"\n[INFO] 성공적으로 추출된 텍스트가 없어 프로세스를 종료합니다. (실패: {len(step1_failures)}건)")
            for fail_file, fail_err in step1_failures:
                print(f"  - {fail_file}: {fail_err}")
            sys.exit(0)
    else:
        print(f"=== [Step 1] 건너뜀 (시작 단계: {args.step}) ===")

    # =========================================================================
    # Step 2: Markdown -> JSON v3 생성
    # =========================================================================
    generated_jsons = []
    target_groups = {}
    step2_success = 0
    step2_failures = []
    
    if step_idx <= 2:
        print(f"\n=== [Step 2] Markdown -> JSON v3 변환 (시작 단계: {args.step}) ===")
        md_groups = gen_j3.group_markdown_files()
        
        if step_idx == 1:
            # Step 1을 수행했으면, 그 결과(affected_card_keys)만 사용
            target_groups = {k: v for k, v in md_groups.items() if k in affected_card_keys}
        else:
            # Step 1을 건너뛰고 시작했으면, 모든 그룹을 가져와서 args (company, filename 등)에 맞춰 필터링
            for card_key, group in md_groups.items():
                if args.company and group["company"] != args.company:
                    continue
                if args.filename:
                    # 마크다운 파일들의 이름 중 target_stem 이 포함되는지
                    target_stem = Path(args.filename).stem
                    if not any(target_stem.lower() in f.stem.lower() for f in group["files"]):
                        continue
                target_groups[card_key] = group
                affected_card_keys.add(card_key)

        if not target_groups:
            print("[INFO] 처리할 마크다운 대상이 존재하지 않습니다.")
            if step_idx == 2:
                sys.exit(0)
        
        print(f"총 {len(target_groups)}개 카드 묶음을 JSON으로 변환합니다.")
        
        for card_key, group in tqdm(sorted(target_groups.items()), desc="2. Markdown -> JSON"):
            comp_name = group["company"]
            files_count = len(group["files"])
            
            # 첫 번째 마크다운 파일의 디렉토리를 기준으로 계층 맞춤
            first_md_file = group["files"][0]
            try:
                rel_dir = first_md_file.parent.relative_to(md_dir)
            except ValueError:
                rel_dir = Path(comp_name)
            
            try:
                result_json = gen_j3.convert_card(card_key, group)
                if result_json:
                    out_json_dir = json_dir / rel_dir
                    out_json_dir.mkdir(parents=True, exist_ok=True)
                    
                    card_id = result_json.get("card_meta", {}).get("card_id", card_key)
                    safe_name = re.sub(r"[^\w\-]", "_", card_id)
                    out_json_path = out_json_dir / f"{safe_name}.json"
                    
                    out_json_path.write_text(
                        json.dumps(result_json, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    
                    generated_jsons.append(out_json_path)
                    step2_success += 1
                else:
                    step2_failures.append((card_key, "결과 JSON 반환 안됨"))
            except Exception as e:
                step2_failures.append((card_key, str(e)))

        if not generated_jsons:
            print(f"\n[INFO] 생성된 JSON 파일이 없어 프로세스를 종료합니다. (실패: {len(step2_failures)}건)")
            for fail_file, fail_err in step2_failures:
                print(f"  - {fail_file}: {fail_err}")
            sys.exit(0)
    else:
        print(f"\n=== [Step 2] 건너뜀 (시작 단계: {args.step}) ===")

    # =========================================================================
    # Step 3: JSON v3 -> Digest.md 생성
    # =========================================================================
    step3_success = 0
    step3_failures = []
    
    if step_idx <= 3:
        print(f"\n=== [Step 3] JSON v3 -> Digest 마크다운 생성 (시작 단계: {args.step}) ===")
        
        if step_idx == 3:
            # Digest부터 시작한 경우 JSON 디렉토리에서 검색
            search_dir = json_dir / args.company if args.company else json_dir
            if search_dir.exists():
                target_stem = Path(args.filename).stem if args.filename else None
                for j_file in search_dir.rglob("*.json"):
                    if target_stem and target_stem.lower() not in j_file.stem.lower():
                        continue
                    generated_jsons.append(j_file)
            
            if not generated_jsons:
                print("[INFO] 처리할 JSON 대상이 존재하지 않습니다.")
                sys.exit(0)

        print(f"총 {len(generated_jsons)}개의 JSON 데이터를 요약합니다.")
        
        for json_path in tqdm(generated_jsons, desc="3. JSON -> Digest"):
            try:
                rel_dir = json_path.parent.relative_to(json_dir)
            except ValueError:
                rel_dir = Path(json_path.parent.name)
            
            try:
                digest_text = gen_digest.generate_digest(json_path, use_sub_category=True)
                if digest_text:
                    out_digest_dir = digest_dir / rel_dir
                    out_digest_dir.mkdir(parents=True, exist_ok=True)
                    out_digest_path = out_digest_dir / f"{json_path.stem}.md"
                    
                    out_digest_path.write_text(digest_text, encoding="utf-8")
                    step3_success += 1
                else:
                    step3_failures.append((json_path.name, "다이제스트 텍스트 생성 실패"))
            except Exception as e:
                step3_failures.append((json_path.name, str(e)))
                
    print("\n=== [완료] 데이터 처리 파이프라인 요약 ===")
    
    print(f"1. PDF -> Markdown : 시도 {len(target_pdfs)}건 | 성공 {step1_success}건 | 실패 {len(step1_failures)}건")
    if step1_failures:
        for fname, err in step1_failures:
            print(f"   - [실패] {fname} : {err}")
            
    print(f"2. Markdown -> JSON: 시도 {len(target_groups)}건 | 성공 {step2_success}건 | 실패 {len(step2_failures)}건")
    if step2_failures:
        for ckey, err in step2_failures:
            print(f"   - [실패] {ckey} : {err}")
            
    print(f"3. JSON -> Digest  : 시도 {len(generated_jsons)}건 | 성공 {step3_success}건 | 실패 {len(step3_failures)}건")
    if step3_failures:
        for jname, err in step3_failures:
            print(f"   - [실패] {jname} : {err}")
            
    print("\n모든 작업이 종료되었습니다.")

if __name__ == "__main__":
    main()
