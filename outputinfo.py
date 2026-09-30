# -*- coding: utf-8 -*-
"""cc_dashboard 输出文件清单 + 视频尾帧抽取（v1.11.0）。

面板「同步 ▾」菜单用这两个能力（都不联网、只碰 ComfyUI 自己的 output 目录）：
  list_output(kind)         output/ 里的图片 / 视频清单（带 mtime，供历史选择 / 视频尾帧）
  extract_tail_frame(ref)   PyAV 解码视频最后一帧 → 写成 PNG 落到 output/cc_tail/

路径安全：所有读写都先做一次「必须落在 output 目录内」的校验，
.. / 绝对路径 / 别的盘符一律拒绝。测试可以用环境变量
CC_DASHBOARD_OUTPUT_DIR 指向临时目录，不必碰真实 output。
"""
import os
import re
import time

try:                                    # 作为插件包导入
    from .tools import paths as _paths
except ImportError:                     # 以顶层模块 / 脚本方式导入
    from tools import paths as _paths

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp",
              ".avif", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v",
              ".mpg", ".mpeg", ".wmv", ".flv"}
SKIP_DIRS = {"cc_tail"}                 # 尾帧自己存放的目录，不混进历史列表
MAX_ITEMS = 500                         # 列表上限（面板只渲染前 60 条，滚动再加）
MAX_DEPTH = 3                           # output/ 往下最多扫 3 层（video/ 这种一层就够）
SEEK_AFTER_SEC = 12.0                   # 超过这个时长的视频先 seek 到 90% 再解尾帧


def output_dir():
    """ComfyUI 的 output 目录（测试可用 CC_DASHBOARD_OUTPUT_DIR 覆盖）。"""
    env = os.environ.get("CC_DASHBOARD_OUTPUT_DIR")
    if env:
        return os.path.abspath(env)
    try:
        import folder_paths
        d = folder_paths.get_output_directory()
        if d:
            return os.path.abspath(d)
    except Exception:
        pass
    return os.path.join(_paths.comfy_root(), "output")


def _safe_root(root):
    return os.path.abspath(root)


def _safe_path(root, sub, name):
    """root / sub / name 归一化后必须还在 root 里面，否则报错。"""
    base = _safe_root(root)
    parts = [p for p in str(sub or "").replace("\\", "/").split("/")
             if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ValueError("非法路径：%s" % (sub,))
    full = os.path.abspath(os.path.join(base, *parts, str(name)))
    try:
        if os.path.commonpath([base, full]) != base:
            raise ValueError("路径越界：%s" % (full,))
    except ValueError:
        raise ValueError("路径越界：%s" % (full,))
    return full


def _rel(sub, name):
    return (sub + "/" + name) if sub else name


def _value(sub, name):
    return _rel(sub, name) + " [output]"


def list_output(kind="image", limit=MAX_ITEMS):
    """列 output 里的图片或视频，按修改时间倒序（最新在前）。

    返回 {"ok": True, "kind": …, "dir": …, "count": …, "items": [
        {"name", "subfolder", "value", "mtime", "size"}, …]}
    """
    kind = "video" if str(kind).lower() == "video" else "image"
    exts = VIDEO_EXTS if kind == "video" else IMAGE_EXTS
    root = output_dir()
    items = []
    if os.path.isdir(root):
        for dirpath, dirnames, filenames in os.walk(root):
            rel = os.path.relpath(dirpath, root)
            depth = 0 if rel == "." else (rel.count(os.sep) + 1)
            if depth >= MAX_DEPTH:
                dirnames[:] = []
            else:
                dirnames[:] = sorted(
                    d for d in dirnames
                    if d not in SKIP_DIRS and not d.startswith("."))
            for fn in filenames:
                ext = os.path.splitext(fn)[1].lower()
                if ext not in exts:
                    continue
                full = os.path.join(dirpath, fn)
                try:
                    if not os.path.isfile(full):
                        continue
                    st = os.stat(full)
                except OSError:
                    continue
                sub = "" if rel == "." else rel.replace(os.sep, "/")
                items.append({
                    "name": fn,
                    "subfolder": sub,
                    "value": _value(sub, fn),
                    "mtime": float(st.st_mtime),
                    "size": int(st.st_size),
                })
    items.sort(key=lambda it: (-it["mtime"], it["name"].lower()))
    out = items[: max(0, int(limit or MAX_ITEMS))]
    return {"ok": True, "kind": kind, "dir": root,
            "count": len(items), "items": out}


def _parse_ref(ref):
    """把面板传的引用解析成 (subfolder, name)。

    认三种写法：
      {"file": "video/total_i2v_00023_.mp4 [output]"}
      {"name": "total_i2v_00023_.mp4", "subfolder": "video"}
      "video/total_i2v_00023_.mp4"
    """
    if isinstance(ref, dict):
        data = ref
    else:
        data = {"file": ref}
    raw = data.get("file") or data.get("value") or data.get("path") or ""
    if not raw:
        name = str(data.get("name") or data.get("filename") or "")
        sub = str(data.get("subfolder") or "")
        raw = (sub.replace("\\", "/").strip("/") + "/" + name) if sub else name
    raw = str(raw).strip()
    if raw.endswith("[output]"):
        raw = raw[:-len("[output]")].strip()
    elif raw.endswith("[input]") or raw.endswith("[temp]"):
        raise ValueError("只能读 output 目录里的视频")
    if raw.startswith("/") or raw.startswith("\\"):
        raise ValueError("非法路径：%s" % (raw,))
    raw = raw.replace("\\", "/").lstrip("/")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts) or any(":" in p for p in parts):
        raise ValueError("非法路径：%s" % (raw,))
    sub = "/".join(parts[:-1])
    name = parts[-1]
    return sub, name


