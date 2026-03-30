import re
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("❌ BeautifulSoup 모듈이 설치되어 있지 않습니다.")
    print("터미널에서 'pip install beautifulsoup4'를 실행한 후 다시 시도해주세요.")
    exit(1)


def fix_broken_table_separators(markdown_text):
    """(이전 스크립트 로직) 깨진 구분선(| -- \n - |)을 한 줄로 병합합니다."""
    pattern = re.compile(r'\|(?:[\s]*\-+[\s\-]*\|)+')
    def replace_newlines(match):
        matched_str = match.group(0)
        if '\n' in matched_str or '\r' in matched_str:
            return matched_str.replace('\n', '').replace('\r', '')
        return matched_str
    return pattern.sub(replace_newlines, markdown_text)


def process_nested_table(table_lines):
    """
    잘못 변환된 중첩 테이블을 해체하여 정상적인 마크다운 표로 변환합니다.
    """
    data_rows = []
    
    # 1. 마크다운 표에서 헤더 구분선(|---|)을 제외하고 실제 데이터 행만 추출
    for line in table_lines:
        line_stripped = line.strip()
        if line_stripped.startswith('|'): line_stripped = line_stripped[1:]
        if line_stripped.endswith('|'): line_stripped = line_stripped[:-1]
        
        cells = [c.strip() for c in line_stripped.split('|')]
        
        # 구분선인지 확인 (셀 내용이 모두 하이픈, 콜론, 공백으로만 이루어져 있는지)
        is_separator = all(re.match(r'^[-:\s]+$', c) for c in cells if c)
        if not is_separator:
            data_rows.append(cells)
            
    if not data_rows:
        return '\n'.join(table_lines)
        
    # 2. 첫 번째 행에서 <table> 태그가 포함된 열(Column)의 인덱스 찾기
    html_col_idx = -1
    for idx, cell in enumerate(data_rows[0]):
        if '<table' in cell.lower():
            html_col_idx = idx
            break
            
    if html_col_idx == -1:
        return '\n'.join(table_lines) # 중첩 표가 없으면 원본 반환
        
    # 3. BeautifulSoup으로 HTML 태그 파싱하여 내부 데이터(inner_data) 추출
    html_content = data_rows[0][html_col_idx]
    soup = BeautifulSoup(html_content, 'html.parser')
    trs = soup.find_all('tr')
    
    inner_data = []
    for tr in trs:
        tds = tr.find_all(['td', 'th'])
        inner_data.append([td.get_text(strip=True) for td in tds])
        
    # 4. 바깥 마크다운 표에서 HTML 태그가 있던 열을 제외한 나머지 데이터(outer_data) 추출
    outer_data = []
    for row in data_rows:
        outer_row = [row[i] for i in range(len(row)) if i != html_col_idx]
        outer_data.append(outer_row)
        
    # 안전장치: 내부 표의 행 개수와 외부 표의 행 개수가 다르면 병합 불가 (원본 반환)
    if len(inner_data) != len(outer_data):
        return '\n'.join(table_lines)
        
    # 5. 분리된 두 데이터를 행(Row) 단위로 병합
    merged_data = []
    for i in range(len(inner_data)):
        merged_row = inner_data[i] + outer_data[i]
        merged_data.append(merged_row)
        
    # 6. 병합된 2D 배열을 정상적인 마크다운 표 텍스트로 생성
    col_count = len(merged_data[0])
    header = "| " + " | ".join(merged_data[0]) + " |"
    separator = "|" + "|".join(["---"] * col_count) + "|"
    
    result_lines = [header, separator]
    for row in merged_data[1:]:
        # 열 개수가 부족하면 빈칸으로 채움
        row_padded = row + [''] * (col_count - len(row))
        result_lines.append("| " + " | ".join(row_padded) + " |")
        
    return '\n'.join(result_lines)


def fix_markdown_text(text):
    """전체 마크다운 텍스트를 파싱하여 복구 로직들을 순차적으로 적용합니다."""
    # 1단계: 먼저 이전의 깨진 구분선 오류부터 수정
    text = fix_broken_table_separators(text)
    
    # 2단계: 표 단위로 블록을 나누어 중첩 HTML 표 해체
    lines = text.split('\n')
    new_lines = []
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # 마크다운 표의 시작인지 확인
        if line.startswith('|') and line.endswith('|'):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith('|') and lines[i].strip().endswith('|'):
                table_lines.append(lines[i])
                i += 1
            
            # 테이블 블록 안에 <table 이라는 문자열이 있는지 확인 후 복구
            if any('<table' in l.lower() for l in table_lines):
                try:
                    fixed_table = process_nested_table(table_lines)
                    new_lines.extend(fixed_table.split('\n'))
                except Exception as e:
                    print(f"⚠️ 표 파싱 중 오류 발생 (원본 유지): {e}")
                    new_lines.extend(table_lines)
            else:
                new_lines.extend(table_lines)
            continue
            
        new_lines.append(lines[i])
        i += 1
        
    return '\n'.join(new_lines)


def process_markdown_directory(directory_path):
    target_dir = Path(directory_path)
    if not target_dir.exists() or not target_dir.is_dir():
        print(f"❌ 오류: 유효한 폴더 경로가 아닙니다 - {directory_path}")
        return

    print(f"📂 '{target_dir.resolve()}' 스캔 및 복구 시작...\n")
    total_count = modified_count = 0

    for file_path in target_dir.rglob('*.md'):
        total_count += 1
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                original_text = f.read()

            fixed_text = fix_markdown_text(original_text)

            if original_text != fixed_text:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(fixed_text)
                print(f"  ✅ [복구 완료] {file_path.name}")
                modified_count += 1

        except Exception as e:
            print(f"  ❌ [오류] {file_path.name} - {e}")

    print("-" * 40)
    print(f"🎉 완료: {total_count}개 파일 중 {modified_count}개 복구됨.")


if __name__ == "__main__":
    # 작업할 폴더 경로를 지정하세요. 현재 폴더는 "./" 입니다.
    TARGET_FOLDER_PATH = r"./"
    process_markdown_directory(TARGET_FOLDER_PATH)