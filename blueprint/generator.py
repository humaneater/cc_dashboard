# -*- coding: utf-8 -*-
"""生成 ComfyUI 总控台蓝图 -> <ComfyUI>/user/default/workflows/00_总控台.json

结构：
  A 图像共用前端（模型槽 + 图像 LoRA 组 + CLIP 取层 + 提示词 + 文本编码）
  B 文生图   : 文生图子图 -> 姿势(子图) -> 手眼矫正(子图) -> 高清化(子图) -> SaveImage(refined)
  C 图生图   : 取图 -> 图生图精修(子图) -> 手眼矫正(子图#2) -> 高清化(子图#2) -> SaveImage(refine)
  D 视频     : 视频提示词 -> 视频地基(UNET high/low + LoRA组 + CLIP/VAE) -> I2V / FLF2V / T2V

模块与管线全部是 subgraph（双击进入看内部连线），外部只暴露关键参数。

命令行： python tools/gen_dashboard.py [--fresh] [--out 路径]
面板：   点「生成 / 更新蓝图」（走 __init__.py 里的 /cc_dashboard/blueprint 接口）
"""
import json
import os
import sys
import uuid

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_HERE = os.path.dirname(os.path.abspath(__file__))
try:                                       # 作为插件包的一部分被导入
    from ..tools import paths
except ImportError:                        # 直接运行 / 被 tools 下的脚本导入
    if os.path.dirname(_HERE) not in sys.path:
        sys.path.insert(0, os.path.dirname(_HERE))
    from tools import paths

OUT_PATH = paths.workflow_path()

# --------------------------------------------------------------- constants
POS_PROMPT = ("masterpiece, best quality, amazing quality, very aesthetic, "
              "absurdres, 1girl, solo, detailed face, detailed eyes, "
              "cinematic lighting, depth of field")
NEG_PROMPT = ("lowres, bad anatomy, bad hands, text, error, missing fingers, "
              "extra digit, fewer digits, cropped, worst quality, low quality, "
              "normal quality, jpeg artifacts, signature, watermark, username, "
              "blurry, artist name, nsfw")
VIDEO_POS = ("The camera slowly pushes in, the character turns their head "
             "slightly and blinks naturally, hair and clothes move gently in "
             "the wind, soft cinematic lighting, smooth motion")
VIDEO_NEG = ("色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，"
             "整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，"
             "画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，"
             "静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走")

M_ILLUSTRIOUS = "waiIllustriousSDXL_v170.safetensors"
M_ANIMA = "oneObsession_anima29BV1.safetensors"
M_ANIMA_TE = "qwen_3_06b_base.safetensors"      # ANIMA 文本编码器（Qwen3-0.6B）
# ANIMA 潜空间 = Wan21 那套 16 通道；官方 split_files 里配的是 qwen_image_vae
# （和 wan_2.1_vae 结构一样、权重不同），裸 DiT 模型用这它最稳
M_ANIMA_VAE = "qwen_image_vae.safetensors"
M_WAN_CKPT = "smoothMixWan22I2VT2V_i2vHigh.safetensors"
M_CN_UNION = "diffusion_pytorch_model_promax.safetensors"
M_LLLITE = "anima-lllite-pose-1.safetensors"
M_UPSCALE = "4xUltrasharp_4xUltrasharpV10.pt"
M_RIFE = "rife47.pth"            # RIFE 补帧权重（frame-interpolation base pack 里那份）

# 蓝图版本号：面板靠它一眼看出「画布上这份是不是旧蓝图」。
# 只要改了会影响到出图结果的结构（节点/连线/参数语义），就 +1。
BLUEPRINT_REV = 7
BLUEPRINT_TAG = "external-te-vae-slots"

# 视频后处理默认值：高清化（逐帧放大）→ 补帧（RIFE）
VID_UPSCALE_BATCH = 4        # 每批帧数（0 = 一把梭，81 帧很容易炸显存）
VID_UPSCALE_TILE = 0         # 分块大小，0 = 自动（显存不够自己往下降）

POSE_REF_IMAGE = "ComfyUI_00521_.png"     # ComfyUI/input/
LATEST_OUTPUT = "ComfyUI_00626_.png"      # ComfyUI/output/
SAMPLE_IMAGE = "example.png"

WAN_HIGH = "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors"
WAN_LOW = "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors"
WAN_LORA_HIGH = "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors"
WAN_LORA_LOW = "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors"
WAN_CLIP = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
WAN_VAE = "wan_2.1_vae.safetensors"

SEED_IMG = 123456789
SEED_VIDEO = 246813579
SEED_T2I = 111111111111111
SEED_UPSCALE = 778899001

LORA_ROWS = 8            # 面板默认显示的 LoRA 行数（可增删，改这里即可扩展）
PROMPT_SLOTS = 8         # 每组提示词的段数（YogurtStringConcat 上限 8）
PROMPT_SEP = ", "        # 段与段之间的分隔符
# 负面提示词：一个整体多行文本框，不分段、不接插件开关（正面那套分段照旧）
SINGLE_PROMPT = (105, 402)

NOTE_TYPES = ("MarkdownNote", "Note")


# ------------------------------------------------------------- graph model
def sock(name, stype, widget=None, label=None):
    d = {"localized_name": label or name, "name": name, "type": stype}
    if widget:
        d["widget"] = {"name": widget}
    d["link"] = None
    return d


def out_sock(name, otype):
    return {"localized_name": name, "name": name, "type": otype, "links": None}


class Graph(object):
    """Small builder for one graph scope (root graph or a subgraph)."""

    def __init__(self, is_root=False):
        self.is_root = is_root
        self.nodes = []
        self.links = []
        self.order = 0
        self.link_id = 0
        self.sg_inputs = []      # exposed inputs  (subgraph only)
        self.sg_outputs = []     # exposed outputs (subgraph only)
        self.groups = []

    # -- nodes ------------------------------------------------------------
    def add(self, nid, ntype, pos, size, widgets=None, title=None, mode=0,
            inputs=None, outputs=None, props=None, wconvert=None):
        """wconvert: [(input_name, type, label)] -> widget promoted to input."""
        ins = [sock(n, t) for n, t in (inputs or [])]
        for name, stype, label in (wconvert or []):
            ins.append(sock(name, stype, widget=name, label=label))
        node = {
            "id": nid,
            "type": ntype,
            "pos": [int(pos[0]), int(pos[1])],
            "size": [int(size[0]), int(size[1])],
            "flags": {},
            "order": self.order,
            "mode": mode,
            "inputs": ins,
            "outputs": [out_sock(n, t) for n, t in (outputs or [])],
            "properties": props if props is not None else
                          {"cnr_id": "comfy-core", "Node name for S&R": ntype},
        }
        self.order += 1
        if title:
            node["title"] = title
        if widgets is not None:
            node["widgets_values"] = widgets
        self.nodes.append(node)
        return node

    def byid(self, nid):
        for n in self.nodes:
            if n["id"] == nid:
                return n
        raise KeyError("no node %s" % nid)

    def slot(self, nid, name):
        node = self.byid(nid)
        for i, s in enumerate(node["inputs"]):
            if s["name"] == name:
                return node, i
        raise KeyError("no input %s.%s" % (nid, name))

    # -- links ------------------------------------------------------------
    def connect(self, src, sslot, dst, dslot):
        sn, dn = self.byid(src), self.byid(dst)
        sname = sn["outputs"][sslot]["name"]
        dname = dn["inputs"][dslot]["name"]
        stype, dtype = sn["outputs"][sslot]["type"], dn["inputs"][dslot]["type"]
        if dtype != stype:
            raise RuntimeError("type mismatch %s.%s(%s) <- %s.%s(%s)"
                               % (dst, dname, dtype, src, sname, stype))
        if dn["inputs"][dslot]["link"] is not None:
            raise RuntimeError("%s.%s already linked" % (dst, dname))
        self.link_id += 1
        lid = self.link_id
        if self.is_root:
            self.links.append([lid, src, sslot, dst, dslot, stype])
        else:
            self.links.append({"id": lid, "origin_id": src, "origin_slot": sslot,
                               "target_id": dst, "target_slot": dslot,
                               "type": stype})
        if sn["outputs"][sslot]["links"] is None:
            sn["outputs"][sslot]["links"] = []
        sn["outputs"][sslot]["links"].append(lid)
        dn["inputs"][dslot]["link"] = lid
        return lid

    def connect_named(self, src, sslot, dst, input_name):
        node, slot = self.slot(dst, input_name)
        return self.connect(src, sslot, dst, slot)

    # -- subgraph io ------------------------------------------------------
    def expose_in_many(self, targets, exposed=None, label=None, default=None):
        """把一个子图输入扇出到多个内部输入（如三级 FaceDetailer 的 model）。

        targets: [(node_id, input_name), ...]
        """
        k = len(self.sg_inputs)
        first = None
        lids, names = [], []
        for nid, input_name in targets:
            node, slot = self.slot(nid, input_name)
            target = node["inputs"][slot]
            if target["link"] is not None:
                raise RuntimeError("%s.%s already linked" % (nid, input_name))
            self.link_id += 1
            lid = self.link_id
            self.links.append({"id": lid, "origin_id": -10, "origin_slot": k,
                               "target_id": nid, "target_slot": slot,
                               "type": target["type"]})
            target["link"] = lid
            lids.append(lid)
            names.append((nid, input_name, target))
            first = first or (nid, input_name, target)
        nid0, name0, t0 = first
        wname = (t0.get("widget") or {}).get("name")
        for nid, input_name, target in names[1:]:
            if target["type"] != t0["type"]:
                raise RuntimeError("扇出类型不一致 %s/%s" % (nid, input_name))
        self.sg_inputs.append({
            "id": str(uuid.uuid4()),
            "name": exposed or name0,
            "type": t0["type"],
            "linkIds": lids,
            "localized_name": label or exposed or name0,
            "pos": [-200, 100 + k * 40],
            "default": default,
            "_widget": bool(wname),
            "_proxy": [str(nid0), wname] if wname else None,
        })
        return k

    def expose_in(self, nid, input_name, exposed=None, label=None, default=None):
        return self.expose_in_many([(nid, input_name)], exposed, label, default)

    def expose_out(self, nid, output_name, exposed=None, label=None, slot=None):
        node = self.byid(nid)
        if slot is None:
            for i, s in enumerate(node["outputs"]):
                if s["name"] == output_name:
                    slot = i
                    break
        if slot is None:
            raise KeyError("no output %s.%s" % (nid, output_name))
        k = len(self.sg_outputs)
        self.link_id += 1
        lid = self.link_id
        stype = node["outputs"][slot]["type"]
        self.links.append({"id": lid, "origin_id": nid, "origin_slot": slot,
                           "target_id": -20, "target_slot": k, "type": stype})
        self.sg_outputs.append({
            "id": str(uuid.uuid4()),
            "name": exposed or output_name,
            "type": stype,
            "linkIds": [lid],
            "localized_name": label or exposed or output_name,
            "pos": [1400, 100 + k * 40],
        })
        return k

    def to_subgraph(self, sg_id, name, category="总控台", description=""):
        clean_ins = [{k: v for k, v in s.items()
                      if k not in ("default", "_widget", "_proxy")}
                     for s in self.sg_inputs]
        clean_outs = [{k: v for k, v in s.items() if k != "default"}
                      for s in self.sg_outputs]
        return {
            "id": sg_id,
            "version": 1,
            "state": {
                "lastGroupId": 0,
                "lastNodeId": max([n["id"] for n in self.nodes] or [0]),
                "lastLinkId": self.link_id,
                "lastRerouteId": 0,
            },
            "revision": 0,
            "config": {},
            "name": name,
            "inputNode": {"id": -10, "bounding": [-320, 60, 120, 60]},
            "outputNode": {"id": -20, "bounding": [1500, 60, 120, 60]},
            "inputs": clean_ins,
            "outputs": clean_outs,
            "widgets": [],
            "nodes": self.nodes,
            "groups": [],
            "links": self.links,
            "extra": {"workflowRendererVersion": "LG"},
            "category": category,
            "description": description,
        }

    def outer(self, sg_id, pos, size, title=None, mode=0, role=None, key=None,
              extra_props=None):
        """Build the outer node that instantiates this subgraph in the root."""
        props = {"proxyWidgets": [], "cnr_id": "comfy-core",
                 "Node name for S&R": title or sg_id}
        if role:
            props["cc_dock_role"] = role
        if key:
            props["cc_dock_key"] = key
        if extra_props:
            props.update(extra_props)
        node = {
            "id": 0,
            "type": sg_id,
            "pos": [int(pos[0]), int(pos[1])],
            "size": [int(size[0]), int(size[1])],
            "flags": {},
            "order": 0,
            "mode": mode,
            "inputs": [],
            "outputs": [],
            "properties": props,
            "widgets_values": [],
        }
        if title:
            node["title"] = title
        for s in self.sg_inputs:
            entry = {"localized_name": s.get("localized_name"),
                     "name": s["name"], "type": s["type"], "link": None}
            if s.get("_widget"):
                entry["widget"] = {"name": s["name"]}
            node["inputs"].append(entry)
            if s.get("_proxy"):
                props["proxyWidgets"].append(list(s["_proxy"]))
        for s in self.sg_outputs:
            node["outputs"].append({"localized_name": s.get("localized_name"),
                                    "name": s["name"], "type": s["type"],
                                    "links": []})
        return node


# --------------------------------------------------------------- widget kits
def fd_widgets(tune, seed):
    """widgets_values for Impact Pack FaceDetailer (29 widgets)."""
    return [tune["guide"], True, FD_MAX_SIZE, seed, "randomize",
            FD_STEPS, FD_CFG, FD_SAMPLER, FD_SCHEDULER,
            tune["denoise"], tune["feather"], True, True,
            tune["thr"], FD_DILATION, tune["crop"], "center-1", 0, 0.93, 0, 0.7,
            "False", tune["drop"], "", 1, False, FD_NOISE_MASK_FEATHER, False, False]


# ------------------------------------------------------- 高清 / 分块精修参数
# 分块大小：跟着「精修那一刻的分辨率」走，目标是长边切成 2 块（块越少越整体）。
# 精修时的图 = 原图 × 倍数，所以分块要按这个尺寸算，而不是写死 1024。
# 上下限按 SDXL 的显存 / 效果折中：1024 以下块太碎，1536 以上单块太吃显存。
TILE_MIN, TILE_MAX, TILE_STEP = 1024, 1536, 64


def auto_tile_size(w, h, factor, step=TILE_STEP, lo=TILE_MIN, hi=TILE_MAX):
    long_side = max(float(w) * float(factor), float(h) * float(factor))
    t = int(round((long_side / 2.0) / step) * step)
    return int(max(lo, min(hi, t)))


# 默认画布 1216×832、倍数 2 → 精修时 2432×1664 → 分块 1216（宽正好 2 块）
DEFAULT_TILE = auto_tile_size(1216, 832, 2.0)

# 「拼图感」的根源就是下面这组值：分块重绘时每块各画各的，接缝又没修。
# 现在的取向是「先稳后细」：
#   1) 分块重绘强度压低（0.12），每块只加细节、不改内容；
#   2) 接缝修复开着（Half Tile + Intersections），块与块之间再糊一遍；
#   3) 分块之前先整体低强度细化一次（整体细化节点，见 sg_upscale）。
USDU_DEFAULTS = {
    "seed": 778899001,
    "steps": 15,
    "cfg": 4.5,
    "sampler_name": "dpmpp_2m",
    "scheduler": "karras",
    "denoise": 0.12,
    "mode_type": "Linear",
    "tile_width": DEFAULT_TILE,
    "tile_height": DEFAULT_TILE,
    "mask_blur": 16,
    "tile_padding": 48,
    "seam_fix_mode": "Half Tile + Intersections",
    "seam_fix_denoise": 0.30,
    "seam_fix_width": 64,
    "seam_fix_mask_blur": 16,
    "seam_fix_padding": 24,
    "force_uniform_tiles": True,
    "tiled_decode": False,
    "batch_size": 1,
}
# 前端给「seed 这类带 control_after_generate 的 INT」在后面插一个控制 widget
USDU_WIDGET_ORDER = (
    ["seed", "control_after_generate"] + [k for k in USDU_DEFAULTS
                                          if k != "seed"])
USDU_PROMOTED = ("denoise", "seam_fix_denoise")


def usdu_widgets(seed=None, **over):
    """UltimateSDUpscaleNoUpscale 的 widgets_values（20 项，顺序按前端）。

    按名字取值再按 USDU_WIDGET_ORDER 摊平，避免以后插件加参数把下标错位。
    """
    vals = dict(USDU_DEFAULTS)
    vals.update(over)
    if seed is not None:
        vals["seed"] = seed
    # 固定种子：USDU 给每个分块用的是同一个 seed，固定住才能重复出同一张，
    # 想换就自己改 seed（分块内部不需要每次换种子）
    vals["control_after_generate"] = "fixed"
    return [vals[k] for k in USDU_WIDGET_ORDER]


