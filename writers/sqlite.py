#!/usr/bin/env python3
"""
writers/sqlite.py — 本地 SQLite 写入器，零外部依赖。

用法:
  python3 -m writers.sqlite --input output/zxgk_batch_20260514_zhixing.json
  python3 -m writers.sqlite --input output/zxgk_batch_20260514_zhixing.json --db zxgk_results.db
"""

import argparse
import json
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
        created_at TEXT DEFAULT (datetime('now'))
    )
    """


def write_batch(json_path, db_path="zxgk_results.db"):
    """将 batch JSON 写入 SQLite"""
    with open(json_path) as f:
        data = json.load(f)

    batch_id = data.get("batch_id", "")
    subsite = data.get("subsite", "unknown")
    table_name = f"{subsite}_results"

    conn = sqlite3.connect(db_path)
    conn.execute(build_schema(table_name))

    count = 0
    for company_data in data.get("companies", []):
        company = company_data.get("company", "")
        for rec in company_data.get("records", []):
            conn.execute(
                f"INSERT INTO {table_name} "
                "(batch_id, company, case_no, name, date, view_id, timestamp, screenshot_path) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    batch_id,
                    company,
                    rec.get("caseNo", ""),
                    rec.get("name", ""),
                    rec.get("date", ""),
                    rec.get("viewId", ""),
                    rec.get("timestamp", 0),
                    rec.get("screenshot", ""),
                ),
            )
            count += 1

    conn.commit()
    conn.close()
    print(f"SQLite: {count} 条写入 {db_path} → 表 {table_name}")
    return count


def main():
    parser = argparse.ArgumentParser(description="SQLite 写入器")
    parser.add_argument("--input", required=True, help="batch JSON 文件路径")
    parser.add_argument("--db", default="zxgk_results.db", help="SQLite 数据库路径")
    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"错误: 文件不存在 — {args.input}", file=sys.stderr)
        sys.exit(1)

    write_batch(args.input, args.db)


if __name__ == "__main__":
    main()
