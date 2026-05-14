#!/usr/bin/env python3
"""
writers/feishu_build.py — lark-cli 自动创建飞书多维表格 + 写入 + DuplexLink

用于新用户：不需要手动在飞书建表、配字段、建关联。
只需提供一个空 Base 的 app_token，脚本自动完成建表和数据写入。

用法:
  python3 -m writers.feishu_build \
      --input output/zxgk_batch_20260514_zhixing.json \
      --app-token "你的base_token" \
      --screenshots output/screenshots

前置条件:
  - lark-cli 已安装并认证（lark-cli auth）
  - 已有一个空的飞书多维表格 Base
  - FEISHU_APP_TOKEN 环境变量设置为该 Base 的 token
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def lark_api(method, path, data=None):
    """调用 lark-cli api"""
    cmd = ["lark-cli", "api", method, path, "--as", "user"]
    if data is not None:
        cmd.append(json.dumps(data, ensure_ascii=False))
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(f"  lark-cli 错误: {result.stderr[:200]}", file=sys.stderr)
            return None
        return json.loads(result.stdout) if result.stdout.strip() else None
    except Exception as e:
        print(f"  lark-cli 异常: {e}", file=sys.stderr)
        return None


def create_table(app_token, name, fields):
    """创建飞书多维表格

    fields: [{"field_name": "xxx", "type": 1}, ...]
    返回: table_id 或 None
    """
    path = f"/open-apis/bitable/v1/apps/{app_token}/tables"
    body = {
        "table": {
            "name": name,
            "default_view_name": "默认视图",
            "fields": fields,
        }
    }
    resp = lark_api("POST", path, body)
    if resp and resp.get("code") == 0:
        table_id = resp.get("data", {}).get("table_id", "")
        print(f"  表 '{name}' 创建成功: {table_id}")
        return table_id
    else:
        msg = resp.get("msg", "unknown") if resp else "no response"
        print(f"  表 '{name}' 创建失败: {msg}", file=sys.stderr)
        return None


def add_field(app_token, table_id, field_name, field_type):
    """给已有表添加字段"""
    path = f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
    body = {"field_name": field_name, "type": field_type}
    resp = lark_api("POST", path, body)
    return resp and resp.get("code") == 0


def add_records(app_token, table_id, records):
    """批量添加记录

    records: [{"fields": {...}}, ...]
    """
    path = f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create"
    body = {"records": records}
    resp = lark_api("POST", path, body)
    if resp and resp.get("code") == 0:
        return len(resp.get("data", {}).get("records", []))
    return 0


def upload_media(file_path, app_token):
    """上传截图到飞书"""
    path = "/open-apis/drive/v1/medias/upload_all"
    cmd = [
        "lark-cli", "api", "POST", path, "--as", "user",
        "-F", f"file_name=@file:{file_path}",
        "-F", f"parent_type=bitable_image",
        "-F", f"parent_node={app_token}",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return None
        resp = json.loads(result.stdout) if result.stdout.strip() else {}
        return resp.get("data", {}).get("file_token") if resp.get("code") == 0 else None
    except Exception:
        return None


def build(app_token, batch_json_path, screenshots_dir=None):
    """全自动建表 + 写入

    流程:
      1. 创建 raw 表（案号、被执行人、立案日期、查看、同步日期）
      2. 创建案件主表（案号提取、被执行人提取、立案日期、执行法院、
         执行标的额、截图、验证状态）
      3. 建立 DuplexLink
      4. 批量写入 raw 表数据
      5. 上传截图（如果有）
    """
    with open(batch_json_path) as f:
        data = json.load(f)

    subsite = data.get("subsite", "unknown")
    batch_id = data.get("batch_id", "")

    print(f"feishu_build: 开始为 subsite={subsite} 创建表结构 ...")

    # Step 1: 创建 raw 表
    raw_name = f"{subsite}_raw"
    raw_fields = [
        {"field_name": "案号", "type": 1},          # Text
        {"field_name": "被执行人", "type": 1},       # Text
        {"field_name": "立案日期", "type": 5},        # DateTime
        {"field_name": "查看", "type": 1},            # Text (viewId)
        {"field_name": "同步日期", "type": 5},         # DateTime
    ]
    raw_table_id = create_table(app_token, raw_name, raw_fields)
    if not raw_table_id:
        print("❌ raw 表创建失败，终止", file=sys.stderr)
        return

    # Step 2: 创建案件主表
    case_name = f"{subsite}_案件主表"
    case_fields = [
        {"field_name": "案号提取", "type": 1},        # Text
        {"field_name": "被执行人提取", "type": 1},     # Text
        {"field_name": "立案日期", "type": 5},         # DateTime
        {"field_name": "执行法院", "type": 1},         # Text
        {"field_name": "执行标的额", "type": 1},        # Text
        {"field_name": "截图", "type": 17},            # Attachment
        {"field_name": "验证状态", "type": 3},          # SingleSelect
    ]
    case_table_id = create_table(app_token, case_name, case_fields)
    if not case_table_id:
        print("❌ 案件主表创建失败，终止", file=sys.stderr)
        return

    # Step 3: 建立 DuplexLink（双向关联）
    # raw 表 → 案件主表
    print("  建立 DuplexLink ...")
    add_field(app_token, raw_table_id, "案件主表", 17)  # 17 = LinkRecords
    add_field(app_token, case_table_id, "raw_一级", 17)

    # Step 4: 批量写入 raw 表
    total = 0
    for company_data in data.get("companies", []):
        company = company_data.get("company", "")
        batch = []
        for rec in company_data.get("records", []):
            batch.append({
                "fields": {
                    "案号": rec.get("caseNo", ""),
                    "被执行人": rec.get("name", ""),
                    "立案日期": int(rec.get("timestamp", 0) / 1000) if rec.get("timestamp") else None,
                    "查看": rec.get("viewId", ""),
                    "同步日期": batch_id[:8] if batch_id else "",
                }
            })
            if len(batch) >= 500:
                n = add_records(app_token, raw_table_id, batch)
                total += n
                batch = []
        if batch:
            total += add_records(app_token, raw_table_id, batch)

    print(f"  raw 表写入 {total} 条")

    # Step 5: 上传截图（如果有）
    if screenshots_dir and Path(screenshots_dir).is_dir():
        print(f"  上传截图 ...")
        uploaded = 0
        for company_data in data.get("companies", []):
            for rec in company_data.get("records", []):
                ss_path = rec.get("screenshot", "")
                if ss_path and Path(ss_path).exists():
                    token = upload_media(ss_path, app_token)
                    if token:
                        uploaded += 1
        print(f"  截图上传: {uploaded} 张")

    print(f"✅ 完成！")
    print(f"  raw 表 ID: {raw_table_id}")
    print(f"  案件主表 ID: {case_table_id}")
    print(f"  请在飞书中手动调整字段选项（如 SingleSelect 的「待销项/已销项」）")


def main():
    parser = argparse.ArgumentParser(
        description="飞书多维表格自动搭建 + 数据写入"
    )
    parser.add_argument("--input", required=True, help="batch JSON 文件路径")
    parser.add_argument(
        "--app-token",
        default=os.environ.get("FEISHU_APP_TOKEN", ""),
        help="飞书 Base app_token（默认从 FEISHU_APP_TOKEN 环境变量读取）",
    )
    parser.add_argument("--screenshots", default=None, help="截图目录")
    args = parser.parse_args()

    if not args.app_token:
        print(
            "错误: 需要 --app-token 参数或 FEISHU_APP_TOKEN 环境变量",
            file=sys.stderr,
        )
        sys.exit(1)

    if not Path(args.input).exists():
        print(f"错误: 文件不存在 — {args.input}", file=sys.stderr)
        sys.exit(1)

    # 检查 lark-cli 认证
    auth_check = lark_api("GET", "/open-apis/authen/v1/user_info")
    if not auth_check or auth_check.get("code") != 0:
        print("错误: lark-cli 未认证，请先运行: lark-cli auth", file=sys.stderr)
        sys.exit(1)

    build(args.app_token, args.input, args.screenshots)


if __name__ == "__main__":
    main()