def check_usdu_widget_order():
    """拿 _object_info.json 核对 USDU 的 widget 顺序，错位就在生成前喊出来。"""
    path = paths.object_info_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as fh:
            oi = json.load(fh)
    except Exception:
        return []
    defn = oi.get("UltimateSDUpscaleNoUpscale")
    if not defn:
        return []
    want, problems = [], []
    for sec in ("required", "optional"):
        for name, spec in (defn["input"].get(sec) or {}).items():
            opts = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
            if opts.get("forceInput") or opts.get("hidden"):
                continue
            t = spec[0]
            if not (isinstance(t, list) or t in
                    ("INT", "FLOAT", "STRING", "BOOLEAN")):
                continue
            want.append(name)
            if t == "INT" and (name in ("seed", "noise_seed")
                               or "control_after_generate" in opts):
                want.append("control_after_generate")
    if want and want != list(USDU_WIDGET_ORDER):
        problems.append("USDU widget 顺序对不上：\n  定义 %s\n  代码 %s"
                        % (want, list(USDU_WIDGET_ORDER)))
    return problems


DETECTORS = ["bbox/face_yolov8m.pt", "bbox/hand_yolov8s.pt", "bbox/Eyes.pt"]
# 三级 FaceDetailer 的定型参数（v6.5 重调，全部围绕「别把画面修烂、别把人脸贴错地方」）：
#   guide   ：采样时把裁剪区放大到的尺寸（按检测框短边算）。
#             256（老 SD1.5 配方）在 1024 级模型上会画出栅格 / 网状纹理；
#             1024 又太大 —— Impact 的算法是 upscale = guide / 检测框短边，
#             一张 1024 图里的脸只有 300~500px，等于把这块放大 2~5 倍再采样，
#             模型就会在裁剪区里画一张「完整的大脸 + 头发 + 肩膀」，缩回去贴到原处 →
#             看起来就是「脸被贴到身上 / 身体拼成两截」。512（Impact 自己的默认）才是甜点。
#   denoise ：重绘强度，越低越安全。0.2~0.25 = 只修不重画；0.4 以上会改内容。
#   feather ：遮罩羽化。5 太硬，块的边一眼可见；24 起糊得自然。
#   crop    ：裁剪范围 = 检测框 × 这个倍数。3.0 等于把半个头都重画一遍，2.0 又太紧（缺上下文），取 2.5。
#   drop    ：小于这个像素的检测框直接丢掉（眼那级最容易在头发上冒出一堆假眼，所以要更大）。
#   thr     ：该级自己的检测置信度阈值。手那级最容易在肢体交叠处误检，所以不再放宽到 0.5 以下。
DETAILER_TUNE = [
    dict(label="脸", guide=512, denoise=0.25, feather=24, crop=2.5, drop=10, thr=0.55),
    dict(label="手", guide=512, denoise=0.25, feather=24, crop=2.5, drop=10, thr=0.55),
    dict(label="眼", guide=384, denoise=0.20, feather=24, crop=2.5, drop=24, thr=0.70),
]
# 面板上的三级开关（脸 / 手 / 眼）认这三个 key，对应子图里 11 / 12 / 13 三个
# FaceDetailer；关掉的那一级走「旁路」（mode 4），图从 image 口直接穿过去，
# 链子不断、也不会白跑一次采样。全关 = 整个矫正模块等于没开。
DETAILER_STAGE_KEYS = ["face", "hand", "eye"]
# detailer 的 cfg 原来是 8.0：脸和眼会被推得过饱和、发红，还容易长噪点。
# 统一降到 4.5（和 ANIMA 采样预设一致），采样器换成跟主采样一样的 dpmpp_2m + karras。
FD_CFG = 4.5
FD_STEPS = 20
FD_SAMPLER = "dpmpp_2m"
FD_SCHEDULER = "karras"
FD_MAX_SIZE = 1024          # 裁剪区放大后的上限（长边）；太大 = 模型在小脸上画大肖像
FD_DILATION = 8
FD_NOISE_MASK_FEATHER = 20
# 遮罩形状：没有 SAM 时 Impact 的遮罩就是「检测框矩形」（羽化一下贴回去），
# 所以肢体交叠的构图上容易看见方块贴痕；挂上 SAM 让遮罩跟着轮廓走。
SAM_MODEL = "sam_vit_b_01ec64.pth"   # models/sams/，由 Impact-Subpack 的 SAMLoader 读取
SEED_FD = (445566778, 556677889, 667788990)


# -------------------------------------------------------- 图像：文生图子图
def sg_t2i(g):
    g.add(1, "EmptyLatentImage", (80, 80), (320, 130), [1216, 832, 1],
          title="画布尺寸",
          outputs=[("LATENT", "LATENT")],
          wconvert=[("width", "INT", "宽"), ("height", "INT", "高")])
    g.add(2, "KSampler", (480, 80), (310, 300),
          [SEED_IMG, "randomize", 28, 5.5, "dpmpp_2m", "karras", 1.0],
          title="采样",
          inputs=[("model", "MODEL"), ("positive", "CONDITIONING"),
                  ("negative", "CONDITIONING"), ("latent_image", "LATENT")],
          outputs=[("LATENT", "LATENT")],
          wconvert=[("seed", "INT", "种子"), ("steps", "INT", "步数"),
                    ("cfg", "FLOAT", "CFG")])
    g.add(3, "VAEDecode", (880, 80), (240, 80), inputs=[("samples", "LATENT"),
                                                        ("vae", "VAE")],
          outputs=[("IMAGE", "IMAGE")])
    g.connect(1, 0, 2, 3)
    g.connect(2, 0, 3, 0)
    g.expose_in(2, "model", "model")
    g.expose_in(2, "positive", "positive")
    g.expose_in(2, "negative", "negative")
    g.expose_in(3, "vae", "vae")
    g.expose_in(1, "width", "width", "宽", 1216)
    g.expose_in(1, "height", "height", "高", 832)
    g.expose_in(2, "seed", "seed", "种子", SEED_IMG)
    g.expose_in(2, "steps", "steps", "步数", 28)
    g.expose_in(2, "cfg", "cfg", "CFG", 5.5)
    g.expose_out(3, "IMAGE", "image")


# ---------------------------------------------------- 图像：图生图精修子图
def sg_i2i(g):
    g.add(1, "VAEEncode", (80, 80), (240, 80),
          inputs=[("pixels", "IMAGE"), ("vae", "VAE")],
          outputs=[("LATENT", "LATENT")])
    g.add(2, "KSampler", (420, 80), (310, 300),
          [SEED_IMG, "randomize", 28, 5.5, "dpmpp_2m", "karras", 0.5],
          title="精修采样",
          inputs=[("model", "MODEL"), ("positive", "CONDITIONING"),
                  ("negative", "CONDITIONING"), ("latent_image", "LATENT")],
          outputs=[("LATENT", "LATENT")],
          wconvert=[("seed", "INT", "种子"), ("steps", "INT", "步数"),
                    ("cfg", "FLOAT", "CFG"), ("denoise", "FLOAT", "重绘强度")])
    g.add(3, "VAEDecode", (820, 80), (240, 80),
          inputs=[("samples", "LATENT"), ("vae", "VAE")],
          outputs=[("IMAGE", "IMAGE")])
    g.connect(1, 0, 2, 3)
    g.connect(2, 0, 3, 0)
    g.expose_in(1, "pixels", "source_image", "源图")
    g.expose_in(1, "vae", "vae_encode")
    g.expose_in(3, "vae", "vae_decode")
    g.expose_in(2, "model", "model")
    g.expose_in(2, "positive", "positive")
    g.expose_in(2, "negative", "negative")
    g.expose_in(2, "seed", "seed", "种子", SEED_IMG)
    g.expose_in(2, "steps", "steps", "步数", 28)
    g.expose_in(2, "cfg", "cfg", "CFG", 5.5)
    g.expose_in(2, "denoise", "denoise", "重绘强度", 0.5)
    g.expose_out(3, "IMAGE", "image")


# -------------------------------------- 图像：图生图（固定分辨率）子图
def sg_i2i_fit(g):
    """P 图向的图生图：先把源图缩到面板分辨率（等比 + 中心裁剪），再走
    VAE 编码 / 重绘 / 解码。输出尺寸永远等于面板上的宽 × 高，不是原图尺寸。"""
    g.add(1, "ImageScale", (80, 80), (330, 150),
          ["lanczos", 1216, 832, "center"],
          title="缩放到固定分辨率（中心裁剪）",
          inputs=[("image", "IMAGE")],
          outputs=[("IMAGE", "IMAGE")],
          wconvert=[("width", "INT", "宽"), ("height", "INT", "高")])
    g.add(2, "VAEEncode", (500, 80), (240, 80),
          inputs=[("pixels", "IMAGE"), ("vae", "VAE")],
          outputs=[("LATENT", "LATENT")])
    g.add(3, "KSampler", (820, 80), (310, 300),
          [SEED_IMG, "randomize", 28, 5.5, "dpmpp_2m", "karras", 0.5],
          title="图生图采样",
          inputs=[("model", "MODEL"), ("positive", "CONDITIONING"),
                  ("negative", "CONDITIONING"), ("latent_image", "LATENT")],
          outputs=[("LATENT", "LATENT")],
          wconvert=[("seed", "INT", "种子"), ("steps", "INT", "步数"),
                    ("cfg", "FLOAT", "CFG"), ("denoise", "FLOAT", "重绘强度")])
    g.add(4, "VAEDecode", (1220, 80), (240, 80),
          inputs=[("samples", "LATENT"), ("vae", "VAE")],
          outputs=[("IMAGE", "IMAGE")])
    g.connect(1, 0, 2, 0)
    g.connect(2, 0, 3, 3)
    g.connect(3, 0, 4, 0)
    g.expose_in(1, "image", "source_image", "源图")
    g.expose_in(1, "width", "width", "宽", 1216)
    g.expose_in(1, "height", "height", "高", 832)
    g.expose_in(2, "vae", "vae_encode")
    g.expose_in(4, "vae", "vae_decode")
    g.expose_in(3, "model", "model")
    g.expose_in(3, "positive", "positive")
    g.expose_in(3, "negative", "negative")
    g.expose_in(3, "seed", "seed", "种子", SEED_IMG)
    g.expose_in(3, "steps", "steps", "步数", 28)
    g.expose_in(3, "cfg", "cfg", "CFG", 5.5)
    g.expose_in(3, "denoise", "denoise", "重绘强度", 0.5)
    g.expose_out(4, "IMAGE", "image")


# ------------------------------------------------------- 模块：姿势 · SDXL
def sg_pose_sdxl(g):
    g.add(1, "ControlNetLoader", (80, 80), (430, 70), [M_CN_UNION],
          title="ControlNet Union Promax",
          outputs=[("CONTROL_NET", "CONTROL_NET")])
    g.add(2, "SetUnionControlNetType", (560, 80), (280, 70), ["openpose"],
          title="类型 openpose",
          inputs=[("control_net", "CONTROL_NET")],
          outputs=[("CONTROL_NET", "CONTROL_NET")])
    g.add(3, "ControlNetApplyAdvanced", (880, 80), (340, 240),
          [0.8, 0.0, 1.0], title="应用姿势",
          inputs=[("positive", "CONDITIONING"), ("negative", "CONDITIONING"),
                  ("control_net", "CONTROL_NET"), ("image", "IMAGE")],
          outputs=[("CONDITIONING", "CONDITIONING"),
                   ("CONDITIONING", "CONDITIONING")],
          wconvert=[("strength", "FLOAT", "姿势强度")])
    g.connect(1, 0, 2, 0)
    g.connect(2, 0, 3, 2)
    g.expose_in(3, "positive", "positive")
    g.expose_in(3, "negative", "negative")
    g.expose_in(3, "image", "pose_image", "姿势骨架")
    g.expose_in(3, "strength", "strength", "姿势强度", 0.8)
    g.expose_out(3, "CONDITIONING", "positive", slot=0)
    g.expose_out(3, "CONDITIONING", "negative", slot=1)


# ------------------------------------------------------ 模块：姿势 · ANIMA
def sg_pose_anima(g):
    g.add(1, "ModelPatchLoader", (80, 80), (430, 70), [M_LLLITE],
          title="Anima LLLite pose patch",
          outputs=[("MODEL_PATCH", "MODEL_PATCH")])
    g.add(2, "AnimaLLLiteApply", (560, 80), (360, 240), [1.0, 0.0, 1.0],
          title="LLLite 应用（软先验）",
          inputs=[("model", "MODEL"), ("model_patch", "MODEL_PATCH"),
                  ("image", "IMAGE")],
          outputs=[("MODEL", "MODEL")],
          wconvert=[("strength", "FLOAT", "姿势强度")])
    g.connect(1, 0, 2, 1)
    g.expose_in(2, "model", "model")
    g.expose_in(2, "image", "pose_image", "姿势骨架")
    g.expose_in(2, "strength", "strength", "姿势强度", 0.8)
    g.expose_out(2, "MODEL", "model")


# ------------------------------------------------------- 模块：脸手眼矫正
def sg_detailer(g):
    for i, name in enumerate(DETECTORS):
        g.add(1 + i, "UltralyticsDetectorProvider", (80, 80 + i * 120),
              (430, 70), [name], title=name.split("/")[-1],
              outputs=[("BBOX_DETECTOR", "BBOX_DETECTOR"),
                       ("SEGM_DETECTOR", "SEGM_DETECTOR")])
    # SAM（可选）：不挂也能跑；挂上以后遮罩跟着人物轮廓走，不再是「检测框矩形」。
    # 面板的「SAM 轮廓遮罩」开关把它在 0（加载）/ 2（静音）之间切：
    # 静音时它不进 prompt，FaceDetailer 的可选输入 sam_model_opt 自动回落成 None。
    g.add(15, "SAMLoader", (80, 80 + 3 * 120), (430, 80),
          [SAM_MODEL, "AUTO"], title="SAM（轮廓遮罩 · 可选）",
          outputs=[("SAM_MODEL", "SAM_MODEL")],
          props=props_for("SAMLoader", "detailer_sam", "sam"))
    for i, tune in enumerate(DETAILER_TUNE):
        g.add(11 + i, "FaceDetailer", (560 + i * 360, 80), (330, 820),
              fd_widgets(tune, SEED_FD[i]),
              title="%s %dpx denoise %.2f cfg %.1f"
                    % (tune["label"], tune["guide"], tune["denoise"], FD_CFG),
              inputs=[("image", "IMAGE"), ("model", "MODEL"),
                      ("clip", "CLIP"), ("vae", "VAE"),
                      ("positive", "CONDITIONING"),
                      ("negative", "CONDITIONING"),
                      ("bbox_detector", "BBOX_DETECTOR"),
                      ("sam_model_opt", "SAM_MODEL")],
              outputs=[("IMAGE", "IMAGE"), ("IMAGE", "IMAGE"),
                       ("IMAGE", "IMAGE"), ("MASK", "MASK"),
                       ("DETAILER_PIPE", "DETAILER_PIPE"),
                       ("IMAGE", "IMAGE")],
              wconvert=[("denoise", "FLOAT", "重绘强度"),
                        ("feather", "INT", "羽化"),
                        ("bbox_threshold", "FLOAT", "检测阈值"),
                        ("guide_size", "FLOAT", "检测框放大尺寸"),
                        ("max_size", "FLOAT", "放大上限"),
                        ("bbox_crop_factor", "FLOAT", "裁剪倍率")],
              props=props_for("FaceDetailer", "detailer_stage",
                              DETAILER_STAGE_KEYS[i]))
    for i in range(3):
        g.connect(1 + i, 0, 11 + i, 6)
        g.connect_named(15, 0, 11 + i, "sam_model_opt")
    g.connect(11, 0, 12, 0)
    g.connect(12, 0, 13, 0)
    # 色彩回正：三轮重绘下来（尤其脸那轮），饱和度和色相会整体飘一点，脸偏红是最常见的。
    # 这里用 KJNodes 的 ColorMatch 把「修完的图」的色彩分布对齐回「修之前的图」——
    # 只动色彩统计，不动结构，所以不会把修好的细节抹掉。
    g.add(14, "ColorMatch", (1680, 80), (330, 200), ["mkl", 1.0, True],
          title="色彩回正（对齐修图前）",
          inputs=[("image_ref", "IMAGE"), ("image_target", "IMAGE")],
          outputs=[("IMAGE", "IMAGE")])
    g.connect(13, 0, 14, 1)
    # 同一个输入图既喂第一级 detailer，又当 ColorMatch 的参考
    g.expose_in_many([(11, "image"), (14, "image_ref")], "image")
    for name in ("model", "clip", "vae", "positive", "negative"):
        g.expose_in_many([(11, name), (12, name), (13, name)], name)
    # 面板上「脸手眼矫正参数」调的这些值：三级各一份重绘强度，
    # 脸 / 手 共用检测阈值，眼单独一个（眼最容易误检，默认更严格）
    g.expose_in(11, "denoise", "denoise_face", "脸重绘强度",
                DETAILER_TUNE[0]["denoise"])
    g.expose_in(12, "denoise", "denoise_hand", "手重绘强度",
                DETAILER_TUNE[1]["denoise"])
    g.expose_in(13, "denoise", "denoise_eye", "眼重绘强度",
                DETAILER_TUNE[2]["denoise"])
    g.expose_in_many([(11, "bbox_threshold"), (12, "bbox_threshold")],
                     "bbox_threshold", "检测阈值（脸 / 手）",
                     DETAILER_TUNE[0]["thr"])
    g.expose_in(13, "bbox_threshold", "bbox_threshold_eye", "眼检测阈值",
                DETAILER_TUNE[2]["thr"])
    g.expose_in_many([(11, "feather"), (12, "feather"), (13, "feather")],
                     "feather", "羽化", DETAILER_TUNE[0]["feather"])
    # v6.5：三级共用的「检测框放大尺寸 / 放大上限 / 裁剪倍率」也放到面板上。
    # guide 从 1024 降到 512 是这版的关键：Impact 的算法是 upscale = guide ÷ 检测框短边，
    # 1024 的图里一张脸只有 300~500px，等于把这块放大 2~5 倍再采样 →
    # 模型会在裁剪区里画「完整的脸 + 头发 + 肩膀」，缩回去贴到原处 = 脸像被贴上去。
    g.expose_in_many([(11, "guide_size"), (12, "guide_size"), (13, "guide_size")],
                     "guide", "检测框放大尺寸", DETAILER_TUNE[0]["guide"])
    g.expose_in_many([(11, "max_size"), (12, "max_size"), (13, "max_size")],
                     "max_size", "放大上限", FD_MAX_SIZE)
    g.expose_in_many([(11, "bbox_crop_factor"), (12, "bbox_crop_factor"),
                      (13, "bbox_crop_factor")],
                     "crop", "裁剪倍率", DETAILER_TUNE[0]["crop"])
    g.expose_out(14, "IMAGE", "image")


