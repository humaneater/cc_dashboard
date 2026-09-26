# -*- coding: utf-8 -*-
"""翻译自检：确认「译」现在是真翻译（长句切块、不截断、可复用、全程离线）。

用法（在插件目录下，用 ComfyUI 自带的 python）：
    ..\\..\\python_embeded\\python.exe tools\\t_translate.py
    ..\\..\\python_embeded\\python.exe tools\\t_translate.py --quick   # 跳过长段落
    ..\\..\\python_embeded\\python.exe tools\\t_translate.py --dict    # 只测词典兜底

只看不改：不写任何文件、不联网（模型没装时会明确告诉你）。
"""
import argparse
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
if PLUGIN not in sys.path:
    sys.path.insert(0, PLUGIN)

from translate import opus_loaded, status, translate                       # noqa: E402

CASES = [
    ("短标签", "银发女孩微笑"),
    ("长句（用户的例子）",
     "男子抽烟大吸一口，过肺，烟雾吐出烟雾，然后逐渐变成猫耳绿发形象。"),
    ("自然语言", "一个女孩坐在窗边看书，阳光照进来，画面是温暖的午后氛围。"),
]

# 长段落：验证按句切块后“尾巴不会丢”
_TAIL = "最后一段画面是蓝色的猫坐在窗台上看雨。"
_BODY = "".join([
    "清晨的城市刚刚醒来，街道上还留着昨夜的水洼。",
    "女孩背着包走在人行道上，风把她的头发吹到一边。",
    "她停在面包店门口，玻璃上倒映出霓虹灯的颜色。",
    "店里的老板正在擦桌子，收音机里放着老歌。",
    "她买了两个可颂，一个留给自己，一个留给朋友。",
    "走出店门的时候，天空开始下起小雨。",
    "她撑开伞，慢慢走向河边的长椅。",
    "河面上有雾，远处的桥灯一盏一盏亮起来。",
    "她坐下来，把面包放在膝盖上，看着水面发呆。",
]) * 3 + _TAIL

_FAILS = []


def ok(cond, msg):
    print(("  [ok]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        _FAILS.append(msg)


def rss_mb():
    """当前进程占用的物理内存（MB）；测不到就返回 -1。"""
    try:                                   # ComfyUI 自带 psutil，最省事
        import os as _os
        import psutil
        return psutil.Process(_os.getpid()).memory_info().rss / 1048576.0
    except Exception:
        pass
    try:
        import ctypes
        from ctypes import wintypes

        class _PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]
        pmc = _PMC()
        pmc.cb = ctypes.sizeof(_PMC)
        fn = ctypes.windll.psapi.GetProcessMemoryInfo
        fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD]
        fn.restype = wintypes.BOOL
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        handle = ctypes.c_void_p(handle) if not isinstance(handle, int) else ctypes.c_void_p(handle)
        if not fn(handle, ctypes.byref(pmc), pmc.cb):
            return -1.0
        return pmc.WorkingSetSize / 1048576.0
    except Exception:
        return -1.0


