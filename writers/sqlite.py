#!/usr/bin/env python3
"""
writers/sqlite.py — 本地 SQLite 写入器，零外部依赖。

用法:
  python3 -m writers.sqlite --input output/zxgk_batch_20260514_zhixing.json
  python3 -m writers.sqlite --input output/zxgk_batch_20260514_zhixing.json --db zxgk_results.db
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def build_schema(table_name):
    return f"""
    CREATE TABLE IF NOT EXISTS {table_name} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id TEXT,
        company TEXT,
        case_no TEXT,
        name TEXT,
        date TEXT,
        view_id TEXT,
        timestamp INTEGER,
        screenshot_path TEXT,
        screenshot_data BLOB,
        created_at TEXT DEFAULT (datetime('now'))
    )
    """


def write_batch(json_path, db_path="zxgk_results.db", store_screenshots="file"):
    """将 batch JSON 写入 SQLite

    store_screenshots:
      "file" — 只存路径（默认，和旧行为一致）
      "blob" — 存二进制，写入成功后删本地文件
      "both" — 路径 + BLOB 都存，文件保留
    """
    with open(json_path) as f:
        data = json.load(f)

    batch_id = data.get("batch_id", "")
    subsite = data.get("subsite", "unknown")
    table_name = f"{subsite}_results"

    conn = sqlite3.connect(db_path)
    conn.execute(build_schema(table_name))
    # 迁移旧表：如果没有 screenshot_data 列则添加
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table_name})")]
    if "screenshot_data" not in cols:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN screenshot_data BLOB")
        conn.commit()

    count = 0
    for company_data in data.get("companies", []):
        company = company_data.get("company", "")
        for rec in company_data.get("records", []):
            ss_path = rec.get("screenshot", "")
            ss_blob = None
            if store_screenshots in ("blob", "both") and ss_path:
                try:
                    with open(ss_path, "rb") as f:
                        ss_blob = f.read()
                except OSError:
                    pass

            conn.execute(
                f"INSERT INTO {table_name} "
                "(batch_id, company, case_no, name, date, view_id, timestamp, screenshot_path, screenshot_data) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    batch_id,
                    company,
                    rec.get("caseNo", ""),
                    rec.get("name", ""),
                    rec.get("date", ""),
                    rec.get("viewId", ""),
                    rec.get("timestamp", 0),
                    ss_path,
                    ss_blob,
                ),
            )
            count += 1

            if store_screenshots == "blob" and ss_blob:
                try:
                    os.remove(ss_path)
                except OSError:
                    pass

    conn.commit()
    conn.close()
    print(f"SQLite: {count} 条写入 {db_path} → 表 {table_name}")
    return count


def main():
    parser = argparse.ArgumentParser(description="SQLite 写入器")
    parser.add_argument("--input", required=True, help="batch JSON 文件路径")
    parser.add_argument("--db", default="zxgk_results.db", help="SQLite 数据库路径")
    parser.add_argument("--store-screenshots", default="file",
                        choices=["file", "blob", "both"],
                        help="截图存储方式: file(路径) blob(二进制) both(两者)")
    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"错误: 文件不存在 — {args.input}", file=sys.stderr)
        sys.exit(1)

    write_batch(args.input, args.db, args.store_screenshots)


if __name__ == "__main__":
    main()