# ------------------------------------------------------------- 模块：高清化
def sg_upscale(g):
    # supersample 关掉：CR 的 supersample 是「先放大 8 倍再缩到目标」，
    # 而我们上游本来就是 4x 放大模型的大图，再拉 8 倍纯属白烧显存
    # （2048 → 16384 那一瞬间要几个 G），缩放结果还更糊。
    g.add(2, "CR Upscale Image", (560, 80), (340, 300),
          [M_UPSCALE, "rescale", 2, 1024, "lanczos", "false", 8],
          title="先放大",
          inputs=[("image", "IMAGE")],
          outputs=[("IMAGE", "IMAGE"), ("STRING", "STRING")],
          wconvert=[("rescale_factor", "FLOAT", "倍数")])
    # 整体细化：整张图一次过采样，先把放大后的色彩 / 对比 / 结构拉回一致，
    # 再交给分块精修。这一步是「拼图感」的主要解药之一。
    # cfg 6.0 → 4.5：和主采样预设对齐，cfg 拉太高会把颜色推浓、发红。
    g.add(6, "KSampler", (940, 80), (310, 300),
          [SEED_UPSCALE, "randomize", 12, 4.5, "dpmpp_2m", "karras", 0.12],
          title="整体细化（整图，防拼图感）",
          inputs=[("model", "MODEL"), ("positive", "CONDITIONING"),
                  ("negative", "CONDITIONING"), ("latent_image", "LATENT")],
          outputs=[("LATENT", "LATENT")],
          wconvert=[("denoise", "FLOAT", "整体细化强度")])
    g.add(7, "VAEEncode", (1300, 80), (240, 80),
          inputs=[("pixels", "IMAGE"), ("vae", "VAE")],
          outputs=[("LATENT", "LATENT")], title="整图潜空间")
    g.add(8, "VAEDecode", (1580, 80), (240, 80),
          inputs=[("samples", "LATENT"), ("vae", "VAE")],
          outputs=[("IMAGE", "IMAGE")], title="整体细化 · 解码")
    g.add(3, "UltimateSDUpscaleNoUpscale", (1900, 80), (340, 420),
          usdu_widgets(), title="分块精修",
          inputs=[("upscaled_image", "IMAGE"), ("model", "MODEL"),
                  ("positive", "CONDITIONING"), ("negative", "CONDITIONING"),
                  ("vae", "VAE")],
          outputs=[("IMAGE", "IMAGE")],
          wconvert=[("tile_width", "INT", "分块大小"),
                    ("tile_height", "INT", "分块大小"),
                    ("denoise", "FLOAT", "精修强度"),
                    ("seam_fix_denoise", "FLOAT", "接缝修复强度")])
    # 色彩回正 + 收尾：v6.4 起去掉了原来「再 4xUltrasharp 一次、然后缩回 1/4」那一段——
    # 那一趟会：① 让 4x 放大模型连着跑两遍，把栅格 / 网纹放大成肉眼可见的「网」；
    #            ② 白跑一遍 4 倍算力（放大完立刻又缩回去）；
    #            ③ 让「倍数」到底乘了几倍变得看不懂。
    # 现在分块精修出来的就是最终尺寸（= 原图 × 倍数），只再加一步色彩回正。
    # 参考图取「先放大」的输出：它和精修结果是同一尺寸，且没有被采样过，色彩最接近原图。
    g.add(9, "ColorMatch", (2280, 80), (330, 200), ["mkl", 1.0, True],
          title="色彩回正（对齐精修前）",
          inputs=[("image_ref", "IMAGE"), ("image_target", "IMAGE")],
          outputs=[("IMAGE", "IMAGE")])
    g.connect(2, 0, 9, 0)
    g.connect(3, 0, 9, 1)
    g.connect(2, 0, 7, 0)
    g.connect(7, 0, 6, 3)
    g.connect(6, 0, 8, 0)
    g.connect(8, 0, 3, 0)
    g.expose_in(2, "image", "image")
    # 同一个 model / 条件 / VAE 扇出给「整体细化」和「分块精修」两条路
    g.expose_in_many([(6, "model"), (3, "model")], "model")
    g.expose_in_many([(6, "positive"), (3, "positive")], "positive")
    g.expose_in_many([(6, "negative"), (3, "negative")], "negative")
    g.expose_in_many([(7, "vae"), (8, "vae"), (3, "vae")], "vae")
    g.expose_in(2, "rescale_factor", "factor", "倍数", 2.0)
    # 分块大小：一个参数同时喂 tile_width / tile_height（面板按分辨率自动算）
    g.expose_in_many([(3, "tile_width"), (3, "tile_height")],
                     "tile", "分块大小", DEFAULT_TILE)
    g.expose_in(6, "denoise", "whole_denoise", "整体细化强度", 0.12)
    g.expose_in(3, "denoise", "denoise", "精修强度", 0.12)
    g.expose_in(3, "seam_fix_denoise", "seam_fix_denoise",
                "接缝修复强度", 0.30)
    g.expose_out(9, "IMAGE", "image")


# ------------------------------------------------------- 视频：I2V / FLF2V 骨架
def _sg_wan_video(g, first_last):
    if first_last:
        g.add(1, "WanFirstLastFrameToVideo", (80, 80), (420, 260),
              [640, 640, 81, 1], title="首尾帧 → 视频",
              inputs=[("positive", "CONDITIONING"),
                      ("negative", "CONDITIONING"), ("vae", "VAE"),
                      ("clip_vision_start_image", "CLIP_VISION"),
                      ("clip_vision_end_image", "CLIP_VISION"),
                      ("start_image", "IMAGE"), ("end_image", "IMAGE")],
              outputs=[("CONDITIONING", "CONDITIONING"),
                       ("CONDITIONING", "CONDITIONING"),
                       ("LATENT", "LATENT")],
              wconvert=[("width", "INT", "宽"), ("height", "INT", "高"),
                        ("length", "INT", "帧数")])
    else:
        g.add(1, "WanImageToVideo", (80, 80), (420, 240),
              [640, 640, 81, 1], title="图 → 视频",
              inputs=[("positive", "CONDITIONING"),
                      ("negative", "CONDITIONING"), ("vae", "VAE"),
                      ("clip_vision_output", "CLIP_VISION_OUTPUT"),
                      ("start_image", "IMAGE")],
              outputs=[("CONDITIONING", "CONDITIONING"),
                       ("CONDITIONING", "CONDITIONING"),
                       ("LATENT", "LATENT")],
              wconvert=[("width", "INT", "宽"), ("height", "INT", "高"),
                        ("length", "INT", "帧数")])
    g.add(2, "KSamplerAdvanced", (560, 80), (310, 340),
          ["enable", 111111111111111, "randomize", 4, 1, "euler", "simple",
           0, 2, "enable"], title="high noise 0→2 步",
          inputs=[("model", "MODEL"), ("positive", "CONDITIONING"),
                  ("negative", "CONDITIONING"), ("latent_image", "LATENT")],
          outputs=[("LATENT", "LATENT")],
          wconvert=[("noise_seed", "INT", "种子"), ("steps", "INT", "步数"),
                    ("cfg", "FLOAT", "CFG")])
    g.add(3, "KSamplerAdvanced", (920, 80), (310, 340),
          ["disable", 0, "fixed", 4, 1, "euler", "simple", 2, 10000,
           "disable"], title="low noise 2→",
          inputs=[("model", "MODEL"), ("positive", "CONDITIONING"),
                  ("negative", "CONDITIONING"), ("latent_image", "LATENT")],
          outputs=[("LATENT", "LATENT")],
          wconvert=[("steps", "INT", "步数"), ("cfg", "FLOAT", "CFG")])
    g.add(4, "VAEDecode", (1280, 80), (240, 80),
          inputs=[("samples", "LATENT"), ("vae", "VAE")],
          outputs=[("IMAGE", "IMAGE")])
    g.connect(1, 2, 2, 3)
    g.connect(1, 0, 2, 1)
    g.connect(1, 1, 2, 2)
    g.connect(2, 0, 3, 3)
    g.connect(1, 0, 3, 1)
    g.connect(1, 1, 3, 2)
    g.connect(3, 0, 4, 0)
    # 这里只输出「解出来的帧」，封装成视频文件搬到顶层了：帧要先过
    # 视频高清化 / 视频补帧两个后处理模块，最后才 CreateVideo → SaveVideo。
    g.expose_in(1, "vae", "vae_image")
    if first_last:
        g.expose_in(1, "start_image", "start_image", "首帧")
        g.expose_in(1, "end_image", "end_image", "尾帧")
    else:
        g.expose_in(1, "start_image", "start_image", "源图")
    g.expose_in(4, "vae", "vae_decode")
    g.expose_in(2, "model", "model_high")
    g.expose_in(3, "model", "model_low")
    g.expose_in(1, "positive", "positive")
    g.expose_in(1, "negative", "negative")
    g.expose_in(1, "width", "width", "宽", 640)
    g.expose_in(1, "height", "height", "高", 640)
    g.expose_in(1, "length", "length", "帧数", 81)
    g.expose_in(2, "steps", "steps_high", "步数", 4)
    g.expose_in(3, "steps", "steps_low", "步数", 4)
    g.expose_in(2, "cfg", "cfg_high", "CFG", 1.0)
    g.expose_in(3, "cfg", "cfg_low", "CFG", 1.0)
    g.expose_in(2, "noise_seed", "seed", "种子", 111111111111111)
    g.expose_out(4, "IMAGE", "frames", "帧")


# ------------------------------------------------------------ 视频：文生视频
def sg_t2v(g):
    g.add(1, "CheckpointLoaderSimple", (80, 80), (430, 110), [M_WAN_CKPT],
          title="Wan 合并模型",
          outputs=[("MODEL", "MODEL"), ("CLIP", "CLIP"), ("VAE", "VAE")])
    g.add(2, "ModelSamplingSD3", (560, 80), (300, 70), [5.0],
          inputs=[("model", "MODEL")], outputs=[("MODEL", "MODEL")])
    g.add(3, "EmptyHunyuanLatentVideo", (900, 200), (380, 150),
          [640, 640, 81, 1],
          outputs=[("LATENT", "LATENT")],
          wconvert=[("width", "INT", "宽"), ("height", "INT", "高"),
                    ("length", "INT", "帧数")])
    g.add(4, "KSampler", (1320, 80), (310, 300),
          [SEED_VIDEO, "randomize", 8, 1.0, "euler", "simple", 1.0],
          title="8 步 / CFG 1",
          inputs=[("model", "MODEL"), ("positive", "CONDITIONING"),
                  ("negative", "CONDITIONING"), ("latent_image", "LATENT")],
          outputs=[("LATENT", "LATENT")],
          wconvert=[("seed", "INT", "种子")])
    g.add(5, "VAEDecode", (1680, 80), (240, 80),
          inputs=[("samples", "LATENT"), ("vae", "VAE")],
          outputs=[("IMAGE", "IMAGE")])
    g.connect(1, 0, 2, 0)
    g.connect(2, 0, 4, 0)
    g.connect(3, 0, 4, 3)
    g.connect(4, 0, 5, 0)
    g.connect(1, 2, 5, 1)
    # 同上：封装成视频搬到顶层，这里只给帧
    g.expose_in(4, "positive", "positive")
    g.expose_in(4, "negative", "negative")
    g.expose_in(3, "width", "width", "宽", 640)
    g.expose_in(3, "height", "height", "高", 640)
    g.expose_in(3, "length", "length", "帧数", 81)
    g.expose_in(4, "seed", "seed", "种子", SEED_VIDEO)
    g.expose_out(5, "IMAGE", "frames", "帧")


# ------------------------------------------------------------- subgraph ids
SG_T2I = "0b7a1c10-0001-4a01-9c01-000000000001"
SG_I2I = "0b7a1c10-0001-4a01-9c01-000000000002"
SG_POSE_SDXL = "0b7a1c10-0001-4a01-9c01-000000000003"
SG_POSE_ANIMA = "0b7a1c10-0001-4a01-9c01-000000000004"
SG_DETAILER = "0b7a1c10-0001-4a01-9c01-000000000005"
SG_UPSCALE = "0b7a1c10-0001-4a01-9c01-000000000006"
SG_I2V = "0b7a1c10-0001-4a01-9c01-000000000007"
SG_FLF2V = "0b7a1c10-0001-4a01-9c01-000000000008"
SG_T2V = "0b7a1c10-0001-4a01-9c01-000000000009"
SG_VIDEO_UPSCALE = "0b7a1c10-0001-4a01-9c01-00000000000a"
SG_VFI = "0b7a1c10-0001-4a01-9c01-00000000000b"
SG_I2I_FIT = "0b7a1c10-0001-4a01-9c01-00000000000c"


# ------------------------------------------------- 模块：视频高清化（逐帧放大）
def sg_video_upscale(g):
    """帧序列 → 4x 放大模型 → 缩到目标倍数。

    纯像素操作，不做扩散采样，所以不会像图像高清链那样把颜色带偏，
    也就不需要色彩回正那一步。
    「目标倍数」是相对原始尺寸说的：4x 模型配 2 倍目标，缩回系数 = 2 ÷ 4 = 0.5。
    """
    g.add(1, "UpscaleModelLoader", (80, 80), (430, 70), [M_UPSCALE],
          title="放大模型（4x）", outputs=[("UPSCALE_MODEL", "UPSCALE_MODEL")])
    # 用 whiterabbit 的高级版而不是核心那版：多了 max_batch_size / tile_size
    # 两个保命参数 —— 81 帧一次过放大必定炸显存，所以按批 + 分块走。
    g.add(2, "UpscaleWithModelAdvanced", (560, 80), (360, 240),
          [VID_UPSCALE_BATCH, VID_UPSCALE_TILE, False, "fp32"],
          title="逐帧放大（分批 / 分块）",
          inputs=[("upscale_model", "UPSCALE_MODEL"), ("image", "IMAGE")],
          outputs=[("IMAGE", "IMAGE")],
          wconvert=[("max_batch_size", "INT", "每批帧数"),
                    ("tile_size", "INT", "分块大小（0=自动）")])
    g.add(3, "CM_FloatBinaryOperation JK", (980, 100), (330, 150),
          ["Div", 2.0, 4.0], title="缩放系数 = 目标倍数 ÷ 模型倍率",
          outputs=[("FLOAT", "FLOAT")],
          wconvert=[("a", "FLOAT", "目标倍数"), ("b", "FLOAT", "模型倍率")])
    g.add(4, "ImageScaleBy", (1370, 80), (340, 160), ["lanczos", 0.5],
          title="缩到目标尺寸",
          inputs=[("image", "IMAGE")], outputs=[("IMAGE", "IMAGE")],
          wconvert=[("scale_by", "FLOAT", "缩放系数")])
    g.connect(1, 0, 2, 0)
    g.connect(2, 0, 4, 0)
    g.connect(3, 0, 4, 1)
    g.expose_in(2, "image", "frames", "帧")
    g.expose_in(3, "a", "factor", "目标倍数", 2.0)
    g.expose_in(3, "b", "base", "放大模型倍率", 4.0)
    g.expose_in(2, "max_batch_size", "batch", "每批帧数", VID_UPSCALE_BATCH)
    g.expose_in(2, "tile_size", "tile", "分块大小（0=自动）", VID_UPSCALE_TILE)
    g.expose_out(4, "IMAGE", "frames", "帧")


