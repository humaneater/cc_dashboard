# -*- coding: utf-8 -*-
"""cc_dashboard 中→英翻译：本机 Opus-MT 真翻译（长句切块）+ 内置绘画词典兜底。

装了 NMT 模型（<ComfyUI>/models/cc_dashboard/opus-mt-zh-en，用
tools/install_translate.py 一键下载，约 300 MB）就是**真翻译**：
含中文的文本一律走模型，长句切成小句、按预算合并后逐块翻译再拼回，不截断丢尾。
没装或者模型加载失败时才回落到内置绘画词典（danbooru 风格标签）。

生命周期：import 阶段不加载；第一次点翻译时才加载，之后常驻进程内复用
（约 0.4 GB 系统内存、强制 CPU 不占显存），随 ComfyUI 退出释放。
想改成“每次翻完就卸”，把环境变量 CC_TRANSLATE_KEEP 设成 0。
嫌等待久就调小 CC_TRANSLATE_BEAMS（默认 4，越小越快）。全程不联网。
"""
import importlib.util
import gc
import json
import os
import re
import threading
import time

try:                                    # 作为插件包导入
    from .tools import paths as _paths
except ImportError:                     # 以顶层模块 / 脚本方式导入
    from tools import paths as _paths

_HERE = os.path.dirname(os.path.abspath(__file__))
DICT_FILE = os.path.join(_HERE, "web", "zh_en_dict.json")
OPUS_DIR_NAME = "opus-mt-zh-en"
MAX_CHARS = 4000                        # 单次翻译上限，防呆

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
# 切小句：句末标点 + 逗号顿号都认。实测 Marian 对 >100 子词的输入会自己省略前文，
# 所以先切碎再按小预算合并，既要译文完整、又不退化成逐词硬拼。
PART_SPLIT_RE = re.compile(r"[。！？；\n!?;，,、]+")
CHUNK_TOKENS = 64                       # 每块子词上限（实测 60 上下质量最好）
MAX_PART_CHARS = 120                    # 没有标点的超长串先按字符粗切
KEEP_ENV = "CC_TRANSLATE_KEEP"          # =0/false/off 时每次翻完就卸载
BEAMS_ENV = "CC_TRANSLATE_BEAMS"        # 束搜索宽度，默认 4；调小更快
_lock = threading.RLock()
_dict_cache = None
_opus_cache = {"model": None, "tok": None, "error": None, "load_ms": 0,
               "loaded_at": 0.0, "retry_after": 0.0, "last_error": None}


# ------------------------------------------------------------------ 路径
def models_root():
    """ComfyUI 的 models 根目录（服务里用 folder_paths，命令行走目录上溯）。"""
    try:
        import folder_paths
        base = getattr(folder_paths, "models_dir", None)
        if base and os.path.isdir(base):
            return base
    except Exception:
        pass
    return os.path.join(_paths.comfy_root(), "models")


def opus_dir():
    return os.path.join(models_root(), "cc_dashboard", OPUS_DIR_NAME)


def _has_transformers():
    try:
        return importlib.util.find_spec("transformers") is not None
    except Exception:
        return False


# ------------------------------------------------------------------ 词典
def dict_data():
    global _dict_cache
    if _dict_cache is not None:
        return _dict_cache
    with _lock:
        if _dict_cache is not None:
            return _dict_cache
        d, raise_ = {}, []
        try:
            with open(DICT_FILE, encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw.get("dict"), dict):
                d = raw["dict"]
            if isinstance(raw.get("raise"), list):
                raise_ = raw["raise"]
        except Exception:
            d, raise_ = {}, []
        _dict_cache = {"dict": d, "keys": sorted(d, key=len, reverse=True),
                       "raise": set(raise_), "source": "full" if d else "empty"}
    return _dict_cache


def dict_count():
    return len(dict_data()["dict"])


def _hit_at(block, i, keys):
    """block[i] 处能匹配到的最长词典词；没有就返回空串。"""
    for k in keys:
        if len(k) <= len(block) - i and block.startswith(k, i):
            return k
    return ""


def _translate_block(block, D):
    out, miss = [], []
    i = 0
    n = len(block)
    while i < n:
        key = _hit_at(block, i, D["keys"])
        if key:
            v = D["dict"].get(key)
            if v:
                out.append(v)
            i += len(key)
            continue
        ch = block[i]
        if _CJK_RE.match(ch):
            j, buf = i, []
            while j < n and _CJK_RE.match(block[j]) and not _hit_at(block, j, D["keys"]):
                buf.append(block[j])
                j += 1
            if buf:
                miss.append("".join(buf))
            i = j if j > i else i + 1
            continue
        if re.match(r"[A-Za-z0-9_]", ch):
            j, buf = i, []
            while j < n and re.match(r"[A-Za-z0-9_'\-.]", block[j]):
                buf.append(block[j])
                j += 1
            if buf:
                out.append("".join(buf))
            i = j
            continue
        i += 1
    raised = [t for t in out if t in D["raise"]]
    rest = [t for t in out if t not in D["raise"]]
    text = re.sub(r"\s+", " ", " ".join(raised + rest)).strip()
    return {"text": text, "miss": miss, "hits": len(out)}