def _decode_last_frame(path):
    """PyAV 解最后一帧 → (PIL.Image, 解码帧数, 时长秒, 旋转角)。"""
    import av
    with av.open(path) as container:
        if not container.streams.video:
            raise ValueError("文件里没有视频轨")
        stream = container.streams.video[0]
        duration = 0.0
        try:
            if stream.duration is not None and stream.time_base is not None:
                duration = float(stream.duration * stream.time_base)
        except Exception:
            duration = 0.0
        rotation = 0
        try:
            md = stream.metadata or {}
            rotation = int(float(md.get("rotate", 0) or 0)) % 360
        except Exception:
            rotation = 0
        # 短视频直接全解；长视频先跳到 90% 再解尾巴，省得白解几分钟
        if duration > SEEK_AFTER_SEC:
            try:
                offset = int(max(0.0, duration * 0.9) * av.time_base)
                container.seek(offset, backward=True, any_frame=False,
                               stream=stream)
            except Exception:
                pass
        last = None
        n = 0
        for frame in container.decode(stream):
            last = frame
            n += 1
        if last is None:
            raise ValueError("解不出任何帧（文件可能损坏）")
        img = last.to_image()
    if rotation in (90, 270):
        try:
            from PIL import Image
            tr = (Image.Transpose.ROTATE_90 if rotation == 90
                  else Image.Transpose.ROTATE_270)
            img = img.transpose(tr)
        except Exception:
            pass
    return img, n, duration, rotation


def extract_tail_frame(ref, out_sub="cc_tail"):
    """抽视频最后一帧写成 PNG → {"ok", "value", "name", "subfolder", …}。"""
    root = output_dir()
    sub, name = _parse_ref(ref)
    ext = os.path.splitext(name)[1].lower()
    if ext not in VIDEO_EXTS:
        raise ValueError("不是视频文件：%s" % name)
    src = _safe_path(root, sub, name)
    if not os.path.isfile(src):
        raise ValueError("视频不存在：%s" % _rel(sub, name))
    img, frames, duration, rotation = _decode_last_frame(src)

    out_dir = _safe_path(root, "", out_sub)
    os.makedirs(out_dir, exist_ok=True)
    stem = re.sub(r"[^\w\-.]+", "_", os.path.splitext(name)[0])[:60] or "video"
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_name = "cc_tail_%s_%s.png" % (stem, stamp)
    out_path = os.path.join(out_dir, out_name)
    i = 2
    while os.path.exists(out_path):                     # 同一秒里连截两次也不覆盖
        out_name = "cc_tail_%s_%s_%d.png" % (stem, stamp, i)
        out_path = os.path.join(out_dir, out_name)
        i += 1
    img.save(out_path, "PNG")
    st = os.stat(out_path)
    return {
        "ok": True,
        "value": _value(out_sub, out_name),
        "name": out_name,
        "subfolder": out_sub,
        "source": _rel(sub, name),
        "width": int(img.size[0]),
        "height": int(img.size[1]),
        "frames": int(frames),
        "duration": round(float(duration), 3),
        "rotation": int(rotation),
        "mtime": float(st.st_mtime),
        "size": int(st.st_size),
        "dir": out_dir,
    }


def status():
    """给面板 / 自检看的概览（不扫目录内容，只报路径与支持后缀）。"""
    return {
        "ok": True,
        "dir": output_dir(),
        "images": sorted(IMAGE_EXTS),
        "videos": sorted(VIDEO_EXTS),
    }