# ------------------------------------------------------ 模块：视频补帧（RIFE）
def sg_vfi(g):
    """帧序列 → RIFE 插帧，同时把帧率一起乘上去。

    补帧只加中间帧、不改总时长：16fps × 2 → 32fps，回放速度不变。
    fps 的乘法就放在这个子图里，所以模块一关，fps 原样透传（不会变速）。
    """
    g.add(1, "RIFE_VFI_Opt", (80, 80), (400, 300),
          [M_RIFE, 2, 1.0, True, 10], title="RIFE 插帧",
          inputs=[("frames", "IMAGE")], outputs=[("IMAGE", "IMAGE")],
          wconvert=[("multiplier", "INT", "补帧倍数")])
    g.add(2, "CM_FloatBinaryOperation JK", (560, 80), (330, 150),
          ["Mul", 16.0, 2.0], title="帧率 × 倍数（播放速度才不变）",
          outputs=[("FLOAT", "FLOAT")],
          wconvert=[("a", "FLOAT", "帧率"), ("b", "FLOAT", "倍数")])
    g.add(3, "CM_FloatToInt JK", (560, 300), (330, 90), [2],
          title="倍数 → 整数（RIFE 只吃整数）",
          outputs=[("INT", "INT")], wconvert=[("a", "FLOAT", "倍数")])
    g.connect(3, 0, 1, 1)
    # 输出顺序定死：输出[0]=帧(IMAGE) 对齐 输入[0]=帧，输出[1]=帧率(FLOAT)
    # 对齐 输入[1]=帧率 —— 这样面板关掉这个模块时，旁路透传不会串味。
    g.expose_in(1, "frames", "frames", "帧")
    g.expose_in(2, "a", "fps", "帧率", 16.0)
    g.expose_in_many([(2, "b"), (3, "a")], "multiplier", "补帧倍数", 2.0)
    g.expose_out(1, "IMAGE", "frames", "帧")
    g.expose_out(2, "FLOAT", "fps", "帧率")


SUBGRAPH_SPECS = [
    (SG_T2I, "文生图", sg_t2i, "文生图（采样 + 解码）"),
    (SG_I2I, "图生图精修", sg_i2i, "图生图精修（VAE 编码 + 重绘）"),
    (SG_I2I_FIT, "图生图（固定分辨率）", sg_i2i_fit,
     "图生图：缩放到固定分辨率 → 中心裁剪 → 重绘（P 图向）"),
    (SG_POSE_SDXL, "姿势 · SDXL", sg_pose_sdxl, "ControlNet Union + OpenPose"),
    (SG_POSE_ANIMA, "姿势 · ANIMA", sg_pose_anima, "Anima LLLite 姿势软先验"),
    (SG_DETAILER, "脸手眼矫正", sg_detailer,
     "脸 / 手 / 眼 三级 FaceDetailer → 色彩回正"),
    (SG_UPSCALE, "高清化", sg_upscale,
     "放大倍数 → 整体细化 → 分块精修 → 色彩回正（最终 = 原图 × 倍数）"),
    (SG_I2V, "图生视频 I2V", lambda g: _sg_wan_video(g, False),
     "Wan2.2 I2V：high/low 双模型 4 步加速"),
    (SG_FLF2V, "首尾帧 FLF2V", lambda g: _sg_wan_video(g, True),
     "Wan2.2 首尾帧过渡：high/low 双模型 4 步加速"),
    (SG_T2V, "文生视频 T2V", sg_t2v, "Wan 合并模型单次采样"),
    (SG_VIDEO_UPSCALE, "视频高清化", sg_video_upscale,
     "逐帧 4x 放大 → 缩到目标倍数（纯像素操作，不采样、不偏色）"),
    (SG_VFI, "视频补帧", sg_vfi,
     "RIFE 插帧：补中间帧，帧率同步 ×倍数，回放速度不变"),
]

CUSTOM_TYPES = {
    "UltralyticsDetectorProvider", "FaceDetailer", "CR Upscale Image",
    "UltimateSDUpscaleNoUpscale", "OpenposePreprocessor",
    "SAMLoader",
    "Power Lora Loader (rgthree)",
    "CR Clip Input Switch", "CR VAE Input Switch",
    "CR Text Input Switch JK",
    "YogurtStringConcat",
    "RIFE_VFI_Opt", "UpscaleWithModelAdvanced",
    "CM_FloatBinaryOperation JK", "CM_FloatToInt JK",
}


def props_for(ntype, role=None, key=None):
    if ntype in NOTE_TYPES:
        p = {}
    elif ntype in CUSTOM_TYPES:
        p = {"Node name for S&R": ntype}
    else:
        p = {"cnr_id": "comfy-core", "Node name for S&R": ntype}
    if role:
        p["cc_dock_role"] = role
    if key:
        p["cc_dock_key"] = key
    return p


def lora_rows(n=LORA_ROWS, preset=None):
    """rgthree Power Lora Loader 的 widgets_values：一行一个 dict。

    preset: [(lora 文件名, 强度), ...] 从第一行开始预挂（视频 4 步加速 LoRA）。
    """
    rows = [{"lora": "", "on": False, "strength": 1.0} for _ in range(n)]
    for i, (name, strength) in enumerate(preset or []):
        if i < n:
            rows[i] = {"lora": name, "on": True, "strength": strength}
    return rows


def prompt_slots(default=""):
    """YogurtStringConcat 的 widgets_values：

    顺序 = required(separator) + optional(enable1, text1 ... enable8, text8)。
    文本一律留空：每一段的文字实际住在对应的"第 N 段"开关节点里（text_false），
    这样「手填 / 插件输入」才能真二选一；空串会被节点自动跳过。
    """
    wv = [PROMPT_SEP]
    for i in range(PROMPT_SLOTS):
        wv.append(True)
        wv.append("")
    return wv


def add_prompt_group(r, nid, key, title, pos, default="", short=""):
    """一个 8 段提示词组 + 8 个二选一开关，开关输出接回 text<i>（只给正面提示词用）。

    每段一个 CR Text Input Switch JK：
      boolean_value=False            -> 用这一格的手填文字（text_false）
      boolean_value=True + 有连线    -> 用插件（text_true）
      boolean_value=True + 没连线    -> 回落 text_true 里同步的手填文字
    面板上的"插件输入"勾选就是这个布尔值；⌖ 跳转跳到这个开关，
    把插件的 STRING 输出连到它的"插件文本"输入即可。
    """
    base = {104: 141, 401: 461}[nid]
    # 二选一开关摆成 3 列 × 3 行，贴在提示词组右侧。
    # 行列都留足间距：开关节点高 82，行距给 130（余 48px 走线），
    # 列距 380（节点宽 340，余 40px），这样往「插件文本」口连线不会互相压。
    if nid == 104:
        x0, y0 = 1680, 200
    else:
        x0, y0 = 780, 5060
    r.add(nid, "YogurtStringConcat", pos, (620, 300), prompt_slots(default),
          title=title, outputs=[("STRING", "STRING")],
          wconvert=[("text%d" % i, "STRING", "第%d段（镜像）" % i)
                    for i in range(1, PROMPT_SLOTS + 1)],
          props=props_for("YogurtStringConcat", "prompt", key))
    for i in range(PROMPT_SLOTS):
        col, row = divmod(i, 3)
        hand = default if i == 0 else ""
        r.add(base + i, "CR Text Input Switch JK",
              (x0 + col * 400, y0 + row * 130), (340, 82), [False, hand, hand],
              title="%s · 第 %d 段（手填 / 插件）" % (short or title, i + 1),
              outputs=[("STRING", "STRING"), ("BOOLEAN", "BOOLEAN")],
              wconvert=[("text_true", "STRING", "插件文本")],
              props=props_for("CR Text Input Switch JK"))
        r.connect_named(base + i, 0, nid, "text%d" % (i + 1))


def add_prompt_box(r, nid, key, title, pos, default=""):
    """负面提示词：一个普通多行文本框（PrimitiveStringMultiline）。

    不分段、不合并、不带插件开关——就是一格，写完直接进 CLIPTextEncode。
    """
    r.add(nid, "PrimitiveStringMultiline", pos, (620, 300), [default],
          title=title, outputs=[("STRING", "STRING")],
          wconvert=[("value", "STRING", "文本")],
          props=props_for("PrimitiveStringMultiline", "prompt", key))


HELP_DETAILER = """## 脸手眼矫正：三级独立开关 + 参数对照（面板 → 画布 → 子图）

模块内部是三级：**脸 → 手 → 眼**（脸那级顺手修眼睛和嘴）。v6.5 起三级各有
一个开关，「参数 → 脸手眼矫正参数」最上面那排勾就能单独开关：

| 面板开关 | 对应子图里的节点 | 关掉会怎样 |
|---|---|---|
| 脸 | 脸 FaceDetailer（子图节点 11） | 图直接从这一级穿过去，不检测、不重绘 |
| 手 | 手 FaceDetailer（子图节点 12） | 同上（手那级最容易在肢体交叠处误检） |
| 眼 | 眼 FaceDetailer（子图节点 13） | 同上（眼那级最容易在头发 / 花纹上冒假眼） |
| SAM 轮廓遮罩 | SAMLoader（子图节点 15） | 不加载 SAM，遮罩回到「检测框矩形」 |

只留「脸」是最安全的组合：脸的检测器最准，手 / 眼那两级用的
`hand_yolov8s.pt` / `Eyes.pt` 在多人交叠、复杂花纹的构图上容易误检，
误检一小块再按 0.3 以上重画，出来的就是「画面里凭空长出一条多余的胳膊」。

关掉的级走的是**旁路**（bypass），不是删节点：图从 `image` 口直接穿过去，
链路不断、也不会白跑一次采样。三个全关 = 整个矫正模块等于没开。

### 参数对照

| 面板上的名字 | 子图里的输入口 | 作用对象 |
|---|---|---|
| 检测阈值 `0.55` | `bbox_threshold` | 脸 / 手 两级的检测置信度 |
| 眼检测阈值 `0.70` | `bbox_threshold_eye` | 眼那级自己的阈值（默认更严） |
| 羽化 `24` | `feather` | **三级共用**的遮罩边缘柔化（像素） |
| 脸重绘 `0.25` | `denoise_face` | 「脸 512px denoise 0.25 cfg 4.5」那级 |
| 手重绘 `0.25` | `denoise_hand` | 「手 512px denoise 0.25 cfg 4.5」那级 |
| 眼重绘 `0.20` | `denoise_eye` | 「眼 384px denoise 0.20 cfg 4.5」那级 |
| 检测框放大尺寸 `512` | `guide` | **三级共用**：检测框送去采样时放大到多大（短边） |
| 放大上限 `1024` | `max_size` | 放大后的长边上限，防止极端比例把这块撑爆 |
| 裁剪倍率 `2.5` | `crop` | 裁剪范围 = 检测框 × 这个倍数 |

双击画布上的「脸手眼矫正」子图进去看：三个 FaceDetailer 上都有
`重绘强度 / 羽化 / 检测阈值 / 检测框放大尺寸 / 放大上限 / 裁剪倍率` 输入口，
面板写的就是它们；最后一级后面还挂着 **色彩回正（ColorMatch）**，
把三级重绘后的色调拉回修图前的样子。
文生图和图生图共用同一份子图定义，所以参数和开关调一次两边都变。

### 默认值参考

| 参数 | 默认 | 常用范围 | 怎么调 |
|---|---|---|---|
| 检测阈值（脸 / 手） | 0.55 | 0.45 ~ 0.70 | 漏检手就往下调（0.45 左右）；误检太多就往上调 |
| 眼检测阈值 | 0.70 | 0.55 ~ 0.85 | **眼睛那级最容易在头发 / 花纹上误检**，误检一来就是一片假眼，所以默认比脸严格 |
| 羽化 | 24 | 16 ~ 40 | 边缘出现方块拼接痕就往上加；加到 40 还看得见块，就把那一级的重绘强度降下来 |
| 脸重绘 | 0.25 | 0.15 ~ 0.35 | 高了会改长相、角色跑偏；低了修不动脏脸 |
| 手重绘 | 0.25 | 0.15 ~ 0.35 | 手崩得厉害再往上加，0.50 以上很容易多指 / 畸形 |
| 眼重绘 | 0.20 | 0.15 ~ 0.30 | 眼睛小，太高会糊成一块 |
| 检测框放大尺寸 | 512 | 384 ~ 768 | Impact 自己的默认值。往上加 = 那块被放大更多，模型在裁剪区里画得越「完整」（脸带头发肩膀），缩回去就越像贴上去 |
| 放大上限 | 1024 | 768 ~ 1536 | 只有极端宽高比的检测框会碰到它；碰不到就不用管 |
| 裁剪倍率 | 2.5 | 2.0 ~ 3.5 | 裁剪范围。3.5 会把半个头都重画一遍，2.0 太紧（缺上下文） |

### v6.5 修了什么（「被错误当成脸重画 / 长出多余的肢体」）

怪图的成因是下面几件事叠在一起，现在逐个拆掉了：

1. **手那级 denoise 0.6** —— `hand_yolov8s` 在肢体交叠处误检一小块，再按 0.6 重画，
   那一块就长出多余的肢体。现在三级统一压到 0.20 ~ 0.25（只修不重画）。
2. **guide 1024** —— Impact 的算法是 `放大倍数 = guide ÷ 检测框短边`，1024 的图里
   一张脸只有 300~500px，等于把这块放大 2~5 倍再采样，模型就会在裁剪区里画
   「完整的脸 + 头发 + 肩膀」，缩回去贴到原处 —— 看起来就是「脸被贴到身上」。
   现在 guide 回到 **512**（Impact 自己的默认值）、max_size 收到 1024。
3. **没有 SAM** —— 遮罩就是检测框矩形，羽化一下贴回去，边界一眼可见。
   现在默认接上 SAM（`models/sams/sam_vit_b_01ec64.pth`），遮罩跟着人物轮廓走；
   不想用就在面板上把「SAM 轮廓遮罩」取消，那一级回到矩形遮罩。
4. **底模 / 提示词冲突** —— `1girl, solo` 配多人交叠的构图时，脸那级会按
   「单人」重画一块，跟旁边的角色打架。这种图直接把三级关掉、或者只留脸。

> 真遇到「越修越烂」的排查顺序：先把三级重绘强度都降到 0.2 左右，还不行就
> 逐级关（先关手和眼、只留脸），再不行把整个模块关掉对比 —— 面板上都能单点。
> 参数页右上角有「↺ 重置默认值」，一键回到上面那张表。
"""


HELP_UPSCALE = """## 高清化：为什么以前会「像很多张拼起来」，现在怎么调

### 原因（旧参数）

旧流程是「放大 2x → 直接把 2432×1664 切成 6 块（1024×1024）各自重绘」：

1. **接缝修复关着**（`seam_fix_mode = None`）——块与块边界各画各的，没有任何糊合；
2. **分块重绘强度 0.2 偏高**——每块都能自由改内容，块与块之间的理解会跑偏；
3. **CFG 7.0 + ddim**——每块各自被提示词拉满，块与块更容易长歪；
4. 遮罩羽化 32 却只留 16 像素重叠，**羽化比重叠还大**，边界反而更花。

四件事叠一起，出来就是拼图感。

### 现在的高清链

    放大「倍数」x → 整体细化（整图一次过，0.12）→ 分块精修（自动分块 + 0.12 + 接缝修复）
            → 色彩回正（对齐精修前）

新增的**整体细化**是把整张图当成一张图先低强度过一遍采样，
把放大后的色彩 / 对比 / 结构先拉回一致，再交给分块精修 —— 这是消除拼图感的关键一步。
分块精修同时改成：`dpmpp_2m + karras`、CFG 4.5、重叠 48、遮罩羽化 16、
**接缝修复 = Half Tile + Intersections（0.30）**。

### v6.4：为什么又去掉了一段

原来分块精修后面还挂着「再 4xUltrasharp 一次 → 缩回 1/4」。它有三个问题：

1. **4x 放大模型连着跑两遍**（开头「先放大」一遍、结尾又一遍）——
   模型会把上一级采样留下的细栅格放大成肉眼可见的**网状纹理**，这是「画面被修烂」的放大器；
2. 白跑一遍 4 倍算力：放到 4 倍立刻又缩回去，显存和时间都白花；
3. 让「倍数」到底乘了几倍变得看不懂。

现在**分块精修出来的就是最终尺寸**，后面只加一步 **色彩回正（ColorMatch, mkl）**：
拿「先放大、还没精修」的那张当参考，只把色彩分布对标回去 —— 不动结构，
专门治「修完偏红 / 饱和度变高」。最终尺寸还是 **原图 × 倍数**。

### 倍数 / 分块怎么算

- **「高清倍数」= 最终尺寸 ÷ 原图尺寸**。填 2 就是 1216×832 → 2432×1664。
  链子里只有一次放大（「先放大」那步，按这个倍数走），所以**填几就是几倍**。
- **分块大小自动跟着分辨率走**：精修那一刻的图是「原图 × 倍数」，
  分块 = 这个尺寸的长边 ÷ 2（再对齐 64、限制在 1024~1536）。
  例：1216×832、倍数 2 → 精修 2432×1664 → 分块 1216（宽正好 2 块）。
  块越少越整体；想手动钉住就把面板上的「自动」取消，自己填分块大小。
  *分块大小是这一块里唯一「自动」的参数；下面几个强度都是你自己调、面板不会覆盖。*

### 面板「高清参数」四个值怎么调

| 面板上的名字 | 默认 | 常用范围 | 怎么调 |
|---|---|---|---|
| 高清倍数 | 2 | 1.5 ~ 2 | **最终**放大比例（原图 × 这个数）。整个高清链的性能大头 |
| 分块大小 | 自动 | 1024 ~ 1536 | 自动 = 精修分辨率的长边切 2 块；手动调小更省显存、但块多 |
| 整体细化强度 | 0.12 | 0.08 ~ 0.20 | **拼图感第一嫌疑人**：越高越容易改内容；先往 0.10 降 |
| 分块精修强度 | 0.12 | 0.08 ~ 0.20 | 分块加细节的力度；块感明显就降到 0.08~0.10 |
| 接缝修复强度 | 0.30 | 0.20 ~ 0.45 | 块与块之间的糊合力度；缝还在就加到 0.35~0.40 |

> 三个强度都是「只加细节、不改内容」的取向。加起来越高越吃时间；
> 想快就把高清化模块整个关掉（旁路），或者把高清倍数降到 1.5。
>
> 还是觉得块感重：先把两个强度降到 0.08~0.10、把接缝修复加到 0.40，
> 再把分块手动调大（上限 1536）——块数更少、更整体，代价是显存和时间。
"""