def translate_with_dict(text):
    """纯词典翻译；返回 {text, miss}。未收录的整块保留原文，不丢信息。"""
    D = dict_data()
    src = ("" if text is None else str(text))
    src = (src.replace("\u3000", " ")
              .replace("，", ",").replace("、", ",").replace("；", ",")
              .replace("。", ",").replace("！", ",").replace("!", ",")
              .replace("？", ",").replace("?", ",")
              .replace("\r\n", "\n").replace("\r", "\n"))
    tags, miss = [], []
    for raw in re.split(r"[,\n]+", src):
        blk = raw.strip()
        if not blk:
            continue
        if not _CJK_RE.search(blk):
            tags.append(blk)
            continue
        r = _translate_block(blk, D)
        tags.append(r["text"] if r["text"] else blk)
        miss.extend(r["miss"])
    clean, seen = [], set()
    for t in tags:
        s = re.sub(r"\s+", " ", str(t)).strip()
        if not s:
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        clean.append(s)
    miss_u = []
    for m in miss:
        if m not in miss_u:
            miss_u.append(m)
    return {"text": ", ".join(clean), "miss": miss_u}


# ------------------------------------------------------------------ Opus-MT（可选）
def opus_installed():
    d = opus_dir()
    need = ("config.json", "source.spm", "target.spm", "vocab.json")
    if not all(os.path.exists(os.path.join(d, f)) for f in need):
        return False
    return (os.path.exists(os.path.join(d, "pytorch_model.bin"))
            or os.path.exists(os.path.join(d, "model.safetensors")))


def status():
    """只读状态：不加载模型、不碰网络。"""
    return {
        "installed": opus_installed(),
        "loaded": opus_loaded(),
        "keep": keep_resident(),
        "engine": "opus-mt" if opus_installed() else "dict",
        "dir": opus_dir(),
        "dict_count": dict_count(),
        "transformers": _has_transformers(),
        "error": _opus_cache.get("error"),
    }


def keep_resident():
    """默认常驻（第一次翻完留在内存里复用）；CC_TRANSLATE_KEEP=0 改成用完即卸。"""
    v = os.environ.get(KEEP_ENV, "")
    return str(v).strip().lower() not in ("0", "false", "no", "off")


def num_beams():
    try:
        return max(1, min(8, int(os.environ.get(BEAMS_ENV, "4"))))
    except Exception:
        return 4


def opus_loaded():
    return _opus_cache.get("model") is not None


def _unload_opus():
    """把模型从内存里放掉（只在 CC_TRANSLATE_KEEP=0 时用，或手动调用）。"""
    with _lock:
        had = _opus_cache.get("model") is not None
        _opus_cache.update(model=None, tok=None, loaded_at=0.0)
        if had:
            try:
                gc.collect()
            except Exception:
                pass
    return had


def _load_opus():
    """懒加载 + 进程内常驻；返回 (model, tokenizer, error)。

    只有真的调用翻译才会走到这里；失败后会留一个冷却时间再允许重试，
    这样“先开 ComfyUI、后装模型”不用重启也能生效。
    """
    with _lock:
        if _opus_cache["model"] is not None:
            return _opus_cache["model"], _opus_cache["tok"], None
        now = time.time()
        if _opus_cache["error"] and now < _opus_cache["retry_after"]:
            return None, None, _opus_cache["error"]
        if not opus_installed():
            _opus_cache["error"] = "模型未安装"
            _opus_cache["retry_after"] = now + 5.0
            return None, None, _opus_cache["error"]
        t0 = time.time()
        try:
            from transformers import MarianMTModel, MarianTokenizer
            d = opus_dir()
            tok = MarianTokenizer.from_pretrained(d, local_files_only=True)
            model = MarianMTModel.from_pretrained(d, local_files_only=True)
            model.eval()
            try:                                # 绝不动显卡：翻译只吃 CPU
                model.to("cpu")
            except Exception:
                pass
            _opus_cache.update(model=model, tok=tok, error=None,
                               load_ms=int((time.time() - t0) * 1000),
                               loaded_at=time.time())
        except Exception as e:                     # 依赖缺失 / 文件损坏都走词典
            _opus_cache["error"] = "%r" % (e,)
            _opus_cache["retry_after"] = time.time() + 10.0
    return _opus_cache["model"], _opus_cache["tok"], _opus_cache["error"]


