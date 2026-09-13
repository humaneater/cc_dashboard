# -*- coding: utf-8 -*-
"""生成 / 更新 00_总控台.json 蓝图（命令行入口）。

用法：
    python tools/gen_dashboard.py                # 结转画布上现有的改动再重建
    python tools/gen_dashboard.py --fresh        # 忽略现有改动，按默认值重建
    python tools/gen_dashboard.py --out D:\\x\\wf.json

重建前会把现有蓝图备份到 <user>/default/cc_dashboard_backups/。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
if PLUGIN not in sys.path:
    sys.path.insert(0, PLUGIN)

from blueprint import generator                              # noqa: E402


if __name__ == "__main__":
    raise SystemExit(generator.main(sys.argv[1:]))
