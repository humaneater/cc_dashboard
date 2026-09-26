# -*- coding: utf-8 -*-
"""下载 cc_dashboard 的「中→英」Opus-MT 模型（可选，约 300 MB，纯离线推理）。

只下 MarianMT 推理必需的文件（权重 / spm / 词表 / config），不下 rust、tf、h5，
所以比整个仓库小一大截。

默认源是 ModelScope（国内直连快），失败自动换 hf-mirror；两个都失败会给出
手动下载地址。实测过两个坑，脚本里都自动处理了：
  1. 系统代理指向 127.0.0.1 但代理没开 → 请求被直接拒绝，会自动清掉再重试；
  2. hf-mirror 大文件偶尔挂住不动 → 换 ModelScope 源，或断点续传重跑。

用法（在插件目录下，用 ComfyUI 自带的 python）：
    ..\\..\\python_embeded\\python.exe tools\\install_translate.py
    python tools\\install_translate.py --status      # 只看装没装
    python tools\\install_translate.py --dry-run     # 只列要下的文件
    python tools\\install_translate.py --force       # 补齐 / 校验文件
    python tools\\install_translate.py --source hf   # 强制走 hf-mirror

装完重启一次 ComfyUI，面板的「译」就是真翻译（长句按小句切块，不截断）；
没装也不影响：内置词典一直可用、不联网。
"""
import argparse
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
if PLUGIN not in sys.path:
    sys.path.insert(0, PLUGIN)

from translate import opus_dir, status                        # noqa: E402

REPO = "Helsinki-NLP/opus-mt-zh-en"
MIRROR = os.environ.get("HF_ENDPOINT") or "https://hf-mirror.com"
MS_API = "https://modelscope.cn/api/v1/models/%s/repo?Revision=master&FilePath="
FILES = [
    "config.json",
    "generation_config.json",
    "pytorch_model.bin",
    "source.spm",
    "target.spm",
    "tokenizer_config.json",
    "vocab.json",
    "special_tokens_map.json",
]
REQUIRED = ["config.json", "pytorch_model.bin", "source.spm", "target.spm",
            "tokenizer_config.json", "vocab.json"]
PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
              "http_proxy", "https_proxy", "all_proxy")


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit)
        n /= 1024.0


def clear_local_proxy():
    """系统代理指向本机但代理没开时，请求会被直接拒绝 —— 先清掉。"""
    cleared = []
    for k in PROXY_KEYS:
        v = os.environ.get(k) or ""
        if re.search(r"(127\.0\.0\.1|localhost)", v):
            os.environ.pop(k, None)
            cleared.append("%s=%s" % (k, v))
    if cleared:
        os.environ["NO_PROXY"] = "*"
        print("[i] 检测到本机代理没开（%s），已临时忽略它继续下载。"
              % ", ".join(cleared))
    return cleared


def url_hf(name, mirror):
    base = (mirror or "https://huggingface.co").rstrip("/")
    return "%s/%s/resolve/main/%s" % (base, REPO, name)


def url_modelscope(name):
    return MS_API % REPO + name


_OPENER = {"obj": None, "use_proxy": None}
_LAST_ERR = [""]


def _opener(use_proxy=False):
    """默认绕开系统代理：国内镜像直连就行，而挂着的死代理会把请求全挡掉。"""
    if _OPENER["obj"] is None or _OPENER["use_proxy"] != use_proxy:
        handlers = [] if use_proxy else [urllib.request.ProxyHandler({})]
        _OPENER["obj"] = urllib.request.build_opener(*handlers)
        _OPENER["use_proxy"] = use_proxy
    return _OPENER["obj"]


def fetch(name, url, dst, quiet=False, use_proxy=False):
    """单文件下载（支持断点续传）；返回 (ok, bytes)。"""
    path = os.path.join(dst, name)
    pos = os.path.getsize(path) if os.path.exists(path) else 0
    req = urllib.request.Request(url, headers={
        "User-Agent": "cc_dashboard/1.8 (+local, offline inference)"})
    if pos:
        req.add_header("Range", "bytes=%d-" % pos)
    try:
        with _opener(use_proxy).open(req, timeout=60) as r:
            resuming = (getattr(r, "status", 200) == 206 and pos > 0)
            total = int(r.headers.get("Content-Length") or 0)
            if not resuming:
                pos = 0
            got, last = 0, time.time()
            mode = "ab" if resuming else "wb"
            with open(path, mode) as fh:
                while True:
                    buf = r.read(262144)
                    if not buf:
                        break
                    fh.write(buf)
                    got += len(buf)
                    if not quiet and time.time() - last > 1.0:
                        last = time.time()
                        pct = ("%.0f%%" % (100.0 * (pos + got) / total)
                               if total else "?")
                        print("    %-26s %6s  %s" % (name, pct, human(pos + got)))
        size = os.path.getsize(path)
        return size > 0, size
    except urllib.error.HTTPError as e:
        if e.code == 416 and pos:          # 本地这份已经下完了
            return True, pos
        if os.path.exists(path) and os.path.getsize(path) == 0:
            os.remove(path)
        _LAST_ERR[0] = "HTTP %s" % e.code
        return False, 0
    except Exception as e:
        _LAST_ERR[0] = "%s: %s" % (type(e).__name__, e)
        return False, 0


