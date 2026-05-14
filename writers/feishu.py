#!/usr/bin/env python3
"""
writers/feishu.py — 飞书固定表写入器

⚠️ 此 writer 使用的是作者私人飞书表结构（tbl5jjR1lZlUWbrd 等）
如果你有自己的飞书表，请修改下面这些字段映射：
  RAW_TABLES → 你的 raw 表 ID
  CASE_TABLE → 你的案件主表 ID
  CASE_FIELD_xxx → 你的字段名

或者直接用 writers/feishu_build.py 让 agent 帮你建表。

用法:
  python3 write_to_bitable.py --input output/zxgk_batch_20260511.json --subsite zhixing
  python3 write_to_bitable.py --input output/zxgk_batch_20260511.json --subsite shixin --cross-ref
  python3 write_to_bitable.py --input output/zxgk_batch_20260511.json --subsite xgl --cross-ref
  python3 write_to_bitable.py --input output/zxgk_batch_20260511.json --subsite zhixing --screenshots output/screenshots

--cross-ref: 写入 raw 表后，按案号在案件主表中匹配，更新 是否失信/是否限高 + 日期
--screenshots: 上传截图到案件主表的 截图 字段，按 viewId 精确匹配
"""

import argparse, json, os, re, subprocess, sys, time
from pathlib import Path

APP_TOKEN = os.environ.get("FEISHU_APP_TOKEN", "")


def _check_token():
    if not APP_TOKEN:
        print("错误: 环境变量 FEISHU_APP_TOKEN 未设置", file=sys.stderr)
        sys.exit(1)

# raw 表映射
RAW_TABLES = {
    "zhixing": "tblem4qjdjQ5RYWB",   # raw_被执行人
    "shixin":  "tblkruwSGaPeFDJU",   # raw_失信被执行人
    "xgl":     "tblREMTC0Z0JWlZH",   # raw_限制消费人员
}

# 案件主表
CASE_TABLE = "tbl5jjR1lZlUWbrd"

# 案件主表字段
CASE_FIELD_SCREENSHOT = "截图"        # 截图 (type=17 attachment)
CASE_FIELD_CASE_NO = "案号提取"        # 案号提取 (Text, cross-ref 搜索用，不用 Lookup 的"案号")
CASE_FIELD_STATUS_SHIXIN = "是否失信"
CASE_FIELD_STATUS_XGL = "是否限高"
CASE_FIELD_SHIXIN_DATE = "失信日期"
CASE_FIELD_XGL_DATE = "限高日期"

# ============================================================================
# 通用 API 调用
# ============================================================================

