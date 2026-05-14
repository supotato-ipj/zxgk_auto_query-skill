# writers — Phase 2 可插拔储存层
#
# 每种 writer 独立子模块，统一接口：
#   write(batch_json_path) → None
#
# 用法：
#   python3 -m writers.sqlite --input output/zxgk_batch_20260514_zhixing.json
#   python3 -m writers.excel --input output/zxgk_batch_20260514_zhixing.json
#   python3 -m writers.feishu --input output/zxgk_batch_20260514_zhixing.json --subsite zhixing