def download_from(source, dst, use_proxy=False):
    """按某个源把文件拉齐；返回 True/False。"""
    print("\n[源] %s" % ("ModelScope" if source == "modelscope"
                         else "hf-mirror（%s）" % MIRROR))
    left = list(FILES)
    if source == "modelscope":
        for name in list(left):
            if name == "special_tokens_map.json":     # 这个仓库没有，别当失败
                continue
            ok, size = fetch(name, url_modelscope(name), dst, use_proxy=use_proxy)
            extra = "" if ok else (_LAST_ERR[0] or "")
            print("    %-26s %s %s" % (name, "ok " if ok else "失败",
                                       human(size) if ok else extra))
            if ok:
                left.remove(name)
        return not [f for f in REQUIRED if f in left]
    # hf 走 huggingface_hub（自带重试 / 校验）
    if MIRROR:
        os.environ["HF_ENDPOINT"] = MIRROR
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(repo_id=REPO, local_dir=dst,
                          allow_patterns=FILES)
    except Exception as e:
        print("    [!] huggingface_hub 下载失败：%r" % (e,))
        return False
    miss = [f for f in REQUIRED if not os.path.exists(os.path.join(dst, f))]
    return not miss


def main(argv=None):
    global MIRROR
    ap = argparse.ArgumentParser(description="下载 cc_dashboard 中→英 Opus-MT 模型")
    ap.add_argument("--source", default="auto",
                    choices=["auto", "modelscope", "hf"],
                    help="下载源；auto = ModelScope 优先，失败换 hf-mirror")
    ap.add_argument("--mirror", default=MIRROR,
                    help="hf 镜像地址（默认 hf-mirror.com；设成空串走官方）")
    ap.add_argument("--status", action="store_true", help="只看当前状态")
    ap.add_argument("--dry-run", action="store_true", help="只列要下的文件")
    ap.add_argument("--force", action="store_true",
                    help="已装也重新核对 / 补齐文件")
    ap.add_argument("--use-proxy", action="store_true",
                    help="让下载走系统代理（默认绕开，国内镜像直连更快）")
    a = ap.parse_args(argv)

    MIRROR = a.mirror
    st = status()
    dst = opus_dir()
    print("=" * 66)
    print("cc_dashboard 中→英翻译模型（Opus-MT，可选，纯离线推理）")
    print("=" * 66)
    print("目标目录 : %s" % dst)
    print("已安装   : %s" % ("是" if st["installed"] else "否"))
    print("词典词条 : %d" % st["dict_count"])
    print("transformers: %s" % ("可用" if st["transformers"] else "缺失"))
    if st.get("error"):
        print("上次错误 : %s" % st["error"])
    if a.status:
        return 0
    if a.dry_run:
        print("\n将要下载（%d 个文件）：" % len(FILES))
        for f in FILES:
            print("  - %s" % f)
        print("\n预估体积：约 300 MB（pytorch_model.bin 占了绝大部分）")
        return 0
    if st["installed"] and not a.force:
        print("\n已经装好了。要核对 / 补齐文件就再加 --force；"
              "想验证效果跑 tools/t_translate.py。")
        return 0

    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.makedirs(dst, exist_ok=True)
    sources = (["modelscope", "hf"] if a.source == "auto" else [a.source])
    print("\n开始下载（断点续传；只下推理需要的文件）...")

    done = False
    for round_no in (1, 2):
        if round_no == 2:
            # hf 那条路走 huggingface_hub，会读系统代理；这里兜一次“代理没开”
            if a.use_proxy or not clear_local_proxy():
                break
        for src in sources:
            if download_from(src, dst, use_proxy=a.use_proxy):
                done = True
                break
        if done:
            break

    missing = [f for f in REQUIRED if not os.path.exists(os.path.join(dst, f))]
    total = 0
    for root, _dirs, files in os.walk(dst):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    print("\n" + "-" * 66)
    if not done or missing:
        print("[!] 还缺：%s" % (", ".join(missing) or "（未知）"))
        print("    手动下载地址（任选其一，存到上面那个目录）：")
        for f in (missing or FILES):
            print("      模型: %s" % url_modelscope(f))
            print("      hf  : %s" % url_hf(f, a.mirror))
        return 1
    print("[ok] 模型就位：%s（共 %s）" % (dst, human(total)))
    print("     重启一次 ComfyUI，面板「译」就是真翻译（长句切块、不截断），"
          "第一次点会加载 1–3 秒，之后常驻内存复用。")
    print("     自检：python tools/t_translate.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
