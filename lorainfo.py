# -*- coding: utf-8 -*-
"""只读：LoRA 清单 + 文件时间（面板的「排序 / 刷新」用它）。

面板要给 LoRA 下拉做「按名字 / 按下载时间」排序，而 ComfyUI 自带的下拉只给
名字、不给时间；所以这里自己列一份：名字 + mtime + 大小。

  GET /cc_dashboard/loras             → {count, dirs, items: [{name, mtime, size}]}
  GET /cc_dashboard/loras?refresh=1   → 先清掉 ComfyUI 的目录缓存再扫，
                                        刚下好的文件立刻能选（不用重启）

只读文件夹（models\\loras 与其子目录），不加载任何权重、不联网、不写文件。
扫描优先走 ComfyUI 自己的 folder_paths（它就是节点下拉的那份清单，含子目录、
扩展名也一致）；不在 ComfyUI 里跑（自检脚本）时退化成自己扫目录。
"""
import os
import time

try:                                     # 作为插件包导入
    from .tools import paths as _paths
except ImportError:                      # 以顶层模块 / 脚本方式导入
    try:
        from tools import paths as _paths
    except ImportError:                  # 单独拷出来跑（比如单测）
        _paths = None

FOLDER = "loras"
# folder_paths 不在时（独立脚本）自己认这几个后缀，和 ComfyUI 的 supported_pt_extensions 一致
FALLBACK_EXTS = (".safetensors", ".sft", ".ckpt", ".pt", ".pt2", ".bin", ".pth", ".gguf")

_CACHE = {"stamp": 0.0, "data": None}    # 只在没要求 refresh 时用，避免每次同步都重新 stat
_CACHE_TTL = 5.0


def roots():
    """这个文件夹在本机的位置（可能不止一个）。"""
    out = []
    try:
        import folder_paths
        for p in folder_paths.get_folder_paths(FOLDER):
            if p and os.path.isdir(p):
                out.append(os.path.abspath(p))
    except Exception:
        pass
    if not out and _paths is not None:
        cand = os.path.join(_paths.comfy_root(), "models", FOLDER)
        if os.path.isdir(cand):
            out.append(os.path.abspath(cand))
    return out


def extensions():
    try:
        import folder_paths
        exts = folder_paths.folder_names_and_paths[FOLDER][1]
        if exts:
            return tuple(exts)
    except Exception:
        pass
    return FALLBACK_EXTS


def invalidate():
    """清掉 ComfyUI 的目录缓存 → 下一次 get_filename_list 真的重新扫盘。

    folder_paths 的缓存平时靠「目录 mtime 变了」自动失效，但同一个目录里
    连着重命名 / 同秒内写入时可能看不出来，所以刷新按钮直接清。
    """
    ok = False
    try:
        import folder_paths
    except Exception:
        return False
    try:
        folder_paths.cache_helper.clear()
        ok = True
    except Exception:
        pass
    try:
        folder_paths.filename_list_cache.pop(FOLDER, None)
        ok = True
    except Exception:
        pass
    return ok


def names(refresh=False):
    """LoRA 文件名清单（相对 models\\loras 的路径，含子目录）。"""
    if refresh:
        invalidate()
    try:
        import folder_paths
        return [str(n) for n in folder_paths.get_filename_list(FOLDER)]
    except Exception:
        pass
    # 独立跑：自己扫
    exts = tuple(x.lower() for x in extensions())
    out = []
    for root in roots():
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__")]
            for fn in filenames:
                if not fn.lower().endswith(tuple(exts)):
                    continue
                rel = os.path.relpath(os.path.join(dirpath, fn), root)
                out.append(rel.replace("\\", "/"))
    return sorted(set(out))


def full_path(name):
    try:
        import folder_paths
        p = folder_paths.get_full_path(FOLDER, name)
        if p:
            return p
    except Exception:
        pass
    for root in roots():
        cand = os.path.abspath(os.path.join(root, *str(name).replace("\\", "/").split("/")))
        if _paths is not None and not _paths.inside(cand, root):
            continue
        if os.path.isfile(cand):
            return cand
    return None


def items(refresh=False):
    """[{name, mtime, size}]：mtime 是 Unix 秒（0 = 读不到，面板会退化成按名字排）。"""
    out = []
    for n in names(refresh):
        mtime, size = 0.0, 0
        p = full_path(n)
        if p:
            try:
                st = os.stat(p)
                mtime = float(st.st_mtime)
                size = int(st.st_size)
            except Exception:
                pass
        out.append({"name": n, "mtime": mtime, "size": size})
    out.sort(key=lambda r: r["name"].lower())
    return out


def listing(refresh=False):
    """面板调的入口：任何异常都不往外抛，返回 ok=False 让面板退回核心接口。"""
    now = time.time()
    if not refresh and _CACHE["data"] is not None and (now - _CACHE["stamp"]) < _CACHE_TTL:
        data = dict(_CACHE["data"])
        data["cached"] = True
        return data
    try:
        rows = items(refresh)
    except Exception as e:
        return {"ok": False, "error": repr(e), "count": 0, "items": [], "dirs": roots()}
    data = {
        "ok": True,
        "count": len(rows),
        "items": rows,
        "dirs": roots(),
        "fetched": now,
    }
    _CACHE["stamp"] = now
    _CACHE["data"] = dict(data)
    data["cached"] = False
    return data