def main(argv=None):
    ap = argparse.ArgumentParser(description="cc_dashboard 中→英翻译自检")
    ap.add_argument("--quick", action="store_true", help="跳过长段落用例")
    ap.add_argument("--dict", action="store_true", help="强制只用词典（离线兜底）")
    a = ap.parse_args(argv)

    st = status()
    print("=" * 70)
    print("cc_dashboard 中→英翻译自检")
    print("=" * 70)
    print("模型目录   : %s" % st["dir"])
    print("已安装     : %s" % ("是" if st["installed"] else "否"))
    print("已加载     : %s" % ("是" if st["loaded"] else "否（第一次翻译时才加载）"))
    print("常驻复用   : %s" % ("开（随 ComfyUI 退出释放）"
                               if st["keep"] else "关（每次用完即卸）"))
    print("词典词条   : %d" % st["dict_count"])
    if st.get("error"):
        print("上次错误   : %s" % st["error"])
    if not st["installed"] and not a.dict:
        print("\n[!] 模型没装：先跑 tools/install_translate.py（约 300 MB），"
              "否则「译」只能走词典。")
        return 2

    engine = "dict" if a.dict else "auto"
    base_rss = rss_mb()
    print("\n基线内存   : %s" % ("%.0f MB" % base_rss if base_rss > 0 else "（测不到）"))

    for name, src in CASES:
        print("\n[%s] %s" % (name, src))
        t0 = time.time()
        r = translate(src, engine=engine)
        dt = time.time() - t0
        print("   → %s" % r.get("text", ""))
        print("   引擎=%s 块=%s 加载=%sms 耗时=%.1fs"
              % (r.get("engine"), r.get("chunks"), r.get("load_ms"), dt))
        ok(bool(r.get("text")), "%s：有译文" % name)
        ok(bool(re.search(r"[A-Za-z]", r.get("text", "") or "")),
           "%s：译文是英文" % name)
        if not a.dict and st["installed"]:
            ok(r.get("engine") == "opus-mt", "%s：走的是本机 Opus-MT（不是词典）" % name)
            ok(not r.get("miss"), "%s：NMT 模式不报未收录" % name)

    if not a.dict and st["installed"]:
        print("\n[复用] 第二次翻译不应再加载模型")
        t0 = time.time()
        r2 = translate("雨后的街道，霓虹灯倒映在水面上。", engine=engine)
        dt2 = time.time() - t0
        print("   → %s（耗时 %.1fs）" % (r2.get("text", ""), dt2))
        ok(r2.get("load_ms") == 0, "第二次调用 load_ms=0（复用常驻模型）")
        ok(opus_loaded(), "模型仍在内存里（随 ComfyUI 退出释放）")

    if not a.quick and not a.dict and st["installed"]:
        print("\n[长段落] %d 字，验证切块后尾巴不丢" % len(_BODY))
        t0 = time.time()
        r3 = translate(_BODY, engine=engine)
        dt3 = time.time() - t0
        out = r3.get("text", "") or ""
        print("   引擎=%s 块=%s 耗时=%.1fs" % (r3.get("engine"), r3.get("chunks"), dt3))
        print("   译文开头: %s" % out[:110])
        print("   译文结尾: %s" % out[-110:])
        ok(r3.get("chunks", 0) >= 2, "长段落被切成多块（chunks=%s）" % r3.get("chunks"))
        tail_hit = [w for w in ("cat", "rain", "window", "blue") if w in out.lower()]
        ok(bool(tail_hit), "结尾那句被翻出来了（命中 %s）" % (tail_hit or "无"))
        ok(len(out) > 200, "译文长度正常（%d 字符）" % len(out))

    rss = rss_mb()
    if rss > 0 and base_rss > 0 and not a.dict:
        own = 0.0
        try:                                   # 只报模型自己那份，别把 torch 算进去
            import translate as _t
            mdl = (_t._opus_cache or {}).get("model")
            if mdl is not None:
                own = sum(p.numel() for p in mdl.parameters()) * 4 / 1048576.0
        except Exception:
            own = 0.0
        print("\n内存       : 进程 %.0f MB（比基线 +%.0f MB，其中大头是 torch 本身）"
              % (rss, rss - base_rss))
        if own:
            print("             Marian 权重本身约 %.0f MB —— 在已经跑着 torch 的 ComfyUI 里"
                  "只多这一份，只用内存、不占显存，常驻到 ComfyUI 关闭。" % own)

    print("\n" + "-" * 70)
    if _FAILS:
        print("[!] %d 项没过：" % len(_FAILS))
        for f in _FAILS:
            print("    - %s" % f)
        return 1
    print("[ok] 全部通过：含中文的文本走本机 Opus-MT，长句切块不截断。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