HELP = """## ComfyUI 总控台 v6

### 怎么用

**面板是悬浮窗**，不随画布平移缩放：拖标题栏移动、拖边/角改大小，位置尺寸自动记住，
挡住东西就往旁边一拖；顶栏右侧三个按钮管窗口本身：

- **⧉**：变成独立小窗口（Chrome / Edge 支持），可以拖到另一个屏幕上，关掉自动收回页面
- **📌**：钉回窗口顶部通栏（旧版的样子），再点一下恢复浮动
- **◎**：跟随执行，**默认开**——跑图时自动切进正在执行的子图并聚焦那个节点；自己拖画布时会先让一让

- **管线**：文生图 / 图生图精修 / 图生图 / 图生视频 / 首尾帧 / 文生视频，点一个切一个
  - **图生图精修**：在源图的原始分辨率上继续重绘，不改变尺寸，用来微调已经满意的图
  - **图生图**：先把源图缩到面板分辨率（等比缩放 + 中心裁剪，不变形）再重绘，
    输出尺寸永远等于面板上选的宽 × 高，适合 P 图 / 统一出图尺寸；
    两条图生图共用同一套模型、提示词、LoRA 和重绘强度，区别只在「改不改尺寸」
  切完之后，面板下面只显示这条管线用得上的东西：图像管线给图像提示词 + 图像参数 + 图像 LoRA，
  视频管线的三兄弟给视频提示词 + 视频参数 + 视频 high/low LoRA，模块按钮也跟着换；不用自己找
- **模型**：下拉即换 checkpoint，Illustrious / ANIMA 都在这里切；
  选到 ANIMA 会自动变成 30 步 / CFG 4.5 / 不走 CLIP 取层 / 姿势换成 LLLite，
  并把 CLIP、VAE 切到外挂那两路（Qwen3-0.6B 文本编码器 + Qwen-Image VAE）
- **外挂资源**（模型下面那一行）：**面板自己读模型头部**判断这个 ckpt 自带不带文本编码器 / VAE ——
  - 自带 → 这一行收起来，不用管；想强行换成外挂（比如给 SDXL 换 `sdxlVAE`）点右边的 `🛠 外挂` 展开
  - 不带（ANIMA 那类只有 `model.diffusion_model.*` 的裸 DiT）→ 自动出现，缺哪项显示哪项，
    并先填好 `qwen_3_06b_base.safetensors` + `qwen_image_vae.safetensors`，不满意直接在下拉里换；
    选谁就写进画布 110 / 111，同时把 112 / 113 两个来源开关切到外挂
  - 每个模型名记住你选过的那份，切回来自动还原；下拉里是 `models/text_encoders`、
    `models/vae` 的全部文件，新丢进去的文件点 `⟳` 就能看到（不用重启）
  - 读不到头部（`.gguf` / `.ckpt` / 接口还没重启）→ 退回按名字判断：名字含 anima 就当外挂，
    其它当自带；出图不受影响
- **模块**：图像那边是 姿势 / 脸手眼矫正 / 高清化；视频那边是 视频高清化 / 视频补帧，
  切到哪条管线就显示哪几个，随时开关。姿势开关按当前模型族自动选 SDXL 或 ANIMA 那套

面板右上角有四个页签，点开才展开，不占地方：

- **提示词**：按管线只显示当前那两组（图像正 / 图像负，或视频正 / 视频负）
  - **正向 = 8 段拼接**：每段一行 `#N` + 文本框 + `插件输入` + `启用` + `⌖ 跳转`，
    右边是这段现在吃的是手填还是插件
  - **负向 = 一个整体文本框**：不分段、不合并、没有插件开关，写完直接进编码
  - **拼接**（只对正向）：8 段按顺序用分隔符（默认 `, `）拼成一条，空段自动跳过，所以没写满也不会有多余逗号；
    分隔符在最上面那格，可以改
  - **自动扩展**：一开始只露 3 行，你在哪一段写了字或者挂了插件，下面就自动多冒一行；最多 8 段。
    想一次看全就点这组右上角的 `全部 8 段`；顶到头了会提示——真要更多，就在画布上再加一个拼接节点串上去
  - **插件输入（手填 / 插件 二选一）**：勾上就是「这段听插件的」，点名框变灰、忽略手填；不勾就是「这段听我手写的」
    （真的二选一：每段在画布上是一个 `CR Text Input Switch JK` 开关节点，插件的 STRING 输出接它的
    「插件文本」口，开关的布尔值由面板控制；勾着插件但还没接线时会回落到手填文字，不会把这段变空）
  - **⌖ 跳转**：点一下直接切到那一段的开关节点并放大居中——你在那儿把插件输出连上（比如 scene-composer 的
    `environment` / `character` / `action` / `positive` / `negative` 的 `prompt` 口），回来勾上「插件输入」就能用。
    没连线的会显示 `插件：未连线`，照着提示去连一下
  - 每段的文字保存在「第 N 段（手填 / 插件）」节点上；拼接器节点里那 8 格是**只读镜像**，只为在画布上瞄一眼
- **LoRA**：图像组给文生图 / 图生图精修 / 图生图共用；视频组给 I2V / FLF2V 的 high、low 两条链共用。
  每行一个开关 + 一个下拉 + 强度，下面还有一行状态：
  - `触发词: …` — 从 LoRA 元数据里读出来的训练触发词，**要锁角色/画风就把这词写进提示词**，不写的话很多时候看着像没生效
  - `⚠ 已选但未启用` — 选了 LoRA 但左边开关没勾，后端会直接跳过这个 LoRA，勾上再出图
  - `⚠ 与当前模型族可能不匹配` — 比如当前是 ANIMA 模型却挂了 Illustrious 的 LoRA（或反过来），换了多半不出效果
  - 行数跟画布节点一致，在画布节点上点 “➕ Add Lora” 加行，面板自动跟上。
    视频组第一行默认挂着 `lightx2v_4steps` 加速 LoRA（4 步 / CFG 1 的配方要它），不用就在面板上关掉
- **参数**：按模块分区，**模块开着才显示那一块**（关掉模块那块自动收起来）
  - **生成参数**：宽 / 高 / 步数 / CFG / 种子 + 🎲 随机；`重绘强度` 只在两条图生图管线里出现
    （图生图精修 = 原分辨率重绘；图生图 = 缩到固定分辨率后重绘）。
    「高」右边那个 **⇄** 是长宽一键互换（1216×832 ↔ 832×1216）：想要竖图点一下就行，
    视频那条也有自己的一个，两边互不影响
  - **姿势参数**：姿势强度（姿势模块开着才有）
  - **脸手眼矫正参数**：检测阈值（脸 / 手）/ 眼检测阈值 / 羽化 / 脸·手·眼三级重绘强度
    （脸手眼矫正模块开着才有）。检测阈值调低 = 更容易认出脸和手；
    眼那级单独一个阈值，是因为眼睛最容易在头发和花纹上误检；
    羽化是遮罩边缘的柔化像素；三级重绘是各自的修复力度。
    三级后面还挂着一道**色彩回正**，专门治「修完偏红 / 饱和度变高」
  - **高清参数**：高清倍数 / 分块大小（带「自动」开关）/ 整体细化强度 / 分块精修强度 / 接缝修复强度
    （高清化模块开着才有），底下两个只读行写着 **输出尺寸** / **实际分块**，不用自己算。
    「高清倍数」是**最终尺寸 ÷ 原图尺寸**，填 2 就是 2 倍（以前填 2 出来是 4 倍，v6.3 起修好了）。
    分块大小是这块里**唯一自动**的参数，其余几个强度你自己调，面板不会覆盖，
    而且改了会记在浏览器里，刷新页面 / 重开工作流都还在
    出图「像很多张拼起来」时先降分块精修强度、再降整体细化强度；接缝修复强度管块与块之间的糊合。
    分块默认**自动跟着分辨率走**（精修尺寸的长边切 2 块，对齐 64、限 1024~1536），
    取消「自动」就能自己钉一个固定值
  - **视频参数**：宽 / 高 / 帧数 / 帧率 / 步数 / CFG / 种子 + 🎲 随机
  - **视频补帧参数**（补帧模块开着才有）：`补帧倍数`——2 = 相邻两帧之间插 1 帧
    （帧数 ×2、帧率也 ×2，**播放速度不变**）；4 = 插 3 帧。16fps 的 81 帧 →×2 变 161 帧 / 32fps。
    底下那行只读提示会算出补完的帧数 / 帧率。源素材本身糊的地方补完还是糊，常规 2 倍就够
  - **视频高清参数**（视频高清化模块开着才有）：`目标倍数`是**相对原始尺寸**说的，
    填 2 就是 640×640 → 1280×1280；`放大模型倍率`跟磁盘上那个放大模型对齐（4xUltrasharp 就是 4），
    换 2x 模型时改成 2，缩放系数会自动按「目标 ÷ 模型倍率」重算；`每批帧数`是显存保险丝
    （一次放大太多帧会炸，默认 4）；`分块大小`填 0 = 自动，显存不够就填 256 / 384 往下压。
    整条链是「先整帧放大、再缩到目标尺寸」，中间那层大图很吃内存，嫌慢就把目标倍数降到 1.5
  - **🎲 随机（默认开）**：开着每张图 / 每段视频都是新种子；关掉就按下面那个数字出，方便微调。
    这个开关是「这次打开页面」的事，刷新后回到默认开，不记进浏览器里
  - 旁边那个 **🎲 按钮**是「只随机这一次」，点一下换个种子，不动上面的开关
- **说明**：就是本页要点

顶栏还有两个按钮：`⟳ 取图`（重新拉 `output/` 图片清单，把最新那张填进**当前管线**的取图节点）、
`↻ 同步`（按旁边 `▾` 选的来源取图：上次结果 / 历史选择 / 自定义 / 视频尾帧 —— 先写当前管线
自己的取图节点（图生图精修 / 图生图 / 图生视频 / 首尾帧），再往下游传；写完节点里的预览图跟着换）。

> 面板没出现？确认 `custom_nodes/cc_dashboard/web/dock.js` 在（插件装好）+ 刷新浏览器页面。
> 想重新生成这份蓝图：面板「说明」页点「生成 / 更新蓝图」，或跑 `python tools/gen_dashboard.py`。
> 面板跑到屏幕外了？`📌` 钉回顶部即可拉回来。
> 实在不想用面板，也可以直接框选节点按 `Ctrl+B` 旁路 / `Ctrl+M` 静音，效果一样。

### 画布结构（双击子图进去看内部连线）

```
[图像共用前端] 模型槽 → 图像 LoRA 组 → CLIP 取层 → 文本编码
        ↓
[文生图]  文生图 → 姿势 → 脸手眼矫正 → 高清化 → output/refined_*
[图生图精修]  取图 → 原分辨率重绘 → 脸手眼矫正 → 高清化 → output/refine_*
[图生图]      取图 → 缩到固定分辨率（等比 + 中心裁剪）→ 采样 → 脸手眼矫正 → 高清化
                  → output/i2ifixed_*
[视频]    视频提示词 → 视频地基（UNET high/low + LoRA 组）→ I2V / FLF2V / T2V
              → 视频高清化 → 视频补帧 → 封装 → output/video/total_*
```

- 文生图和两条图生图**共用**模型槽、提示词、LoRA 组
- **模型分两套**：面板顶栏的「图像模型」就是 101 模型槽（Illustrious / ANIMA / 任意 ckpt，管文生图 + 两条图生图）；
  「视频模型」是 406 / 407 那一对加载器（high noise / low noise，管 I2V / FLF2V / T2V）：
  safetensors 走 `UNETLoader`、GGUF 走 `UnetLoaderGGUF`，面板按文件后缀自己换，下游连线不动。
  Wan 2.2 这类模型是「两个专家」拼出来的，high 管前几步、low 管后几步，两个都要对；
  面板里勾着「⇄ 成对」时改一个会自动把另一个换成配对的（`high_noise` ↔ `low_noise`、
  `highQ80` ↔ `lowQ80`、`Q8H` ↔ `Q8L` 这些写法都认；另一半不在清单里就不动），
  两边的族名对不上会在面板上直接提示。切到视频管线就只看得到视频模型，图像管线只看得到图像模型。
  视频模型那一行下面还有一条「外挂资源」：视频模型是**分离式**的，UNETLoader 只给模型本体，
  文本编码器（403，默认 `umt5_xxl_fp8_e4m3fn_scaled.safetensors`）和 VAE（412，默认 `wan_2.1_vae.safetensors`）
  必须外挂，同样在下拉里换文件
- 提示词是「一处来源」：面板上的正向 8 段拼完再分发给文生图 / 图生图精修 / 图生图（负向就是一个单框，视频那套同理），
  不是每个模型各写一份
- 取图节点在画布上是可见的：图生图精修 / 图生图 / I2V / 首尾帧都用 `output/` 里的图，刷新列表即可选到上一轮出的图
- 管线切换是「静音其它 Save 节点」，不会白跑别的管线
- 模块关掉靠旁路透传，不会断线也不会报错
- 视频后处理（高清化 / 补帧）在三条视频管线上各挂了一份，默认关着；
  链子顺序是 **视频高清化 → 视频补帧**（先放大再补帧：同样一遍 4x 放大，
  81 帧比补完的 161 帧省一半时间和显存），两个都关掉就直接输出原始帧

### 其它

- 采样步数 / CFG / 尺寸 / 种子 / 重绘强度 / 高清倍数都在面板参数区，也可以直接改画布上的参数节点；
  种子节点上的控制项（`randomize` / `fixed`）就是面板那个 🎲 随机开关写的，两边是同一个东西
- 视频的 4 步是加速 LoRA 绑定的，想改步数就双击进 I2V / FLF2V 子图改
- ANIMA 的裸 DiT（只含 `model.diffusion_model.*`，没有文本编码器 / VAE）已经接好了：
  A2 区 `110 CLIPLoader` + `111 VAELoader` 补料，`112 / 113` 两个开关切「ckpt 自带 / 外挂」；
  面板顶栏的「外挂资源」行就是改这两个 loader 的文件，面板没加载时手动把这两个开关设成 `2` 即可。
  两份官方文件：`models/text_encoders/qwen_3_06b_base.safetensors`（1137 MB，Qwen3-0.6B）
  与 `models/vae/qwen_image_vae.safetensors`（242 MB）；官方仓库 `circlestone-labs/Anima`
  的 `split_files/` 里就是这两份，国内可以用 `hf-mirror.com` 或 ModelScope 下
- 想接 Krea2 这类分离式权重：同样按 A2 区的接法，换成它自己的 `UNETLoader` + `CLIPLoader` + `VAELoader`
- IPAdapter 参考图需求已删除（无节点、无权重）
"""


def build_subgraphs():
    subs, builders = [], {}
    for sg_id, name, fn, desc in SUBGRAPH_SPECS:
        g = Graph()
        fn(g)
        builders[sg_id] = g
        subs.append(g.to_subgraph(sg_id, name, description=desc))
    return subs, builders


def enclose(nodes, pad=70):
    x0 = min(n["pos"][0] for n in nodes) - pad
    y0 = min(n["pos"][1] for n in nodes) - pad
    x1 = max(n["pos"][0] + n["size"][0] for n in nodes) + pad
    y1 = max(n["pos"][1] + n["size"][1] for n in nodes) + pad
    return [x0, y0, x1 - x0, y1 - y0]


