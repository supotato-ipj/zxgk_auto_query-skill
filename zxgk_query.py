#!/usr/bin/env python3
"""zxgk_query.py — 中国执行信息公开网 统一查询 CLI 入口

用法:
  python3 zxgk_query.py --company "XX公司"
  python3 zxgk_query.py --company "XX公司" --mode text-only --feishu
  python3 zxgk_query.py --company "XX公司" --mode full --feishu
  python3 zxgk_query.py --batch config/companies.txt --feishu
  python3 zxgk_query.py --batch config/companies.txt --mode full --feishu
  python3 zxgk_query.py --mode backfill --batch-id "20260510-zhixing" --feishu
  python3 zxgk_query.py --diagnose
  python3 zxgk_query.py --batch config/companies.txt --resume

返回值:
  0  成功（查到结果）
  1  查询无结果
  2  WAF 封禁（需冷却）
  3  captcha-solver 不可用
  4  配置/参数错误
"""
import sys
from zxgk.cli import main

if __name__ == "__main__":
    sys.exit(main())