def _n_tokens(tok, s):
    try:
        return len(tok(s).input_ids)
    except Exception:                              # 量不出来就按字符粗估
        return max(1, len(s) // 2)


def split_sentences(text):
    """切成小句（句末标点 + 逗号顿号）；没有标点的超长串按字符粗切。"""
    out = []
    for part in PART_SPLIT_RE.split(text or ""):
        part = (part or "").strip()
        if not part:
            continue
        if len(part) > MAX_PART_CHARS:
            out.extend(part[i:i + MAX_PART_CHARS]
                       for i in range(0, len(part), MAX_PART_CHARS))
        else:
            out.append(part)
    return out


def split_chunks(tok, text, budget=CHUNK_TOKENS):
    """把整段文本按子词预算合并成若干块，每块都能整块喂给模型。"""
    chunks, cur = [], ""
    for s in split_sentences(text):
        cand = s if not cur else (cur + " " + s)
        if _n_tokens(tok, cand) <= budget:
            cur = cand
            continue
        if cur:
            chunks.append(cur)
            cur = ""
        if _n_tokens(tok, s) <= budget:
            cur = s
            continue
        n = max(1, _n_tokens(tok, s))               # 单句超预算：按比例硬切
        step = max(60, min(len(s), int(len(s) * budget / n)))
        for i in range(0, len(s), step):
            piece = s[i:i + step]
            if cur and _n_tokens(tok, cur + " " + piece) > budget:
                chunks.append(cur)
                cur = ""
            cur = piece if not cur else (cur + " " + piece)
    if cur:
        chunks.append(cur)
    return chunks or ([text] if (text or "").strip() else [])


def translate_with_opus(text):
    """本机 Opus-MT 中→英。返回 {text, chunks, load_ms, fresh}；不可用返回 None。"""
    was_loaded = opus_loaded()
    model, tok, _err = _load_opus()
    if model is None or tok is None:
        return None
    try:
        import torch
        chunks = split_chunks(tok, text)
        outs, failed = [], 0
        with torch.inference_mode():
            for ch in chunks:
                try:
                    batch = tok([ch], return_tensors="pt", padding=True,
                                truncation=True, max_length=512)
                    ids = model.generate(**batch, max_length=512,
                                         num_beams=num_beams())
                    outs.append(tok.batch_decode(ids, skip_special_tokens=True)[0].strip())
                except Exception as e:              # 单块失败只影响这一块
                    failed += 1
                    _opus_cache["last_error"] = "%r" % (e,)
                    outs.append((translate_with_dict(ch) or {}).get("text", ""))
        out = re.sub(r"\s+", " ", " ".join(x for x in outs if x)).strip()
        if not out:
            return None
        fresh = (not was_loaded)
        res = {"text": out, "chunks": len(chunks), "failed": failed,
               "fresh": fresh, "kept": keep_resident(),
               "load_ms": (_opus_cache.get("load_ms") or 0) if fresh else 0}
        if not keep_resident():
            _unload_opus()
        return res
    except Exception as e:
        _opus_cache["last_error"] = "%r" % (e,)
        return None


# ------------------------------------------------------------------ 统一入口
def translate(text, engine="auto"):
    """中→英统一入口。

    engine: auto / opus = 含中文就优先走本机 Opus-MT（长句切块，不截断）；
            dict        = 只用内置绘画词典。
    模型没装、加载失败或翻译失败时自动回落到词典。
    返回 {ok, text, miss, engine, chunks, loaded, load_ms}。
    """
    t = ("" if text is None else str(text))[:MAX_CHARS]
    if not t.strip():
        return {"ok": True, "text": "", "miss": [], "engine": "none",
                "chunks": 0, "loaded": opus_loaded(), "load_ms": 0}
    e = (engine or "auto").strip().lower()
    if e not in ("auto", "dict", "opus"):
        e = "auto"
    if e != "dict" and _CJK_RE.search(t) and opus_installed():
        r = translate_with_opus(t)
        if r and r.get("text"):
            return {"ok": True, "text": r["text"], "miss": [],
                    "engine": "opus-mt", "chunks": r.get("chunks", 1),
                    "loaded": opus_loaded(), "load_ms": r.get("load_ms", 0)}
    local = translate_with_dict(t)
    return {"ok": True, "text": local["text"], "miss": local["miss"],
            "engine": "dict", "chunks": 0, "loaded": opus_loaded(),
            "load_ms": 0}


# ------------------------------------------------------------------ ComfyUI 节点
class CCTranslateZhEn:
    """画布节点：中文提示词 → 英文。装了 Opus-MT 就是真翻译，没装用词典。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"multiline": True, "default": ""}),
            },
            "optional": {
                "engine": (["auto", "dict", "opus"], {"default": "auto"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("english", "missed")
    FUNCTION = "run"
    CATEGORY = "cc_dashboard/文本"
    DESCRIPTION = ("中文 → 英文提示词。engine=auto 时含中文就走本机 Opus-MT 真翻译"
                   "（长句自动切块，不截断），模型没装或失败才回落到内置绘画词典"
                   "（1000+ 词，danbooru 风格标签）；engine=dict 可强制只用词典。"
                   "missed 输出列出词典模式下没收录的词。")

    def run(self, text, engine="auto"):
        r = translate(text, engine=engine)
        return (r.get("text", ""), ", ".join(r.get("miss", [])))