def build():
    subs, B = build_subgraphs()
    r = Graph(is_root=True)

    def inst(sg_id, nid, pos, size, title, role=None, key=None, mode=0):
        node = B[sg_id].outer(sg_id, pos, size, title=title, mode=mode,
                              role=role, key=key)
        node["id"] = nid
        node["order"] = r.order
        r.order += 1
        r.nodes.append(node)
        return node

    # ---------------------------------------------------- A 图像共用前端
    r.add(101, "CheckpointLoaderSimple", (80, 120), (430, 110),
          [M_ILLUSTRIOUS], title="模型槽（Illustrious / ANIMA / 任意 ckpt）",
          outputs=[("MODEL", "MODEL"), ("CLIP", "CLIP"), ("VAE", "VAE")],
          props=props_for("CheckpointLoaderSimple", "model_slot"))
    r.add(102, "Power Lora Loader (rgthree)", (560, 60), (420, 560),
          lora_rows(), title="图像 LoRA 组（文生图 + 图生图共用）",
          inputs=[("model", "MODEL"), ("clip", "CLIP")],
          outputs=[("MODEL", "MODEL"), ("CLIP", "CLIP")],
          props=props_for("Power Lora Loader (rgthree)", "lora_group", "image"))
    r.add(103, "CLIPSetLastLayer", (1040, 60), (430, 70), [-2],
          title="CLIP 取层 -2（ANIMA 时自动旁路）",
          inputs=[("clip", "CLIP")], outputs=[("CLIP", "CLIP")],
          props=props_for("CLIPSetLastLayer", "preset_sdxl"))
    # 正面：8 段拼接 + 每段一个"手填/插件"二选一开关（CR Text Input Switch JK）
    # 负面：一个整体文本框，不分段不接插件
    add_prompt_group(r, 104, "image_pos", "图像提示词 · 正向（8 段拼接）",
                     (1040, 200), POS_PROMPT, "图像·正向")
    add_prompt_box(r, 105, "image_neg", "图像提示词 · 负向（单框）",
                   (1040, 560), NEG_PROMPT)
    r.add(106, "CLIPTextEncode", (3320, 230), (400, 200), [POS_PROMPT],
          title="正向编码", inputs=[("clip", "CLIP")],
          outputs=[("CONDITIONING", "CONDITIONING")],
          wconvert=[("text", "STRING", "文本")],
          props=props_for("CLIPTextEncode", "clip_encode", "image_pos"))
    r.add(107, "CLIPTextEncode", (3320, 490), (400, 200), [NEG_PROMPT],
          title="负向编码", inputs=[("clip", "CLIP")],
          outputs=[("CONDITIONING", "CONDITIONING")],
          wconvert=[("text", "STRING", "文本")],
          props=props_for("CLIPTextEncode", "clip_encode", "image_neg"))
    r.add(108, "LoadImage", (80, 300), (400, 520), [POSE_REF_IMAGE, "image"],
          title="姿势参考图", outputs=[("IMAGE", "IMAGE"), ("MASK", "MASK")],
          props=props_for("LoadImage", "pose_image"))
    r.add(109, "OpenposePreprocessor", (560, 700), (330, 220),
          ["enable", "enable", "enable", 512, "disable"],
          title="OpenPose（身+手+脸）", inputs=[("image", "IMAGE")],
          outputs=[("IMAGE", "IMAGE"), ("POSE_KEYPOINT", "POSE_KEYPOINT")],
          props=props_for("OpenposePreprocessor"))

    # 外挂资源：裸 DiT（ANIMA 那种只有 model.diffusion_model.* 的）没有文本编码器 /
    # VAE，用这两个 loader 补上，再由 112 / 113 两个开关与 ckpt 自带的那份二选一。
    # 面板顶栏「外挂资源」行直接改这两个文件（role=te_slot / vae_slot）。
    r.add(110, "CLIPLoader", (4380, 140), (560, 90),
          [M_ANIMA_TE, "stable_diffusion", "default"],
          title="文本编码器（外挂 · 裸模型用）",
          outputs=[("CLIP", "CLIP")],
          props=props_for("CLIPLoader", "te_slot", "image"))
    r.add(111, "VAELoader", (4380, 280), (430, 80), [M_ANIMA_VAE],
          title="VAE（外挂 · 裸模型用）", outputs=[("VAE", "VAE")],
          props=props_for("VAELoader", "vae_slot", "image"))
    r.add(112, "CR Clip Input Switch", (4380, 430), (400, 160), [1],
          title="CLIP 来源（1 = ckpt 自带 / 2 = ANIMA）",
          inputs=[("clip1", "CLIP"), ("clip2", "CLIP")],
          outputs=[("CLIP", "CLIP"), ("STRING", "STRING")],
          props=props_for("CR Clip Input Switch", "family", "clip"))
    r.add(113, "CR VAE Input Switch", (4380, 660), (400, 160), [1],
          title="VAE 来源（1 = ckpt 自带 / 2 = ANIMA）",
          inputs=[("VAE1", "VAE"), ("VAE2", "VAE")],
          outputs=[("VAE", "VAE"), ("STRING", "STRING")],
          props=props_for("CR VAE Input Switch", "family", "vae"))

    # 参数节点
    img_params = [
        (121, "PrimitiveInt", "画布宽", "width", 1216, (80, 1000)),
        (122, "PrimitiveInt", "画布高", "height", 832, (420, 1000)),
        (123, "PrimitiveInt", "采样步数", "steps", 28, (760, 1000)),
        (124, "PrimitiveFloat", "CFG", "cfg", 5.5, (1100, 1000)),
        (125, "PrimitiveInt", "种子", "seed", SEED_IMG, (1440, 1000)),
        (126, "PrimitiveFloat", "重绘强度", "denoise", 0.5, (1780, 1000)),
        (127, "PrimitiveFloat", "姿势强度", "pose_strength", 0.8, (80, 1140)),
        (128, "PrimitiveFloat", "高清倍数", "upscale_factor", 2.0,
         (420, 1140)),
        (129, "PrimitiveFloat", "高清 · 分块精修强度", "upscale_denoise", 0.12,
         (760, 1140)),
        (1291, "PrimitiveFloat", "高清 · 接缝修复强度", "upscale_seam_fix",
         0.30, (1100, 1280)),
        (1292, "PrimitiveFloat", "高清 · 整体细化强度", "upscale_whole_denoise",
         0.12, (1440, 1280)),
        (1293, "PrimitiveInt", "高清 · 分块大小（自动跟随分辨率）", "upscale_tile",
         DEFAULT_TILE, (1780, 1280)),
        (130, "PrimitiveFloat", "脸手眼矫正 · 检测阈值（脸 / 手）",
         "detailer_threshold", DETAILER_TUNE[0]["thr"], (760, 1420)),
        (1295, "PrimitiveFloat", "脸手眼矫正 · 眼检测阈值",
         "detailer_threshold_eye", DETAILER_TUNE[2]["thr"], (1100, 1420)),
        (131, "PrimitiveInt", "脸手眼矫正 · 羽化（三级共用）",
         "detailer_feather", DETAILER_TUNE[0]["feather"], (1440, 1420)),
        (132, "PrimitiveFloat", "脸手眼矫正 · 脸重绘（1024px 那级）",
         "detailer_denoise_face", DETAILER_TUNE[0]["denoise"], (1780, 1420)),
        (133, "PrimitiveFloat", "脸手眼矫正 · 手重绘（1024px 那级）",
         "detailer_denoise_hand", DETAILER_TUNE[1]["denoise"], (2120, 1420)),
        (134, "PrimitiveFloat", "脸手眼矫正 · 眼重绘（768px 那级）",
         "detailer_denoise_eye", DETAILER_TUNE[2]["denoise"], (760, 1560)),
        # v6.5：三级的「检测框放大尺寸 / 放大上限 / 裁剪倍率」（三级共用一份值）。
        # 这三个是「画面被修烂 / 脸像被贴上去」的直接旋钮，所以放到面板上。
        (137, "PrimitiveFloat", "脸手眼矫正 · 检测框放大尺寸（三级共用）",
         "detailer_guide", DETAILER_TUNE[0]["guide"], (1100, 1560)),
        (138, "PrimitiveFloat", "脸手眼矫正 · 放大上限（长边）",
         "detailer_max_size", FD_MAX_SIZE, (1440, 1560)),
        (139, "PrimitiveFloat", "脸手眼矫正 · 裁剪倍率（检测框 × N）",
         "detailer_crop", DETAILER_TUNE[0]["crop"], (1780, 1560)),
    ]
    for nid, ntype, title, key, val, pos in img_params:
        # 种子节点第二个 widget 是 control_after_generate：默认随机
        # PrimitiveInt 自带 control_after_generate 控件（前端会补），所以整型参数都写两位：
        # 种子默认 randomize（面板的「🎲 随机」开关就写这一格），其它保持 fixed。
        if ntype == "PrimitiveInt":
            wv = [val, "randomize" if key in ("seed", "video_seed") else "fixed"]
        else:
            wv = [val]
        r.add(nid, ntype, pos, (300, 60), wv, title=title,
              outputs=[("INT" if ntype == "PrimitiveInt" else "FLOAT",
                        "INT" if ntype == "PrimitiveInt" else "FLOAT")],
              props=props_for(ntype, "param", key))

    # ------------------------------------------------------------- B 文生图
    inst(SG_T2I, 201, (100, 1800), (470, 470), "文生图",
         role="pipeline", key="t2i")
    inst(SG_POSE_SDXL, 202, (660, 1800), (410, 300), "姿势 · SDXL",
         role="module", key="pose_sdxl", mode=4)
    inst(SG_POSE_ANIMA, 203, (660, 2180), (410, 270), "姿势 · ANIMA",
         role="module", key="pose_anima", mode=4)
    inst(SG_DETAILER, 204, (1160, 1800), (430, 430), "脸手眼矫正",
         role="module", key="detailer", mode=4)
    inst(SG_UPSCALE, 205, (1680, 1800), (450, 450), "高清化",
         role="module", key="upscale", mode=4)
    r.add(206, "SaveImage", (2220, 1770), (490, 700), ["refined"],
          title="出图 refined_*", inputs=[("images", "IMAGE")],
          props=props_for("SaveImage", "save", "t2i"))

    # --------------------------------------------------------- C 图生图精修
    r.add(301, "LoadImageOutput", (100, 3600), (400, 520),
          [LATEST_OUTPUT + " [output]", "image", "refresh", "image"],
          title="取图（output 里的图）",
          outputs=[("IMAGE", "IMAGE"), ("MASK", "MASK")],
          props=props_for("LoadImageOutput", "source_image", "i2i"))
    inst(SG_I2I, 302, (600, 3600), (490, 530), "图生图精修",
         role="pipeline", key="i2i")
    inst(SG_DETAILER, 303, (1180, 3600), (430, 430), "脸手眼矫正",
         role="module", key="detailer", mode=4)
    inst(SG_UPSCALE, 304, (1700, 3600), (450, 450), "高清化",
         role="module", key="upscale", mode=4)
    r.add(305, "SaveImage", (2240, 3570), (490, 700), ["refine"],
           title="出图 refine_*", inputs=[("images", "IMAGE")], mode=2,
           props=props_for("SaveImage", "save", "i2i"))

    # ------------------------------- C2 图生图（固定分辨率，P 图向）
    r.add(311, "LoadImageOutput", (100, 4400), (400, 520),
          [LATEST_OUTPUT + " [output]", "image", "refresh", "image"],
          title="取图（output 里的图）",
          outputs=[("IMAGE", "IMAGE"), ("MASK", "MASK")],
          props=props_for("LoadImageOutput", "source_image", "i2i_fixed"))
    inst(SG_I2I_FIT, 312, (600, 4400), (540, 560), "图生图（固定分辨率）",
         role="pipeline", key="i2i_fixed")
    inst(SG_DETAILER, 313, (1220, 4400), (430, 430), "脸手眼矫正",
         role="module", key="detailer", mode=4)
    inst(SG_UPSCALE, 314, (1740, 4400), (450, 450), "高清化",
         role="module", key="upscale", mode=4)
    r.add(315, "SaveImage", (2280, 4370), (490, 700), ["i2ifixed"],
          title="出图 i2ifixed_*", inputs=[("images", "IMAGE")], mode=2,
          props=props_for("SaveImage", "save", "i2i_fixed"))

    # --------------------------------------------------------------- D 视频
    add_prompt_group(r, 401, "video_pos", "视频提示词 · 正向（8 段拼接）",
                     (100, 5200), VIDEO_POS, "视频·正向")
    add_prompt_box(r, 402, "video_neg", "视频提示词 · 负向（单框）",
                   (100, 5560), VIDEO_NEG)
    r.add(403, "CLIPLoader", (2600, 6060), (600, 90),
          [WAN_CLIP, "wan", "default"], title="Wan 文本编码器",
          outputs=[("CLIP", "CLIP")],
          props=props_for("CLIPLoader", "te_slot", "video"))
    r.add(404, "CLIPTextEncode", (2600, 6200), (500, 200), [VIDEO_POS],
          title="视频正向编码", inputs=[("clip", "CLIP")],
          outputs=[("CONDITIONING", "CONDITIONING")],
          wconvert=[("text", "STRING", "文本")],
          props=props_for("CLIPTextEncode", "clip_encode", "video_pos"))
    r.add(405, "CLIPTextEncode", (2600, 6460), (500, 210), [VIDEO_NEG],
          title="视频负向编码", inputs=[("clip", "CLIP")],
          outputs=[("CONDITIONING", "CONDITIONING")],
          wconvert=[("text", "STRING", "文本")],
          props=props_for("CLIPTextEncode", "clip_encode", "video_neg"))
    r.add(406, "UNETLoader", (100, 5920), (430, 80), [WAN_HIGH, "default"],
          title="Wan high noise", outputs=[("MODEL", "MODEL")],
          props=props_for("UNETLoader", "unet_slot", "video_high"))
    r.add(407, "UNETLoader", (100, 6040), (430, 80), [WAN_LOW, "default"],
          title="Wan low noise", outputs=[("MODEL", "MODEL")],
          props=props_for("UNETLoader", "unet_slot", "video_low"))
    r.add(408, "Power Lora Loader (rgthree)", (580, 5920), (420, 520),
          lora_rows(preset=[(WAN_LORA_HIGH, 1.0)]),
          title="视频 LoRA 组 · high（I2V / FLF2V 共用）",
          inputs=[("model", "MODEL"), ("clip", "CLIP")],
          outputs=[("MODEL", "MODEL"), ("CLIP", "CLIP")],
          props=props_for("Power Lora Loader (rgthree)", "lora_group",
                          "video_high"))
    r.add(409, "Power Lora Loader (rgthree)", (1040, 5920), (420, 520),
          lora_rows(preset=[(WAN_LORA_LOW, 1.0)]),
          title="视频 LoRA 组 · low（I2V / FLF2V 共用）",
          inputs=[("model", "MODEL"), ("clip", "CLIP")],
          outputs=[("MODEL", "MODEL"), ("CLIP", "CLIP")],
          props=props_for("Power Lora Loader (rgthree)", "lora_group",
                          "video_low"))
    r.add(410, "ModelSamplingSD3", (1500, 5920), (300, 70), [5.0],
          title="采样偏移 high", inputs=[("model", "MODEL")],
          outputs=[("MODEL", "MODEL")], props=props_for("ModelSamplingSD3"))
    r.add(411, "ModelSamplingSD3", (1500, 6050), (300, 70), [5.0],
          title="采样偏移 low", inputs=[("model", "MODEL")],
          outputs=[("MODEL", "MODEL")], props=props_for("ModelSamplingSD3"))
    r.add(412, "VAELoader", (1840, 5920), (430, 80), [WAN_VAE],
          title="Wan VAE", outputs=[("VAE", "VAE")],
          props=props_for("VAELoader", "vae_slot", "video"))
    r.add(413, "LoadImageOutput", (100, 6500), (400, 520),
          [LATEST_OUTPUT + " [output]", "image", "refresh", "image"],
          title="I2V 取图（output 里的图）",
          outputs=[("IMAGE", "IMAGE"), ("MASK", "MASK")],
          props=props_for("LoadImageOutput", "source_image", "i2v"))
    # FLF 的首尾帧也走 output 池：这样「同步输出图」才能把刚出的图传过来
    r.add(414, "LoadImageOutput", (580, 6500), (400, 520),
          [LATEST_OUTPUT + " [output]", "image", "refresh", "image"],
          title="FLF 首帧（output 里的图）",
          outputs=[("IMAGE", "IMAGE"), ("MASK", "MASK")],
          props=props_for("LoadImageOutput", "source_image", "flf_start"))
    r.add(415, "LoadImageOutput", (1040, 6500), (400, 520),
          [LATEST_OUTPUT + " [output]", "image", "refresh", "image"],
          title="FLF 尾帧（output 里的图）",
          outputs=[("IMAGE", "IMAGE"), ("MASK", "MASK")],
          props=props_for("LoadImageOutput", "source_image", "flf_end"))

    vid_params = [
        (421, "PrimitiveInt", "视频宽", "video_width", 640, (100, 7120)),
        (422, "PrimitiveInt", "视频高", "video_height", 640, (440, 7120)),
        (423, "PrimitiveInt", "视频帧数", "video_length", 81, (780, 7120)),
        (424, "PrimitiveFloat", "视频帧率", "video_fps", 16.0, (1120, 7120)),
        (425, "PrimitiveInt", "视频步数", "video_steps", 4, (1460, 7120)),
        (426, "PrimitiveFloat", "视频 CFG", "video_cfg", 1.0, (1800, 7120)),
        (427, "PrimitiveInt", "视频种子", "video_seed", SEED_VIDEO,
         (2140, 7120)),
        # 视频后处理（v6.6）：高清化 → 补帧。默认都旁路，面板上点开才跑。
        (481, "PrimitiveFloat", "补帧 · 倍数", "vfi_multiplier", 2.0,
         (100, 7240)),
        (482, "PrimitiveFloat", "视频高清 · 目标倍数（相对原尺寸）",
         "video_upscale_factor", 2.0, (440, 7240)),
        (483, "PrimitiveFloat", "视频高清 · 放大模型倍率（换模型才要改）",
         "video_upscale_base", 4.0, (780, 7240)),
        (484, "PrimitiveInt", "视频高清 · 每批帧数（0 = 不限制）",
         "video_upscale_batch", VID_UPSCALE_BATCH, (1120, 7240)),
        (485, "PrimitiveInt", "视频高清 · 分块大小（0 = 自动）",
         "video_upscale_tile", VID_UPSCALE_TILE, (1460, 7240)),
    ]
    for nid, ntype, title, key, val, pos in vid_params:
        if ntype == "PrimitiveInt":
            wv = [val, "randomize" if key in ("seed", "video_seed") else "fixed"]
        else:
            wv = [val]
        r.add(nid, ntype, pos, (300, 60), wv, title=title,
              outputs=[("INT" if ntype == "PrimitiveInt" else "FLOAT",
                        "INT" if ntype == "PrimitiveInt" else "FLOAT")],
              props=props_for(ntype, "param", key))

    # 三条视频管线各挂一套后处理：视频高清化 → 视频补帧 → 封装 → 存盘。
    # 一行一条管线，互不干扰；两个模块默认旁路（mode=4），要用就在面板上点开。
    vid_rows = [
        (SG_I2V, 431, 492, 491, 497, 432, "i2v", 7340, 550,
         "图生视频 I2V", "video/total_i2v", "出视频 i2v"),
        (SG_FLF2V, 441, 494, 493, 498, 442, "flf2v", 7900, 590,
         "首尾帧过渡 FLF2V", "video/total_flf2v", "出视频 flf2v"),
        (SG_T2V, 451, 496, 495, 499, 452, "t2v", 8460, 550,
         "文生视频 T2V", "video/total_t2v", "出视频 t2v"),
    ]
    for sg_id, pipe_id, up_id, vfi_id, cv_id, save_id, key, y, pw, \
            ptitle, prefix, stitle in vid_rows:
        inst(sg_id, pipe_id, (100, y), (pw, 470), ptitle,
             role="pipeline", key=key)
        inst(SG_VIDEO_UPSCALE, up_id, (700, y), (400, 260), "视频高清化",
             role="module", key="vupscale", mode=4)
        inst(SG_VFI, vfi_id, (1140, y), (360, 240), "视频补帧",
             role="module", key="vfi", mode=4)
        r.add(cv_id, "CreateVideo", (1540, y), (300, 110), [16, "auto", "sRGB"],
              title="封装 " + key.upper(), inputs=[("images", "IMAGE")],
              outputs=[("VIDEO", "VIDEO")],
              wconvert=[("fps", "FLOAT", "帧率")],
              props=props_for("CreateVideo"))
        r.add(save_id, "SaveVideo", (1880, y), (340, 160),
              [prefix, "auto", "auto", "auto"], title=stitle,
              inputs=[("video", "VIDEO")], outputs=[("VIDEO", "VIDEO")],
              mode=2, props=props_for("SaveVideo", "save", key))

    r.add(901, "MarkdownNote", (5200, 120), (680, 1000), [HELP],
          props={})
    r.add(135, "MarkdownNote", (5200, 1200), (680, 300), [HELP_DETAILER],
          props={})
    r.add(136, "MarkdownNote", (5200, 1550), (680, 620), [HELP_UPSCALE],
          props={})

    wire_root(r)

    zones = [
        (1, "A 图像共用前端（模型 / 提示词 / LoRA / 取层）", "#3f789e",
         [101, 102, 103, 104, 105, 108, 109,
          141, 142, 143, 144, 145, 146, 147, 148,
          121, 122, 123, 124, 125, 126, 127, 128, 129,
          130, 131, 132, 133, 134]),
        (2, "B 文生图（多模型分类）", "#3d7f6e",
         [201, 202, 203, 204, 205, 206]),
        (3, "C 图生图精修", "#8f6f3d", [301, 302, 303, 304, 305]),
        (6, "C2 图生图（固定分辨率 · P 图）", "#a06a3c",
         [311, 312, 313, 314, 315]),
        (4, "D 视频（I2V / 首尾帧 / 文生视频）", "#4a9e6b",
         [401, 402, 403, 404, 405, 406, 407, 408, 409, 410, 411, 412,
          461, 462, 463, 464, 465, 466, 467, 468,
          413, 414, 415, 421, 422, 423, 424, 425, 426, 427,
          481, 482, 483, 484, 485,
          431, 432, 441, 442, 451, 452,
          491, 492, 493, 494, 495, 496, 497, 498, 499]),
        (5, "A2 ANIMA 文本编码器 / VAE（跟随模型族自动切）", "#8b5ea8",
         [106, 107, 110, 111, 112, 113]),
    ]
    for gid, title, color, ids in zones:
        nodes = [r.byid(i) for i in ids]
        r.groups.append({"id": gid, "title": title, "bounding": enclose(nodes),
                         "color": color, "flags": {}})
    return r, subs


