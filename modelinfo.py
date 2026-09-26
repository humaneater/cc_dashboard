# -*- coding: utf-8 -*-
"""只读探测：这个模型自带不带文本编码器 / VAE、属于哪个架构族、训练分辨率是多少。

面板换图像模型时问一次（GET /cc_dashboard/model_info?name=...），据此决定
顶栏「外挂资源」那一行要不要出现、默认填哪个文件，以及「★ 推荐分辨率」给多少。

只读 safetensors 的头部（前 8 字节长度 + JSON 头），**不加载权重、不占显存**，
单个文件几毫秒到几十毫秒；按「文件名 + mtime + 大小」缓存，重复问不再读盘。

判据一：张量名前缀 / 形状（判定架构族，本机 18 个 ckpt 实测过）
  is_anima 有 llm_adapter 张量（本机三个 anima 模型都命中，SDXL 系全不命中）
  wan      有 patch_embedding.weight + model.diffusion_model.blocks.（Wan 2.2 实测命中）
  sdxl     有 label_emb.0.0.weight（[1280, 2816]）或 conditioner.embedders.1
  sd3      有 joint_blocks.（MMDiT）    flux 有 double_blocks. + single_blocks.
  sd15/sd21 看 cross-attn 的上下文维度（attn2.to_k 第二维 768 / 1024 / 2048）
  has_te   有 conditioner. / cond_stage_model. / text_encoders. / clip_l. /
           clip_g. / text_model. / model.embed_tokens. / encoder.block. 前缀
  has_vae  有 first_stage_model. / vae. / decoder. / encoder. 前缀
  has_dit  有 model.diffusion_model. / net. 前缀

判据二：__metadata__ 里作者写死的训练分辨率 —— 有就**优先用它**（自己训的 / 转换过的
  ckpt 常带 kohya 的 ss_resolution、ss_bucket_info，或 ModelSpec 的 modelspec.resolution）。
  实测本机这批 CivitAI 下载的成品 ckpt **一个都没写**（18 个里 0 个有 ss_resolution /
  modelspec.resolution），所以绝大多数情况下只能靠「架构族 → 该族官方训练分辨率」。
  返回体里 res_src 会说清这条建议是哪来的：file（文件里写的）/ family（按结构判族）/ none。

读不到（.gguf / .ckpt / 不在白名单目录 / 文件坏了）→ known=False，
面板自动退回「按模型名判断」（名字含 anima 就当外挂），不报错、不阻塞。
"""
import json
import os
import re
import struct

try:                                     # 作为插件包导入
    from .tools import paths as _paths
except ImportError:                      # 以顶层模块 / 脚本方式导入
    try:
        from tools import paths as _paths
    except ImportError:                  # 单独拷出来跑（比如单测）
        _paths = None


# 允许探测的模型目录（够用就好：这几类里都是 safetensors）
FOLDERS = ("checkpoints", "unet", "diffusion_models", "vae", "text_encoders")

_TE_PREFIX = ("conditioner.", "cond_stage_model.", "text_encoders.",
              "clip_l.", "clip_g.", "text_model.", "model.embed_tokens.",
              "encoder.block.", "te_model.")
_VAE_PREFIX = ("first_stage_model.", "vae.", "decoder.", "encoder.")
_DIT_PREFIX = ("model.diffusion_model.", "net.")

MAX_HEADER = 128 * 1024 * 1024          # 头部再大也不至于这么大，防呆

_CACHE = {}                             # path -> (mtime_ns, size, result)

# 架构族 → (显示名, 训练宽, 训练高, 一句话理由)。宽高为 0 = 这类文件没有「分辨率」可言。
# 数字都是各家的官方训练 / 官方示例分辨率，不是面板瞎猜的：
#   SDXL 1024²（官方桶 1024² / 1152×896 / 1216×832 / 1344×768 / 1536×640）
#   SD1.5 512²、SD2.x 768²、SD3 1024²、FLUX 1024²
#   ANIMA 官方 README：512²~1536²，默认按 1024²（"Works at resolutions between 512^2 and 1536^2"）
#   Wan 2.2 I2V-A14B：官方 480P / 720P 两档，480P = 832×480（720P 是 1280×720，很吃显存）
FAMILY = {
    "anima": ("ANIMA", 1024, 1024,
              "ANIMA 官方支持 512²~1536²，默认按 1024²"),
    "sdxl": ("SDXL / Illustrious / NoobAI / Pony", 1024, 1024,
             "SDXL 系官方训练分辨率 1024²"),
    "sd15": ("SD1.5", 512, 512, "SD1.5 训练分辨率 512²"),
    "sd21": ("SD2.x", 768, 768, "SD2.x 训练分辨率 768²"),
    "sd3": ("SD3 / SD3.5", 1024, 1024, "SD3 官方训练分辨率 1024²"),
    "flux": ("FLUX.1", 1024, 1024, "FLUX 官方分辨率 1024²"),
    "wan": ("Wan 视频 2.1 / 2.2", 832, 480,
            "Wan 2.2 官方 480P 档 832×480（720P 是 1280×720，很吃显存）"),
    "other": ("纯 VAE / 文本编码器（没有扩散主干）", 0, 0, ""),
    "unknown": ("认不出的结构", 0, 0, ""),
}

