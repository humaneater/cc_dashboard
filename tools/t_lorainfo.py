# -*- coding: utf-8 -*-
"""LoRA 清单接口自检：名字 + 文件时间 + 刷新（面板的排序 / ⟳ 靠它）。

用法（在插件目录下，用 ComfyUI 自带的 python）：
    ..\\..\\python_embeded\\python.exe tools\\t_lorainfo.py

只看不改：只列目录、读 stat，不打开权重、不联网、不写任何文件。
"""
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
if PLUGIN not in sys.path:
    sys.path.insert(0, PLUGIN)

import lorainfo                                              # noqa: E402

_FAILS = []


def ok(cond, msg):
    print(("  [ok]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        _FAILS.append(msg)


def skip(msg):
    print("  [skip] " + msg)


def main():
    print("=" * 70)
    print("LoRA 清单接口自检（lorainfo）")
    print("=" * 70)

    print("\n[1] 列得出来、带文件时间")
    t0 = time.perf_counter()
    r = lorainfo.listing(True)
    dt = (time.perf_counter() - t0) * 1000
    if not r.get("ok"):
        skip("这台机器上读不到 LoRA 目录（%s）" % r.get("error"))
        print("\n[ok] 跳过（没有 LoRA 目录时不该报错）")
        return 0
    ok(isinstance(r.get("items"), list), "items 是列表")
    ok(r["count"] == len(r["items"]), "count 与 items 对得上（%d）" % r["count"])
    ok(dt < 1500, "扫一遍 %.0f ms（大目录也只 stat，不读权重）" % dt)
    if r["count"]:
        first = r["items"][0]
        ok(set(first.keys()) >= {"name", "mtime", "size"},
           "每一项都有 name / mtime / size：%s" % first["name"])
        withtime = [x for x in r["items"] if x["mtime"] > 0]
        ok(len(withtime) >= max(1, r["count"] // 2),
           "%d/%d 个文件读到了修改时间（时间排序靠它）" % (len(withtime), r["count"]))
        ok(all(0 <= x["mtime"] < time.time() + 86400 for x in withtime),
           "时间戳都在合理范围内（不是 1970 也不是未来）")
        ok(all(not os.path.isabs(x["name"]) and ".." not in x["name"].split("/")
               for x in r["items"]), "名字都是相对路径、没有 ..（拒绝路径穿越）")
        newest = max(r["items"], key=lambda x: x["mtime"] or 0)
        print("       最新的一个：%s（%s）"
              % (newest["name"], time.strftime("%Y-%m-%d %H:%M", time.localtime(newest["mtime"]))))
    else:
        skip("models\\loras 是空的（功能没问题，只是没得排）")

    print("\n[2] 5 秒内重复问走缓存（省得每秒同步都 stat 一遍）")
    t1 = time.perf_counter()
    r2 = lorainfo.listing(False)
    ok(r2.get("cached") is True, "第二次 cached=True")
    ok(r2["count"] == r["count"], "两次结果一致")
    ok((time.perf_counter() - t1) < 0.05, "第二次 < 50ms")
    r3 = lorainfo.listing(True)
    ok(r3.get("cached") is False, "带 refresh=1 时不吃缓存（真的重新扫盘）")

    print("\n[3] 不该抛异常 / 不该越界")
    ok(lorainfo.full_path("../secrets.safetensors") is None, "越界名字 → None")
    ok(lorainfo.full_path("") is None, "空名字 → None")
    ok(lorainfo.full_path("definitely_not_here.safetensors") is None, "不存在的文件 → None")
    ok(isinstance(lorainfo.invalidate(), bool), "invalidate() 不抛异常（拿不到 folder_paths 就回 False）")

    print("\n[4] 接口注册与版本")
    init = os.path.join(PLUGIN, "__init__.py")
    txt = open(init, encoding="utf-8").read()
    ok("/cc_dashboard/loras" in txt, "__init__.py 注册了 /cc_dashboard/loras 路由")
    ok("_lorainfo" in txt, "__init__.py 导入了 lorainfo")
    dock = open(os.path.join(PLUGIN, "web", "dock.js"), encoding="utf-8").read()
    ok("fetchLoras" in dock and "setLoraSortMode" in dock and "ccd-lora-refresh" in dock,
       "面板里有排序 / 刷新（fetchLoras / setLoraSortMode / ⟳ 按钮）")

    print("\n" + "-" * 70)
    if _FAILS:
        print("[!] %d 项没过：" % len(_FAILS))
        for f in _FAILS:
            print("    - %s" % f)
        return 1
    print("[ok] 全部通过：清单带时间、刷新真重扫、越界读不到。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