def wire_root(r):
    C = r.connect_named
    # A 区：模型槽 → 图像 LoRA 组 → CLIP 取层 → 文本编码
    C(101, 0, 102, "model")
    C(101, 1, 112, "clip1")
    C(110, 0, 112, "clip2")
    C(112, 0, 102, "clip")
    C(102, 1, 103, "clip")
    C(103, 0, 106, "clip")
    C(103, 0, 107, "clip")
    C(104, 0, 106, "text")
    C(105, 0, 107, "text")
    C(108, 0, 109, "image")

    # 姿势参考骨架 → 两套姿势模块
    C(109, 0, 202, "pose_image")
    C(109, 0, 203, "pose_image")

    # 条件链：文本 → 姿势(SDXL) → 文生图 / 手眼 / 高清
    C(106, 0, 202, "positive")
    C(107, 0, 202, "negative")
    C(202, 0, 201, "positive")
    C(202, 1, 201, "negative")
    C(202, 0, 204, "positive")
    C(202, 1, 204, "negative")
    C(202, 0, 205, "positive")
    C(202, 1, 205, "negative")
    # 图生图不带 ControlNet 姿势，直接用文本条件
    C(106, 0, 302, "positive")
    C(107, 0, 302, "negative")
    C(106, 0, 303, "positive")
    C(107, 0, 303, "negative")
    C(106, 0, 304, "positive")
    C(107, 0, 304, "negative")

    # 模型链：LoRA 组 → 姿势(ANIMA) → 文生图 / 手眼 / 高清；图生图直连 LoRA 组
    C(102, 0, 203, "model")
    for dst in (201, 204, 205):
        C(203, 0, dst, "model")
    for dst in (302, 303, 304):
        C(102, 0, dst, "model")

    # VAE / CLIP：ckpt 自带的那份与 ANIMA 专用 loader 经开关二选一
    C(101, 2, 113, "VAE1")
    C(111, 0, 113, "VAE2")
    for dst, name in ((201, "vae"), (204, "vae"), (205, "vae"),
                      (302, "vae_encode"), (302, "vae_decode"),
                      (303, "vae"), (304, "vae")):
        C(113, 0, dst, name)
    C(103, 0, 204, "clip")
    C(103, 0, 303, "clip")

    # 参数
    C(121, 0, 201, "width")
    C(122, 0, 201, "height")
    C(123, 0, 201, "steps")
    C(124, 0, 201, "cfg")
    C(125, 0, 201, "seed")
    C(123, 0, 302, "steps")
    C(124, 0, 302, "cfg")
    C(125, 0, 302, "seed")
    C(126, 0, 302, "denoise")
    C(127, 0, 202, "strength")
    C(127, 0, 203, "strength")
    C(128, 0, 205, "factor")
    C(128, 0, 304, "factor")
    C(128, 0, 314, "factor")
    C(129, 0, 205, "denoise")
    C(129, 0, 304, "denoise")
    C(129, 0, 314, "denoise")
    C(1291, 0, 205, "seam_fix_denoise")
    C(1291, 0, 304, "seam_fix_denoise")
    C(1291, 0, 314, "seam_fix_denoise")
    C(1292, 0, 205, "whole_denoise")
    C(1292, 0, 304, "whole_denoise")
    C(1292, 0, 314, "whole_denoise")
    # 分块大小：一个参数喂三条图像管线的分块精修（面板按分辨率自动算好）
    C(1293, 0, 205, "tile")
    C(1293, 0, 304, "tile")
    C(1293, 0, 314, "tile")
    # 脸手眼矫正参数：三条图像管线的矫正模块共用同一组值
    for dst in (204, 303, 313):
        C(130, 0, dst, "bbox_threshold")
        C(1295, 0, dst, "bbox_threshold_eye")
        C(131, 0, dst, "feather")
        C(132, 0, dst, "denoise_face")
        C(133, 0, dst, "denoise_hand")
        C(134, 0, dst, "denoise_eye")
        # 三级共用：检测框放大尺寸 / 放大上限 / 裁剪倍率
        C(137, 0, dst, "guide")
        C(138, 0, dst, "max_size")
        C(139, 0, dst, "crop")

    # B / C 图像链
    C(201, 0, 204, "image")
    C(204, 0, 205, "image")
    C(205, 0, 206, "images")
    C(301, 0, 302, "source_image")
    C(302, 0, 303, "image")
    C(303, 0, 304, "image")
    C(304, 0, 305, "images")

    # C2 图生图（固定分辨率）：取图 → 缩放 → 重绘 → 模块 → 存图
    C(311, 0, 312, "source_image")
    C(312, 0, 313, "image")
    C(313, 0, 314, "image")
    C(314, 0, 315, "images")
    C(121, 0, 312, "width")
    C(122, 0, 312, "height")
    C(123, 0, 312, "steps")
    C(124, 0, 312, "cfg")
    C(125, 0, 312, "seed")
    C(126, 0, 312, "denoise")
    for dst in (312, 313, 314):
        C(106, 0, dst, "positive")
        C(107, 0, dst, "negative")
        C(102, 0, dst, "model")
    for dst, name in ((312, "vae_encode"), (312, "vae_decode"),
                      (313, "vae"), (314, "vae")):
        C(113, 0, dst, name)
    C(103, 0, 313, "clip")

    # D 视频
    C(401, 0, 404, "text")
    C(402, 0, 405, "text")
    C(403, 0, 404, "clip")
    C(403, 0, 405, "clip")
    C(406, 0, 408, "model")
    C(407, 0, 409, "model")
    C(408, 0, 410, "model")
    C(409, 0, 411, "model")
    C(410, 0, 431, "model_high")
    C(410, 0, 441, "model_high")
    C(411, 0, 431, "model_low")
    C(411, 0, 441, "model_low")
    for dst in (431, 441):
        C(404, 0, dst, "positive")
        C(405, 0, dst, "negative")
        C(412, 0, dst, "vae_image")
        C(412, 0, dst, "vae_decode")
        C(421, 0, dst, "width")
        C(422, 0, dst, "height")
        C(423, 0, dst, "length")
        C(425, 0, dst, "steps_high")
        C(425, 0, dst, "steps_low")
        C(426, 0, dst, "cfg_high")
        C(426, 0, dst, "cfg_low")
        C(427, 0, dst, "seed")
    C(404, 0, 451, "positive")
    C(405, 0, 451, "negative")
    C(421, 0, 451, "width")
    C(422, 0, 451, "height")
    C(423, 0, 451, "length")
    C(427, 0, 451, "seed")
    C(413, 0, 431, "start_image")
    C(414, 0, 441, "start_image")
    C(415, 0, 441, "end_image")

    # 视频后处理链：管线 → 视频高清化 → 视频补帧 → 封装 → 存盘。
    # 高清放在补帧前面：同样一遍 4x 放大，81 帧比补完的 161 帧省一半时间和显存。
    # 帧率只在补帧那一步乘（模块关掉就原样透传），所以回放速度永远对得上。
    for pipe_id, up_id, vfi_id, cv_id, save_id in (
            (431, 492, 491, 497, 432),
            (441, 494, 493, 498, 442),
            (451, 496, 495, 499, 452)):
        C(pipe_id, 0, up_id, "frames")
        C(up_id, 0, vfi_id, "frames")
        C(424, 0, vfi_id, "fps")
        C(481, 0, vfi_id, "multiplier")
        C(vfi_id, 0, cv_id, "images")
        C(vfi_id, 1, cv_id, "fps")
        C(cv_id, 0, save_id, "video")
        C(482, 0, up_id, "factor")
        C(483, 0, up_id, "base")
        C(484, 0, up_id, "batch")
        C(485, 0, up_id, "tile")


WIDGET_CARRY = {
    101: [0], 103: [0], 108: [0], 110: [0], 111: [0], 112: [0], 113: [0],
    121: [0], 122: [0], 123: [0], 124: [0], 125: [0], 126: [0],
    127: [0], 128: [0], 129: [0], 1291: [0], 1292: [0],
    130: [0], 131: [0], 132: [0], 133: [0], 134: [0],
    137: [0], 138: [0], 139: [0],
    # 301 / 413 是 LoadImageOutput：第 0 格是文件名，第 1 格 control_after_refresh
    301: [0], 413: [0],
    # 视频那套加载器（v1.5.0）：high / low 模型槽 + 文本编码器 + VAE 也结转，
    # 免得重建蓝图时把你挑好的视频权重弹回默认
    403: [0], 406: [0], 407: [0], 412: [0],
    421: [0], 422: [0], 423: [0], 424: [0], 425: [0], 426: [0], 427: [0],
    481: [0], 482: [0], 483: [0], 484: [0], 485: [0],
}
LORA_CARRY = [102, 408, 409]
PROMPT_CARRY = [104, 105, 401, 402]
# 每段的"手填 / 插件"开关（v6.1 起）：整份 widgets_values 结转
# 只有正面那两组有分段开关；负面 105 / 402 已经是单框，不再生成开关节点
PROMPT_BASE = {104: 141, 401: 461}
# 读老文件（v6.1 的负面也是 8 段）时用的旧 id 表，别删
OLD_PROMPT_BASE = {104: 141, 105: 151, 401: 461, 402: 471}
SEG_CARRY = [b + i for b in PROMPT_BASE.values() for i in range(PROMPT_SLOTS)]

# 子图里的采样器 / 调度器：面板「参数 → 采样器 / 调度器」下拉写的就是这两格，
# 重建蓝图时按子图 id + 节点 id + 类型结转，免得点一次「生成 / 更新蓝图」就弹回默认。
SAMPLER_WIDGET_ORDER = {
    "KSampler": ["seed", "control_after_generate", "steps", "cfg",
                 "sampler_name", "scheduler", "denoise"],
    "KSamplerAdvanced": ["add_noise", "noise_seed", "control_after_generate",
                         "steps", "cfg", "sampler_name", "scheduler",
                         "start_at_step", "end_at_step",
                         "return_with_leftover_noise"],
}
SAMPLER_CARRY_WIDGETS = ("sampler_name", "scheduler")


def carry_samplers(wf, prev):
    """把旧蓝图子图里的采样器 / 调度器选择搬到新蓝图（找不到就保持默认）。"""
    old_subs = {s.get("id"): s for s in
                ((prev.get("definitions") or {}).get("subgraphs") or [])}
    n = 0
    for sub in (wf.get("definitions") or {}).get("subgraphs") or []:
        old = old_subs.get(sub.get("id"))
        if not old:
            continue
        old_nodes = {x.get("id"): x for x in old.get("nodes") or []}
        for node in sub.get("nodes") or []:
            order = SAMPLER_WIDGET_ORDER.get(node.get("type"))
            o = old_nodes.get(node.get("id"))
            if not order or not o or o.get("type") != node.get("type"):
                continue
            owv, nwv = o.get("widgets_values"), node.get("widgets_values")
            if not isinstance(owv, list) or not isinstance(nwv, list):
                continue
            for name in SAMPLER_CARRY_WIDGETS:
                i = order.index(name)
                if i < len(owv) and i < len(nwv) and isinstance(owv[i], str):
                    if nwv[i] != owv[i]:
                        nwv[i] = owv[i]
                        n += 1
    return n


# 子图「内部」节点的开关状态：面板上的三级（脸 / 手 / 眼）和 SAM 开关写的是
# 子图定义里那三个 FaceDetailer / SAMLoader 的 mode，不是实例节点，所以
# 上面那套按根图 id 结转的逻辑管不到它们，得单独按 (子图 id, 节点 id, 类型) 搬。
SUB_MODE_ROLES = ("detailer_stage", "detailer_sam")