# 作者自己写在 __metadata__ 里的训练分辨率（有就信它）
_META_RES_KEYS = ("modelspec.resolution", "ss_resolution", "training_resolution",
                  "ss_training_resolution", "resolution")

_DIFFUSION_PREFIX = ("model.diffusion_model.", "net.", "double_blocks.",
                     "single_blocks.", "joint_blocks.", "x_embedder.", "llm_adapter")

def folder_roots(folder):
    """这个模型目录在哪（运行在 ComfyUI 里就用它自己的解析结果）。"""
    out = []
    try:
        import folder_paths
        for p in folder_paths.get_folder_paths(folder):
            if p and os.path.isdir(p):
                out.append(os.path.abspath(p))
    except Exception:
        pass
    if not out and _paths is not None:
        cand = os.path.join(_paths.comfy_root(), "models", folder)
        if os.path.isdir(cand):
            out.append(cand)
    return out


def resolve(name, folders=FOLDERS):
    """文件名 → 磁盘路径。只认白名单目录里的文件，拒绝路径穿越。"""
    if not name or not isinstance(name, str):
        return None
    name = name.strip().replace("\\", "/")
    if not name or name.startswith("/") or os.path.isabs(name):
        return None
    if any(p in ("", ".", "..") for p in name.split("/")):
        return None
    for folder in folders:
        for root in folder_roots(folder):
            cand = os.path.abspath(os.path.join(root, *name.split("/")))
            if not os.path.isfile(cand):
                continue
            if _paths is not None and not _paths.inside(cand, root):
                continue
            return cand
    return None


def read_header(path):
    """safetensors 头部 → (张量表, __metadata__ 表)。只读前几 MB，不碰权重。"""
    with open(path, "rb") as fh:
        raw = fh.read(8)
        if len(raw) != 8:
            raise ValueError("not a safetensors file")
        n = struct.unpack("<Q", raw)[0]
        if n <= 0 or n > MAX_HEADER:
            raise ValueError("bad safetensors header length %d" % n)
        head = json.loads(fh.read(n).decode("utf-8", "replace"))
    meta = head.pop("__metadata__", None) or {}
    if not isinstance(meta, dict):
        meta = {}
    return head, meta


def head_shape(head, key):
    """某个张量的形状（读不到就 None）。"""
    v = head.get(key)
    if isinstance(v, dict):
        s = v.get("shape")
        if isinstance(s, (list, tuple)):
            return [int(x) for x in s]
    return None


def detect_arch(head):
    """按张量名 / 形状判断这是哪家的模型（认不出就 unknown）。"""
    keys = head.keys()

    def any_key(*subs):
        return any(any(s in k for s in subs) for k in keys)

    def any_pref(*prefs):
        if len(prefs) == 1 and isinstance(prefs[0], (list, tuple)):
            prefs = tuple(prefs[0])          # 允许直接把前缀表丢进来
        return any(k.startswith(prefs) for k in keys)

    if any_key("llm_adapter"):                       # 本机 3 个 anima 都命中
        return "anima"
    if is_wan_like(head) and any(k.startswith("blocks.") or ".blocks." in k for k in keys):
        return "wan"                                 # Wan 2.1 / 2.2 实测命中
    if any_key("double_blocks.") and any_key("single_blocks."):
        return "flux"
    if any_key("joint_blocks."):
        return "sd3"
    if "model.diffusion_model.label_emb.0.0.weight" in head \
            or any_pref("conditioner.embedders.1"):
        return "sdxl"                                # SDXL 专属：加训的 label_emb + 第二个 TE
    # 单 CLIP 的老 UNet：cross-attn 的上下文维度 768（SD1.5）/ 1024（SD2.1）/ 2048（SDXL）
    for k, v in head.items():
        if k.endswith("attn2.to_k.weight") and isinstance(v, dict):
            s = v.get("shape") or []
            if len(s) == 2 and 512 <= int(s[1]) <= 4096:
                ctx = int(s[1])
                if ctx == 768:
                    return "sd15"
                if ctx == 1024:
                    return "sd21"
                if ctx == 2048:
                    return "sdxl"
            break
    if any_pref(_DIFFUSION_PREFIX):
        return "unknown"
    if any_pref(("first_stage_model.", "vae.", "decoder.", "encoder.")) \
            or any_pref(_TE_PREFIX):
        return "other"                               # 纯 VAE / 纯文本编码器
    return "unknown"


def _ints(txt):
    return [int(x) for x in re.findall(r"\d+", str(txt))]


