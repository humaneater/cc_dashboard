# -*- coding: utf-8 -*-
"""把插件打成可以直接发给别人的 zip。

用法：
    python tools/make_zip.py [--out dist] [--list]

产出的 zip 里只有一层 cc_dashboard/ 目录，别人解压到
<ComfyUI>/custom_nodes/ 下就是 <ComfyUI>/custom_nodes/cc_dashboard/。
缓存、备份、本地快照（_object_info.json）不进包。
"""
import argparse
import os
import sys
import time
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
if PLUGIN not in sys.path:
    sys.path.insert(0, PLUGIN)

from tools import paths                                    # noqa: E402

SKIP_DIRS = {"__pycache__", ".git", ".github", "dist", "_t_dock", "node_modules"}
SKIP_EXT = {".pyc", ".pyo", ".log", ".zip"}
SKIP_FILES = {"_object_info.json", ".DS_Store"}


def version():
    with open(os.path.join(PLUGIN, "__init__.py"), encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("__version__"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return "0.0.0"


def collect():
    out = []
    for dirpath, dirnames, filenames in os.walk(PLUGIN):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn in SKIP_FILES or os.path.splitext(fn)[1] in SKIP_EXT:
                continue
            full = os.path.join(dirpath, fn)
            out.append((full, os.path.relpath(full, os.path.dirname(PLUGIN))))
    return sorted(out, key=lambda p: p[1])


def main(argv=None):
    ap = argparse.ArgumentParser(description="打包 cc_dashboard 插件")
    ap.add_argument("--out", default=os.path.join(PLUGIN, "dist"),
                    help="输出目录，默认 <plugin>/dist")
    ap.add_argument("--list", action="store_true", help="只列出会打包的文件")
    args = ap.parse_args(argv)

    files = collect()
    if args.list:
        for _full, rel in files:
            print(rel)
        print("共 %d 个文件" % len(files))
        return 0

    os.makedirs(args.out, exist_ok=True)
    name = "cc_dashboard-%s.zip" % version()
    dst = os.path.join(args.out, name)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
        for full, rel in files:
            zf.write(full, rel.replace(os.sep, "/"))
        # 版本 + 打包时间，方便别人确认拿到的是哪一版
        zf.writestr("cc_dashboard/VERSION.txt",
                    "cc_dashboard %s\npacked %s\n"
                    % (version(), time.strftime("%Y-%m-%d %H:%M:%S")))
    size = os.path.getsize(dst) / 1024.0 / 1024.0
    print("wrote %s（%.2f MB，%d 个文件）" % (dst, size, len(files)))
    print("发给别人：解压到 <ComfyUI>/custom_nodes/ 下，重启 ComfyUI 即可。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