def carry_sub_modes(wf, prev):
    old_subs = {s.get("id"): s for s in
                ((prev.get("definitions") or {}).get("subgraphs") or [])}
    n = 0
    for sub in (wf.get("definitions") or {}).get("subgraphs") or []:
        old = old_subs.get(sub.get("id"))
        if not old:
            continue
        old_nodes = {x.get("id"): x for x in old.get("nodes") or []}
        for node in sub.get("nodes") or []:
            props = node.get("properties") or {}
            if props.get("cc_dock_role") not in SUB_MODE_ROLES:
                continue
            o = old_nodes.get(node.get("id"))
            if not o or o.get("type") != node.get("type"):
                continue
            if isinstance(o.get("mode"), int) and node.get("mode") != o["mode"]:
                node["mode"] = o["mode"]
                n += 1
    return n


def joined_prompt_text(old_nodes, nid, owv):
    """把老的分段提示词拼回一条（负面从 8 段退回单框时用）。

    优先读各段开关的手填格，那儿才是真文本；读不到再退到拼接器里的镜像格。
    """
    sep = PROMPT_SEP
    if isinstance(owv, list) and owv and isinstance(owv[0], str) and owv[0]:
        sep = owv[0]
    base = OLD_PROMPT_BASE.get(nid)
    parts = []
    for i in range(PROMPT_SLOTS):
        t = ""
        sw = old_nodes.get(base + i) if base else None
        swv = sw.get("widgets_values") if sw else None
        if isinstance(swv, list) and len(swv) >= 2 and isinstance(swv[1], str):
            t = swv[1]
        if not t.strip() and isinstance(owv, list) and len(owv) > 2 + 2 * i:
            t = owv[2 + 2 * i] if isinstance(owv[2 + 2 * i], str) else ""
        if t.strip():
            parts.append(t.strip())
    return sep.join(parts)


def carry_widgets(old_node, new_node, indices):
    owv = old_node.get("widgets_values")
    if not isinstance(owv, list):
        return False
    nwv = new_node.get("widgets_values")
    if not isinstance(nwv, list):
        nwv = []
        new_node["widgets_values"] = nwv
    changed = False
    for i in indices:
        if i >= len(owv) or isinstance(owv[i], (dict, list)):
            continue
        while len(nwv) <= i:
            nwv.append(None)
        nwv[i] = owv[i]
        changed = True
    return changed



# v6.4：这几个参数「以前的默认值本身有问题」（羽化 5 太硬、重绘 0.4~0.5 太高）。
# 画布上如果还是老默认值（说明你没动过这一项），就跟着升级到新默认；
# 你自己调过的值（不等于老默认）一律保留。
# 每项是 [(旧默认, 新默认), ...]：可以串多级，老用户从任何一代默认值都能跳到最新。
PARAM_MIGRATE = {
    # 旧高清链净倍率是「倍数 × 2」，那时候填 1（= 实际 2 倍）是个常见值；
    # 现在链子只放大一次，1 就成了「完全没放大」，所以跟着升到 2。
    "upscale_factor": [(1, 2)],
    "detailer_feather": [(5, 24)],
    # v6.5：三级重绘强度整体再降一档（0.2~0.25 = 只修不重画）
    "detailer_denoise_face": [(0.40, 0.25), (0.35, 0.25)],
    "detailer_denoise_hand": [(0.50, 0.25), (0.45, 0.25)],
    "detailer_denoise_eye": [(0.50, 0.20), (0.30, 0.20)],
    # v6.5：脸 / 手 的检测阈值回到 0.55（手那级最容易在肢体交叠处误检）
    "detailer_threshold": [(0.50, 0.55)],
    "detailer_threshold_eye": [(0.65, 0.70)],
}


def migrate_stale_defaults(wf):
    """把「还停在旧默认值」的参数升到新默认；用户自己调过的不动。"""
    n = 0
    for node in wf.get("nodes") or []:
        props = node.get("properties") or {}
        if props.get("cc_dock_role") != "param":
            continue
        rule = PARAM_MIGRATE.get(props.get("cc_dock_key"))
        if not rule:
            continue
        wv = node.get("widgets_values")
        if not isinstance(wv, list) or not wv:
            continue
        for old, new in rule:
            try:
                if abs(float(wv[0]) - float(old)) < 1e-6 \
                        and abs(float(old) - float(new)) > 1e-9:
                    wv[0] = new
                    n += 1
                    break
            except (TypeError, ValueError):
                break
    return n


# 按 node id 升级「还停在旧默认值」的文件槽（v1.9.0）：111 原来是 wan_2.1_vae，
# 官方 ANIMA 那份是 qwen_image_vae；只在还是旧默认时才换，用户挑过的不动。
FILE_MIGRATE = {
    111: [("wan_2.1_vae.safetensors", M_ANIMA_VAE)],
}


def migrate_resource_files(wf):
    """外挂文件槽的默认值升级（见 FILE_MIGRATE）。"""
    n = 0
    by_id = {node.get("id"): node for node in wf.get("nodes") or []}
    for nid, rules in FILE_MIGRATE.items():
        node = by_id.get(nid)
        wv = (node or {}).get("widgets_values")
        if not isinstance(wv, list) or not wv:
            continue
        for old, new in rules:
            if str(wv[0]) == old and old != new:
                wv[0] = new
                n += 1
                break
    return n


def carry_video_loaders(wf, prev):
    """视频模型槽（406 / 407）：上一份用的是 GGUF 加载器就还出 GGUF 节点。

    面板上选 .gguf 会把 UNETLoader 换成 UnetLoaderGGUF，名字一样但节点类型不同；
    重建蓝图时要是硬塞回 UNETLoader，那格就会挂上一个「清单里没有的文件」。
    """
    old_nodes = {n.get("id"): n for n in prev.get("nodes") or []}
    new_nodes = {n.get("id"): n for n in wf.get("nodes") or []}
    n = 0
    for nid in (406, 407):
        o, new = old_nodes.get(nid), new_nodes.get(nid)
        if not (o and new):
            continue
        owv = o.get("widgets_values")
        name = owv[0] if isinstance(owv, list) and owv and isinstance(owv[0], str) else ""
        if not name:
            continue
        if o.get("type") != "UnetLoaderGGUF" and not name.lower().endswith(".gguf"):
            continue
        new["type"] = "UnetLoaderGGUF"
        new["widgets_values"] = [name]          # GGUF 加载器没有 weight_dtype 那一格
        n += 1
    return n


def carry_over(wf, prev):
    """把旧工作流里用户改过的值结转到这次重建的工作流上。

    只认节点 id + 类型一致的：模型槽 / 参数 / 取图 / LoRA 行 / 提示词，
    以及各管线、模块、Save 的 mode（保留你当前开着哪些管线）。
    """
    if not isinstance(prev, dict):
        return 0
    old_nodes = {n.get("id"): n for n in prev.get("nodes") or []}
    new_nodes = {n.get("id"): n for n in wf.get("nodes") or []}
    # 先定好视频模型槽的加载器类型（UNETLoader / UnetLoaderGGUF），
    # 后面那些按「类型一致才结转」的规则才不会打架
    carried = carry_video_loaders(wf, prev)
    for nid, idx in WIDGET_CARRY.items():
        o, n = old_nodes.get(nid), new_nodes.get(nid)
        if o and n and o.get("type") == n.get("type"):
            carried += 1 if carry_widgets(o, n, idx) else 0
    for nid in LORA_CARRY:
        o, n = old_nodes.get(nid), new_nodes.get(nid)
        if not (o and n) or o.get("type") != n.get("type"):
            continue
        owv = o.get("widgets_values")
        if isinstance(owv, list) and any(
                isinstance(x, dict) and "lora" in x for x in owv):
            n["widgets_values"] = json.loads(json.dumps(owv))
            carried += 1
    # 每段的"手填 / 插件"开关：整份接过来（手填文字 + 插件开关状态）
    for nid in SEG_CARRY:
        o, n = old_nodes.get(nid), new_nodes.get(nid)
        if not (o and n) or o.get("type") != n.get("type"):
            continue
        owv = o.get("widgets_values")
        if isinstance(owv, list) and len(owv) == 3:
            n["widgets_values"] = json.loads(json.dumps(owv))
            carried += 1
    # 提示词组：正面（8 段版）整份接过来，老的单框版落到第 1 段；
    # 负面（新的是单框）把老的分段文本按分隔符拼回一格，老的单框文本原样搬
    for nid in PROMPT_CARRY:
        o, n = old_nodes.get(nid), new_nodes.get(nid)
        if not (o and n):
            continue
        owv = o.get("widgets_values")
        nwv = n.get("widgets_values")
        if not isinstance(nwv, list):
            continue
        old_type = o.get("type")
        if n.get("type") == "PrimitiveStringMultiline":
            text = None
            if (old_type == "PrimitiveStringMultiline"
                    and isinstance(owv, list) and owv
                    and isinstance(owv[0], str)):
                text = owv[0]
            elif old_type == "YogurtStringConcat":
                text = joined_prompt_text(old_nodes, nid, owv)
            if text is not None:
                nwv[0] = text
                carried += 1
            continue
        texts = None
        if (old_type == "YogurtStringConcat"
                and isinstance(owv, list) and len(owv) == len(nwv)):
            # 只接分隔符和 enable 开关；段文本住在各段开关里（这里留空当镜像）
            nwv[0] = owv[0]
            for i in range(PROMPT_SLOTS):
                nwv[1 + 2 * i] = owv[1 + 2 * i]
            carried += 1
            texts = [owv[2 + 2 * i] for i in range(PROMPT_SLOTS)]
        elif (old_type == "PrimitiveStringMultiline"
                and isinstance(owv, list) and owv and isinstance(owv[0], str)):
            texts = [owv[0]]
        if not texts:
            continue
        # 老文本搬到各段开关的手填格里（只在那边还空着的时候搬，别覆盖后来写的）
        base = PROMPT_BASE[nid]
        for i, t in enumerate(texts):
            if not t:
                continue
            sw = new_nodes.get(base + i)
            if not sw or sw.get("type") != "CR Text Input Switch JK":
                continue
            swv = sw.get("widgets_values")
            if not isinstance(swv, list) or len(swv) < 3:
                continue
            if isinstance(swv[1], str) and swv[1].strip():
                continue
            swv[1] = t
            swv[2] = t
            carried += 1
    # 管线 / 模块 / Save 的开关状态
    for nid, o in old_nodes.items():
        n = new_nodes.get(nid)
        if not n or o.get("type") != n.get("type"):
            continue
        if isinstance(o.get("mode"), int):
            n["mode"] = o["mode"]
    # 子图里的采样器 / 调度器（面板下拉写的）
    carried += carry_samplers(wf, prev)
    # 子图内部的三级矫正 / SAM 开关（面板上那几个勾写的）
    carried += carry_sub_modes(wf, prev)
    ds = (prev.get("extra") or {}).get("ds")
    if isinstance(ds, dict):
        wf.setdefault("extra", {})["ds"] = ds
    return carried


def build_workflow(prev=None):
    """构造蓝图（纯函数，不碰磁盘）。

    prev：画布上现有那份蓝图；给了就按 id 结转用户改过的模型槽 / LoRA / 参数 /
    取图 / 提示词 / 开关状态，不给就是一份干净的默认蓝图。
    """
    for problem in check_usdu_widget_order():
        print("warn: %s" % problem)

    r, subs = build()
    wf = {
        "id": "0b7a1c10-0002-4a01-9c01-000000000010",
        "revision": 0,
        "last_node_id": max(n["id"] for n in r.nodes),
        "last_link_id": max(l[0] for l in r.links),
        "nodes": r.nodes,
        "links": r.links,
        "groups": r.groups,
        "config": {},
        "extra": {"ds": {"scale": 0.12, "offset": [120, 260]},
                  "workflowRendererVersion": "LG",
                  # 面板读这个判断「画布上这份是不是旧蓝图」；见 BLUEPRINT_REV
                  "cc_dashboard_blueprint": {"rev": BLUEPRINT_REV,
                                             "tag": BLUEPRINT_TAG}},
        "version": 0.4,
        "definitions": {"subgraphs": subs},
    }
    carried = carry_over(wf, prev)
    migrated = migrate_stale_defaults(wf)
    migrated_files = migrate_resource_files(wf)

    live = [n["id"] for n in r.nodes if n.get("mode", 0) == 0]
    bypassed = [n["id"] for n in r.nodes if n.get("mode", 0) == 4]
    muted = [n["id"] for n in r.nodes if n.get("mode", 0) == 2]
    report = {
        "nodes": len(r.nodes),
        "links": len(r.links),
        "groups": len(r.groups),
        "subgraphs": len(subs),
        "carried": carried,
        "migrated": migrated,
        "migrated_files": migrated_files,
        "live": len(live),
        "bypassed": bypassed,
        "muted": muted,
        "subgraph_list": [
            {"name": sg["name"], "nodes": len(sg["nodes"]),
             "links": len(sg["links"]), "inputs": len(sg["inputs"]),
             "outputs": len(sg["outputs"])}
            for sg in subs],
    }
    return wf, report


def write_blueprint(mode="update", out_path=None, backup=True, guard=False,
                    prev_override=None):
    """生成蓝图并落盘。

    mode="update" 结转画布上现有的用户改动；mode="fresh" 按默认值重建。
    guard=True 时只允许写进 ComfyUI 的工作流目录（接口调用走这条）。
    prev_override：面板把自己画布上的现况传来时用它做结转（比磁盘那份新）；
    结构永远来自 build()，所以传旧画布也只会救回参数、不会把旧结构带回来。
    返回 {ok, path, backup, mode, report, workflow}。
    """
    out = os.path.abspath(out_path) if out_path else paths.workflow_path()
    if guard and not paths.inside(out, paths.workflows_dir()):
        raise ValueError("拒绝写到工作流目录之外：%s" % out)

    existing = None
    if os.path.exists(out):
        try:
            with open(out, encoding="utf-8") as fh:
                existing = json.load(fh)
        except Exception as e:
            print("warn: 旧工作流读取失败 %r" % (e,))
    prev = existing if mode != "fresh" else None
    if mode != "fresh" and isinstance(prev_override, dict) \
            and isinstance(prev_override.get("nodes"), list):
        prev = prev_override

    wf, report = build_workflow(prev)

    # 备份：画布上手动改过的东西不会被这次重建静默吃掉
    backup_to = None
    if existing is not None and backup:
        try:
            import shutil
            backup_to = paths.backup_path(out)
            os.makedirs(os.path.dirname(backup_to), exist_ok=True)
            shutil.copyfile(out, backup_to)
        except Exception as e:      # 备份失败不影响生成
            backup_to = None
            print("warn: 备份失败 %r" % (e,))

    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(wf, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    if prev is None:
        src = "defaults"
    elif prev is prev_override:
        src = "canvas"
    else:
        src = "file"
    return {"ok": True, "path": out, "backup": backup_to, "mode": mode,
            "carried_from": src, "report": report, "workflow": wf}


def print_report(res):
    rep = res.get("report") or {}
    print("wrote %s" % res.get("path"))
    if res.get("backup"):
        print("backup %s" % res["backup"])
    print("root nodes=%d links=%d groups=%d subgraphs=%d"
          % (rep.get("nodes", 0), rep.get("links", 0), rep.get("groups", 0),
             rep.get("subgraphs", 0)))
    print("carried user values: %d" % rep.get("carried", 0))
    if rep.get("migrated"):
        print("升级了 %d 个还停在旧默认值的矫正参数（羽化 5→24、"
              "重绘 →0.25/0.25/0.20、阈值 →0.55/0.70）" % rep["migrated"])
    if rep.get("migrated_files"):
        print("外挂文件槽升级了 %d 个还停在旧默认值的"
              "（111 VAE：wan_2.1_vae → qwen_image_vae）" % rep["migrated_files"])
    print("live=%d bypassed=%s muted=%s"
          % (rep.get("live", 0), rep.get("bypassed", []), rep.get("muted", [])))
    for sg in rep.get("subgraph_list", []):
        print("  sg %-14s nodes=%-3d links=%-3d in=%-2d out=%d"
              % (sg["name"], sg["nodes"], sg["links"], sg["inputs"],
                 sg["outputs"]))


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="生成 ComfyUI 总控台蓝图")
    ap.add_argument("--out", help="输出路径，默认 <user>/default/workflows/00_总控台.json")
    ap.add_argument("--fresh", action="store_true",
                    help="不结转画布上现有的值，按默认值重建")
    ap.add_argument("--no-backup", action="store_true", help="不写备份")
    ap.add_argument("--preset", action="store_true",
                    help="维护者用：把默认蓝图覆盖写进 blueprint/00_总控台.json")
    args = ap.parse_args(argv)
    if args.preset:
        res = write_blueprint(mode="fresh", out_path=paths.blueprint_json(),
                              backup=False, guard=False)
    else:
        res = write_blueprint(mode="fresh" if args.fresh else "update",
                              out_path=args.out, backup=not args.no_backup,
                              guard=bool(args.out))
    print_report(res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