def is_wan_like(head):
    """Wan 2.1 / 2.2 的 DiT 签名：patch_embedding 的形状是 [dim, in_ch, 1, 2, 2]。

    本机两个 Wan 权重实测命中（完整 ckpt 前缀是 model.diffusion_model.，
    单独的 fp8 UNet 没有前缀，所以这里按「结尾名 + 形状」认，不按前缀）。
    dim 下界取 1024：Wan 1.3B 是 1536、14B 是 5120；太小的 dim 是别的模型，别误判。
    """
    for k, v in head.items():
        if not k.endswith("patch_embedding.weight") or not isinstance(v, dict):
            continue
        s = v.get("shape") or []
        if len(s) == 5 and tuple(int(x) for x in s[2:]) == (1, 2, 2) \
                and 1024 <= int(s[0]) <= 16384 and 4 <= int(s[1]) <= 128:
            return True
    return False


def meta_resolution(meta):
    """作者写在 __metadata__ 里的训练分辨率。

    返回 (w, h, 来源说明, 训练桶列表)。没有 → (None, None, None, [])。
    认三种写法：
      · ss_resolution / modelspec.resolution 等直接写的 "1024, 1024" / "(768, 768)" / "1024x1024"
      · ss_bucket_info（kohya 的分桶训练）→ 用得最多的那个桶
    """
    if not meta:
        return None, None, None, []
    for k in _META_RES_KEYS:
        v = meta.get(k)
        if v in (None, ""):
            continue
        xs = [x for x in _ints(v) if 64 <= x <= 8192]
        if len(xs) >= 2:
            return xs[0], xs[1], k, []
        if len(xs) == 1:
            return xs[0], xs[0], k + "（只写了边长）", []
    raw = meta.get("ss_bucket_info")
    if raw:
        try:
            j = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            j = None
        rows = []
        buckets = (j or {}).get("buckets") if isinstance(j, dict) else None
        for ars in (buckets or {}).values():
            if not isinstance(ars, dict):
                continue
            for row in ars.values():
                if isinstance(row, (list, tuple)) and len(row) == 3:
                    try:
                        cnt, w, h = int(row[0]), int(row[1]), int(row[2])
                    except Exception:
                        continue
                    if 64 <= w <= 8192 and 64 <= h <= 8192:
                        rows.append((cnt, w, h))
        if rows:
            rows.sort(key=lambda r: (-r[0], -(r[1] * r[2])))
            cnt, w, h = rows[0]
            return w, h, "ss_bucket_info（训练桶里用得最多的那个：%d 张）" % cnt, rows[:12]
    return None, None, None, []


def probe_path(path):
    """按张量名前缀 / 形状 + 元数据判断这份权重里有什么、是哪一族、训练分辨率多少。"""
    st = os.stat(path)
    hit = _CACHE.get(path)
    if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        return hit[2]
    head, meta = read_header(path)
    keys = list(head.keys())
    arch = detect_arch(head)
    name, fw, fh, fwhy = FAMILY.get(arch, FAMILY["unknown"])
    tw, th, tsrc, buckets = meta_resolution(meta)
    from_file = bool(tw and th)
    if from_file:
        res_w, res_h = tw, th
        res_src = "file"
        res_why = "模型文件里写了训练分辨率（" + str(tsrc) + "）"
    elif fw and fh:
        res_w, res_h = fw, fh
        res_src = "family"
        res_why = fwhy + "（按模型结构判定：" + name + "，文件里没写训练分辨率）"
    else:
        res_w = res_h = None
        res_src = "none"
        res_why = "这份文件里没有扩散主干 / 也没写分辨率，面板按模型名兜底"
    has_te = any(k.startswith(_TE_PREFIX) for k in keys)
    has_vae = any(k.startswith(_VAE_PREFIX) for k in keys)
    # T5 / umt5 这类纯文本编码器里也有 encoder.block.*，别被当成 VAE（civitai 那批常见）
    if has_vae and any(k.startswith(("encoder.block.", "spiece_model", "shared.",
                                     "logit_scale", "transformer.")) for k in keys):
        has_vae = False
    res = {
        "known": True,
        "file": os.path.basename(path),
        "size": st.st_size,
        "keys": len(keys),
        "has_te": has_te,
        "has_vae": has_vae,
        "has_dit": any(k.startswith(_DIT_PREFIX) for k in keys),
        "is_anima": any("llm_adapter" in k for k in keys),
        "arch": arch,
        "arch_label": name,
        "train_res": [tw, th] if from_file else None,
        "train_res_src": tsrc,
        "res": [res_w, res_h] if res_w else None,
        "res_src": res_src,
        "res_why": res_why,
        "buckets": [[w, h, c] for (c, w, h) in buckets],
        "meta_keys": sorted(meta.keys())[:24],
    }
    _CACHE[path] = (st.st_mtime_ns, st.st_size, res)
    return res


def probe(name, folders=FOLDERS):
    """面板调的入口：给个文件名，回它自带什么。任何异常都变成 known=False。"""
    try:
        path = resolve(name, folders)
    except Exception as e:
        return {"ok": True, "known": False, "name": name, "reason": repr(e)}
    if not path:
        return {"ok": True, "known": False, "name": name, "reason": "no_file"}
    try:
        res = dict(probe_path(path))
    except Exception as e:
        # .gguf / .ckpt / 老格式 safetensors：读不了头部就别猜，面板按名字兜底
        return {"ok": True, "known": False, "name": name, "reason": repr(e)}
    res["ok"] = True
    res["name"] = name
    return res
