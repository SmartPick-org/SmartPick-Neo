import json
from pathlib import Path

def migrate_content(v3_path, v4_path):
    print(f"MIGRATING: {v4_path.name}")
    with open(v3_path, "r", encoding="utf-8") as f:
        v3_data = json.load(f)
    with open(v4_path, "r", encoding="utf-8") as f:
        v4_data = json.load(f)

    # V3 혜택 맵 구축 (ID -> content, (cat, sub) -> content)
    id_map = {}
    cat_sub_map = {}
    
    for b in v3_data.get("benefits", []):
        id_map[b["benefit_id"].lower()] = b.get("content", "")
        key = (b.get("category"), b.get("sub_category"))
        if key not in cat_sub_map:
            cat_sub_map[key] = b.get("content", "")

    # V4에 주입
    count = 0
    for b in v4_data.get("benefits", []):
        v4_id = b["benefit_id"].lower()
        key = (b.get("category"), b.get("sub_category"))
        
        content = ""
        if v4_id in id_map:
            content = id_map[v4_id]
        elif key in cat_sub_map:
            content = cat_sub_map[key]
        
        if content:
            # benefit_id 바로 아래(또는 형제)로 content 주입
            # dict는 순서를 유지하므로 재배열
            new_benefit = {"benefit_id": b["benefit_id"], "content": content}
            for k, v in b.items():
                if k != "benefit_id":
                    new_benefit[k] = v
            
            b.clear()
            b.update(new_benefit)
            count += 1
            
    print(f"  -> Injected {count} descriptions.")
    return v4_data

# 작업 경로
ROOT = Path("c:/Users/vs501/Documents/workspace/SmartPick-Neo")
samples = [
    {
        "company": "kb",
        "v3": ROOT / "datasets/json_v3/kb/manuals/kb_goodday_olym.json",
        "v4": ROOT / "datasets/json_v4/kb/kb_goodday_olym.json"
    },
    {
        "company": "shinhan",
        "v3": ROOT / "datasets/json_v3/shinhan/new/shinhan_mr_life.json",
        "v4": ROOT / "datasets/json_v4/shinhan/shinhan_mr_life.json"
    },
    {
        "company": "hyundai",
        "v3": ROOT / "datasets/json_v3/hyundai/manual/hyundai_the_pink_ed2.json",
        "v4": ROOT / "datasets/json_v4/hyundai/hyundai_the_pink_ed2.json"
    }
]

output_dir = ROOT / "calc_refactor/content_migration_test"
output_dir.mkdir(parents=True, exist_ok=True)

for s in samples:
    modified_v4 = migrate_content(s["v3"], s["v4"])
    out_path = output_dir / s["v4"].name
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(modified_v4, f, ensure_ascii=False, indent=2)

print("\nMigration completed. Check outcomes in calc_refactor/content_migration_test/")