def lark_api(method, path, data=None):
    """通用 lark-cli API 调用（JSON body）"""
    cmd = ["lark-cli", "api", method, path, "--as", "user"]
    if data:
        cmd += ["--data", json.dumps(data, ensure_ascii=False)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        print(f"  lark-cli error: {r.stderr[:300]}", file=sys.stderr)
        return None
    return json.loads(r.stdout)


def lark_upload_media(file_path, parent_type="bitable_image", app_token=None):
    """上传文件到飞书 bitable 媒体存储，返回 file_token。

    lark-cli 的 --file /path 在本机有 bug（cannot open file），
    因此通过 stdin 管道 + --file - 绕开。

    parent_type: bitable_image（图片）或 bitable_file（文件）
    """
    if app_token is None:
        app_token = APP_TOKEN

    file_size = os.path.getsize(file_path)
    file_name = os.path.basename(file_path)

    metadata = {
        "file_name": file_name,
        "parent_type": parent_type,
        "parent_node": app_token,
        "size": file_size,
    }

    upload_url = "/open-apis/drive/v1/medias/upload_all"

    with open(file_path, "rb") as fh:
        proc = subprocess.Popen(
            ["lark-cli", "api", "POST", upload_url, "--as", "user",
             "--data", json.dumps(metadata, ensure_ascii=False),
             "--file", "-"],
            stdin=fh,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    try:
        stdout, stderr = proc.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        print(f"  upload timeout: {file_name}", file=sys.stderr)
        return None

    if proc.returncode != 0:
        print(f"  upload error: {stderr.decode()[:300]}", file=sys.stderr)
        return None

    resp = json.loads(stdout)
    if resp.get("code") != 0:
        print(f"  upload API error: {resp.get('msg', '?')}", file=sys.stderr)
        return None

    return resp["data"]["file_token"]


def lark_update_record(table_id, record_id, fields):
    """用 PUT 更新飞书多维表格记录（支持 attachment 字段）"""
    path = f"/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/{record_id}"
    resp = lark_api("PUT", path, {"fields": fields})
    return resp and resp.get("code") == 0


# ============================================================================
# 数据加载
# ============================================================================

def load_records(input_path):
    with open(input_path) as f:
        data = json.load(f)

    all_records = []
    for company in data.get("companies", []):
        for rec in company.get("records", []):
            all_records.append({
                "company": company["company"],
                "caseNo": rec.get("caseNo", ""),
                "name": rec.get("name", ""),
                "date": rec.get("date", ""),
                "timestamp": rec.get("timestamp", 0),
                "viewId": rec.get("viewId", ""),
            })
    return all_records


# ============================================================================
# Raw 表写入
# ============================================================================

def write_raw_table(records, subsite):
    """批量写入 raw 表（自动跳过已存在的重复记录）"""
    table_id = RAW_TABLES[subsite]
    print(f"写入 raw 表 ({subsite}): {len(records)} 条")

    # 去重：查询已存在的 (案号, viewId)
    case_nos = list(set(r["caseNo"] for r in records if r.get("caseNo")))
    if case_nos:
        existing = get_existing_keys(table_id, case_nos)
        new_records = [r for r in records
                       if (r["caseNo"], r["viewId"]) not in existing]
        skipped = len(records) - len(new_records)
        if skipped > 0:
            print(f"  跳过 {skipped} 条重复（表中已存在）")
        records = new_records

    if not records:
        print(f"  无新记录，写入完成")
        return 0

    batch = []
    for r in records:
        fields = {
            "案号": r["caseNo"],
            "被执行人": r["name"],
            "查看": f'viewId={r["viewId"]}',
        }
        if r["timestamp"] and r["timestamp"] > 0:
            fields["立案日期"] = r["timestamp"]
        batch.append({"fields": fields})

    # 每批最多 500 条
    total = 0
    chunk_size = 500
    for i in range(0, len(batch), chunk_size):
        chunk = batch[i : i + chunk_size]
        path = f"/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/batch_create"
        resp = lark_api("POST", path, {"records": chunk})
        if resp and resp.get("code") == 0:
            n = len(resp.get("data", {}).get("records", []))
            total += n
            print(f"  batch {i // chunk_size + 1}: {n}/{len(chunk)} 条 ✅")
        else:
            print(f"  batch {i // chunk_size + 1}: 写入失败", file=sys.stderr)
        time.sleep(0.5)

    print(f"  写入完成: {total}/{len(batch)} 条")
    return total


# ============================================================================
# 交叉匹配
# ============================================================================

def cross_ref_update(subsite):
    """
    交叉匹配：在案件主表中按案号查找，更新 是否失信/是否限高。
    仅支持 shixin 和 xgl 子站。
    """
    if subsite not in ("shixin", "xgl"):
        return

    field_map = {
        "shixin": (CASE_FIELD_STATUS_SHIXIN, CASE_FIELD_SHIXIN_DATE),
        "xgl": (CASE_FIELD_STATUS_XGL, CASE_FIELD_XGL_DATE),
    }
    status_field, date_field = field_map[subsite]

    print(f"交叉匹配: {subsite} → 案件主表.{status_field}")

    # 1. 读取 raw 表中的最新记录（同步日期 = 今天）
    raw_table = RAW_TABLES[subsite]
    path = f"/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{raw_table}/records?page_size=500"
    resp = lark_api("GET", path)
    if not resp or resp.get("code") != 0:
        print("  读取 raw 表失败", file=sys.stderr)
        return

    raw_records = resp.get("data", {}).get("items", [])
    if not raw_records:
        print("  无 raw 记录，跳过交叉匹配")
        return
    print(f"  读取 {len(raw_records)} 条 raw 记录")

    # 2. 逐条在案件主表中按案号查找
    updated = 0
    for rr in raw_records:
        fields = rr.get("fields", {})
        case_no = _extract_text(fields.get("案号"))

        if not case_no:
            continue

        # 在案件主表中查找匹配记录
        filter_payload = {
            "conjunction": "and",
            "conditions": [
                {"field_name": CASE_FIELD_CASE_NO, "operator": "is", "value": [case_no]}
            ],
        }
        search_path = (
            f"/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{CASE_TABLE}/records"
            f"/search"
        )
        search_resp = lark_api("POST", search_path,
                               {"filter": filter_payload, "page_size": 1})
        if not search_resp or search_resp.get("code") != 0:
            continue

        items = search_resp.get("data", {}).get("items", [])
        if not items:
            continue

        case_record_id = items[0]["record_id"]

        # 更新案件主表记录
        update_path = f"/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{CASE_TABLE}/records/{case_record_id}"
        update_data = {"fields": {status_field: "是"}}
        update_resp = lark_api("PUT", update_path, update_data)
        if update_resp and update_resp.get("code") == 0:
            updated += 1
        time.sleep(0.3)

    print(f"  交叉匹配完成: 更新 {updated} 条")


# ============================================================================
# 截图上传
# ============================================================================

def build_screenshot_map(screenshots_dir):
    """扫描截图目录，构建 {viewId: filepath} 映射。

    截图文件名格式: detail_r{n}_{viewId}__{caseNo}.png
    例如: detail_r1_3147017__2026_京0106执7047号.png → viewId=3147017
    """
    ss_dir = Path(screenshots_dir)
    if not ss_dir.is_dir():
        print(f"截图目录不存在: {screenshots_dir}", file=sys.stderr)
        return {}

    ss_map = {}
    for f in ss_dir.glob("detail_r*.png"):
        # detail_r1_3147017__ → 提取 viewId
        m = re.match(r'detail_r\d+_(\d+)', f.name)
        if m:
            vid = m.group(1)
            # 如果同一 viewId 有多张（不同公司同名），取文件较新的
            if vid not in ss_map or f.stat().st_mtime > ss_map[vid].stat().st_mtime:
                ss_map[vid] = f

    print(f"截图目录: {len(ss_map)} 个 viewId 有截图")
    return ss_map


def find_case_record_by_raw(raw_record):
    """从 raw 表记录的「案件主表」DuplexLink 字段提取 case table record_id。

    搜索 API (/records/search) 返回格式:
      "案件主表": {"link_record_ids": ["recvjtxY7UhA8F"]}

    列表 API (/records?page_size=N) 返回格式:
      "案件主表": [{"record_ids": ["recvjtxY7UhA8F"], "table_id": "..."}]
    """
    fields = raw_record.get("fields", {})
    case_link = fields.get("案件主表")
    if not case_link:
        return None

    # 搜索 API 格式: dict with link_record_ids
    if isinstance(case_link, dict):
        for key in ("link_record_ids", "record_ids"):
            ids = case_link.get(key, [])
            if ids:
                return ids[0]
        return None

    # 列表 API 格式: list[dict] with record_ids
    if isinstance(case_link, list):
        for item in case_link:
            if isinstance(item, dict):
                for key in ("record_ids", "link_record_ids"):
                    ids = item.get(key, [])
                    if ids:
                        return ids[0]
    return None


def find_raw_record_by_view_id(raw_table_id, view_id):
    """在 raw 表中按「查看」字段（viewId=xxx）查找记录。

    返回 raw record dict 或 None。
    """
    search_val = f"viewId={view_id}"
    filter_payload = {
        "conjunction": "and",
        "conditions": [
            {"field_name": "查看", "operator": "contains", "value": [search_val]}
        ],
    }
    path = f"/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{raw_table_id}/records/search"
    resp = lark_api("POST", path, {
        "filter": filter_payload,
        "page_size": 1,
        "field_names": ["查看", "是否新增", "案件主表"],
    })
    if not resp or resp.get("code") != 0:
        return None

    items = resp.get("data", {}).get("items", [])
    if not items:
        return None
    return items[0]


def upload_screenshots_for_records(records, screenshots_dir, subsite):
    """为批量查询记录上传截图到案件主表。

    流程:
      1. 扫描截图目录构建 viewId → filepath 映射
      2. 对每条 record，用 viewId 在 raw 表中查找对应记录
      3. 通过 raw 记录的 DuplexLink 找到案件主表 record_id
      4. 上传截图文件到 bitable 媒体存储
      5. PUT 更新案件主表记录的「截图」字段

    records: load_records() 返回的 list[dict]
    screenshots_dir: 截图目录路径
    subsite: 子站名（决定用哪个 raw 表）
    """
    raw_table_id = RAW_TABLES.get(subsite)
    if not raw_table_id:
        print(f"未知子站: {subsite}", file=sys.stderr)
        return

    # Step 1: 构建截图映射
    ss_map = build_screenshot_map(screenshots_dir)
    if not ss_map:
        print("没有找到截图文件，跳过上传")
        return

    # Step 2: 过滤有截图的记录，去重 viewId
    seen_vids = set()
    pending = []
    for r in records:
        vid = r.get("viewId", "")
        if vid in seen_vids:
            continue
        if vid in ss_map:
            seen_vids.add(vid)
            pending.append({"viewId": vid, "caseNo": r.get("caseNo", ""),
                           "company": r.get("company", ""),
                           "screenshot": str(ss_map[vid])})

    print(f"截图上传: {len(pending)} 个 viewId 待处理")

    if not pending:
        return

    success = 0
    fail = 0
    skip_no_link = 0

    for i, item in enumerate(pending):
        vid = item["viewId"]
        ss_path = item["screenshot"]
        case_no = item["caseNo"]

        print(f"  [{i+1}/{len(pending)}] viewId={vid} ({case_no})")

        # Step 3: 在 raw 表中查找
        raw_record = find_raw_record_by_view_id(raw_table_id, vid)
        if not raw_record:
            print(f"    ⚠️  raw 表中找不到 viewId={vid}，跳过")
            skip_no_link += 1
            continue

        # Step 3.5: 只处理标记为「新增」的 raw 记录，跳过已有记录
        # 是否新增格式：{"type": 3, "value": ["新增"]} 或 {"type": 3, "value": ["已有"]}
        raw_fields = raw_record.get("fields", {})
        is_new_raw = raw_fields.get("是否新增")
        is_new = False
        if isinstance(is_new_raw, dict):
            vals = is_new_raw.get("value", [])
            if vals and vals[0] == "新增":
                is_new = True
        elif isinstance(is_new_raw, list):
            if is_new_raw and is_new_raw[0] == "新增":
                is_new = True
        if not is_new:
            print(f"    ⏭️  viewId={vid} 非新增记录，跳过截图上传")
            skip_no_link += 1
            continue

        # Step 4: 通过 DuplexLink 找案件主表 record_id
        case_record_id = find_case_record_by_raw(raw_record)
        if not case_record_id:
            print(f"    ⚠️  raw 记录无「案件主表」链接，跳过")
            skip_no_link += 1
            continue

        # Step 5: 上传截图到 bitable 媒体存储
        file_token = lark_upload_media(ss_path)
        if not file_token:
            print(f"    ❌ 上传失败")
            fail += 1
            continue

        # Step 6: 更新案件主表记录
        if lark_update_record(CASE_TABLE, case_record_id,
                              {CASE_FIELD_SCREENSHOT: [{"file_token": file_token}]}):
            print(f"    ✅ {case_record_id}")
            success += 1
        else:
            print(f"    ❌ 更新记录失败 (record_id={case_record_id})")
            fail += 1

        time.sleep(0.5)  # 限速

    print(f"  截图上传完成: 成功 {success}, 失败 {fail}, "
          f"跳过(无链接) {skip_no_link}")


# ============================================================================
# 工具函数
# ============================================================================

def _extract_text(val):
    """提取飞书 Text 字段的值"""
    if isinstance(val, list) and len(val) > 0:
        item = val[0]
        if isinstance(item, dict) and "text" in item:
            return item["text"]
        return str(item)
    return str(val) if val else ""


def _parse_view_id(view_field):
    """从「查看」字段解析 viewId（格式 viewId=3212278）"""
    text = _extract_text(view_field) if isinstance(view_field, (list, str)) else str(view_field)
    if "viewId=" in text:
        return text.split("viewId=", 1)[1].strip()
    return ""


def get_existing_keys(table_id, case_nos, recent_days=7):
    """查询 raw 表中已存在的 (案号, viewId) 集合。

    case_nos: 待查询的案号列表，会被去重后分块查询
    recent_days: 只比对最近 N 天内创建的记录，过滤旧数据
    返回: set of (caseNo, viewId) tuples
    """
    existing = set()
    unique_cases = list(set(case_nos))
    chunk_size = 50  # Feishu filter 值数组上限
    cutoff_ms = int((time.time() - recent_days * 86400) * 1000)

    for i in range(0, len(unique_cases), chunk_size):
        chunk = unique_cases[i:i + chunk_size]
        page_token = None
        while True:
            filter_payload = {
                "conjunction": "and",
                "conditions": [
                    {"field_name": "案号", "operator": "is", "value": chunk}
                ],
            }
            body = {"filter": filter_payload, "page_size": 500}
            if page_token:
                body["page_token"] = page_token

            path = f"/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{table_id}/records/search"
            resp = lark_api("POST", path, body)
            if not resp or resp.get("code") != 0:
                print(f"  dedup 查询跳过 (API error)", file=sys.stderr)
                return existing

            data = resp.get("data", {})
            for item in data.get("items", []):
                if item.get("create_time", 0) < cutoff_ms:
                    continue
                fields = item.get("fields", {})
                case_no = _extract_text(fields.get("案号"))
                view_id = _parse_view_id(fields.get("查看"))
                if case_no and view_id:
                    existing.add((case_no, view_id))

            if data.get("has_more") and data.get("page_token"):
                page_token = data["page_token"]
            else:
                break

    return existing


# ============================================================================
# 入口
# ============================================================================

def main():
    _check_token()
    parser = argparse.ArgumentParser(description="写入飞书多维表格")
    parser.add_argument("--input", required=True, help="batch JSON 文件路径")
    parser.add_argument("--subsite", required=True, choices=["zhixing", "shixin", "xgl"])
    parser.add_argument("--cross-ref", action="store_true", help="交叉匹配案件主表")
    parser.add_argument("--screenshots", default=None,
                        help="截图目录路径（如 output/screenshots），上传截图到案件主表")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"文件不存在: {args.input}", file=sys.stderr)
        sys.exit(1)

    # Step 1: 读 JSON
    print(f"读取: {args.input}")
    records = load_records(args.input)
    print(f"  共 {len(records)} 条记录（{len(set(r['company'] for r in records))} 家公司）")

    # Step 2: 写 raw 表
    written = write_raw_table(records, args.subsite)
    if written == 0 and records:
        print("写入 raw 表失败", file=sys.stderr)
        sys.exit(1)

    # Step 3: 交叉匹配（可选）
    if args.cross_ref:
        cross_ref_update(args.subsite)

    # Step 4: 上传截图（可选）
    if args.screenshots:
        print(f"\n--- 截图上传 ---")
        upload_screenshots_for_records(records, args.screenshots, args.subsite)

    print(f"\n✅ 完成: {written} 条写入 raw_{args.subsite}")


if __name__ == "__main__":
    main()
