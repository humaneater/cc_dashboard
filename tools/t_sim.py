# -*- coding: utf-8 -*-
"""离线复刻前端 graphToPrompt：子图展开 + 旁路透传 + 静音排除。

不需要启动 ComfyUI。用于验证 00_总控台.json 在各场景下的执行集合：
  默认文生图 / 文生图全模块 / 切 ANIMA / 图生图 / I2V / FLF2V / T2V /
  视频后处理（视频高清化 → 视频补帧）/ 图生图+视频 / LoRA 行开关 / 模块旁路 /
  面板默认值（重置默认值写回画布的那一套）

运行： python tools/t_sim.py
"""
import copy
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(HERE))
from tools import paths                                    # noqa: E402

WF_PATH = paths.workflow_path()
OI_PATH = paths.object_info_path()

WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN"}

# 面板上所有模块开关（图像三个 + 视频后处理两个）。每个场景都从「全关」起步。
MOD_KEYS = ("pose_sdxl", "pose_anima", "detailer", "upscale", "vfi", "vupscale")

PROBLEMS = []


def widgetable(spec):
    if not isinstance(spec, list) or not spec:
        return False
    t = spec[0]
    if isinstance(t, list) or t in ("COMBO", "COMFY_DYNAMICCOMBO_V3"):
        return True
    return t in WIDGET_TYPES


def widget_names(defn):
    names = []
    for sec in ("required", "optional"):
        for name, spec in (defn["input"].get(sec) or {}).items():
            opts = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
            if opts.get("forceInput") or opts.get("hidden"):
                continue
            if not widgetable(spec):
                continue
            names.append(name)
            # 前端给「带 control_after_generate 的 INT」多挂一个控制 widget：
            # 老节点叫 seed / noise_seed，新 PrimitiveInt 直接写在 spec 第二项里
            if spec[0] == "INT" and (name in ("seed", "noise_seed")
                                     or "control_after_generate" in opts):
                names.append("control_after_generate")
    return names


def required_names(defn):
    out = []
    for name, spec in (defn["input"].get("required") or {}).items():
        opts = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
        if opts.get("hidden"):
            continue
        out.append(name)
    return out


class Ctx(object):
    """一个图层（根图或某个子图）。"""

    def __init__(self, graph, links, path, parent=None, inst_id=None,
                 is_root=False):
        self.nodes = {n["id"]: n for n in graph}
        self.links = links            # {id: link}
        self.path = path              # "" 表示根图
        self.parent = parent          # (Ctx, instance_node_id)
        self.inst_id = inst_id
        self.is_root = is_root

    def exec_id(self, nid):
        return "%s:%s" % (self.path, nid) if self.path else str(nid)

    def link_into(self, nid, slot):
        for l in self.links.values():
            if l["target_id"] == nid and l["target_slot"] == slot:
                return l
        return None

    def link_from(self, nid, slot):
        for l in self.links.values():
            if l["origin_id"] == nid and l["origin_slot"] == slot:
                return l
        return None


class Sim(object):
    def __init__(self, wf, oi):
        self.wf = wf
        self.oi = oi
        self.subs = {s["id"]: s for s in
                     (wf.get("definitions") or {}).get("subgraphs") or []}
        self.prompt = {}
        self.root = Ctx(wf["nodes"], {l[0]: {"id": l[0], "origin_id": l[1],
                                             "origin_slot": l[2],
                                             "target_id": l[3],
                                             "target_slot": l[4],
                                             "type": l[5]}
                                      for l in wf["links"]},
                        "", is_root=True)

    # ---------------------------------------------------------------- 工具
    def wvalue(self, node, name):
        defn = self.oi.get(node["type"])
        if not defn:
            return None
        names = widget_names(defn)
        if name not in names:
            return None
        i = names.index(name)
        wv = node.get("widgets_values") or []
        return wv[i] if i < len(wv) else None

    def set_wvalue(self, node, name, value):
        defn = self.oi.get(node["type"])
        names = widget_names(defn)
        i = names.index(name)
        wv = node.setdefault("widgets_values", [])
        while len(wv) <= i:
            wv.append(None)
        wv[i] = value

    def bypass_slot(self, node, slot):
        outs = node.get("outputs") or []
        ins = node.get("inputs") or []
        if slot >= len(outs):
            return -1
        otype = outs[slot]["type"]
        if slot < len(ins) and ins[slot]["type"] == otype:
            return slot
        for i, s in enumerate(ins):
            if s["type"] == otype:
                return i
        return -1

    def sub_ctx(self, ctx, node):
        sg = self.subs[node["type"]]
        inner_links = {l["id"]: l for l in (sg.get("links") or [])}
        return Ctx(sg["nodes"], inner_links, ctx.exec_id(node["id"]),
                   parent=(ctx, node["id"]), inst_id=node["id"])

    # ------------------------------------------------------------ 解析
    def resolve_output(self, ctx, nid, slot):
        """返回 ("node", ctx, nid, slot) 或 None。"""
        node = ctx.nodes[nid]
        mode = node.get("mode", 0)
        if mode == 2:
            return None
        if mode == 4:
            b = self.bypass_slot(node, slot)
            return self.resolve_input(ctx, nid, b) if b >= 0 else None
        if node["type"] in self.subs:
            inner = self.sub_ctx(ctx, node)
            lk = inner.link_into(-20, slot)
            if lk is None:
                return None
            return self.resolve_output(inner, lk["origin_id"],
                                       lk["origin_slot"])
        return ("node", ctx, nid, slot)

    def resolve_input(self, ctx, nid, slot):
        node = ctx.nodes[nid]
        lk = ctx.link_into(nid, slot)
        if lk is None:
            return None
        if lk["origin_id"] == -10:
            if ctx.parent is None:
                return None
            pctx, inst = ctx.parent
            return self.resolve_input(pctx, inst, lk["origin_slot"])
        return self.resolve_output(ctx, lk["origin_id"], lk["origin_slot"])

    # ------------------------------------------------------------ 收集
    def ensure(self, ctx, nid):
        node = ctx.nodes[nid]
        key = ctx.exec_id(nid)
        if key in self.prompt:
            return key
        if node["type"] in self.subs:
            raise RuntimeError("子图实例不应直接进 prompt：%s" % node["type"])
        defn = self.oi[node["type"]]
        entry = {"class_type": node["type"],
                 "_meta": {"title": node.get("title") or node["type"]}}
        self.prompt[key] = entry
        inputs = {}
        for i, s in enumerate(node.get("inputs") or []):
            tgt = self.resolve_input(ctx, nid, i)
            if tgt is None:
                continue
            inputs[s["name"]] = [tgt[1].exec_id(tgt[2]), tgt[3]]
            self.ensure(tgt[1], tgt[2])
        # widget 值（被链接覆盖）
        names = widget_names(defn)
        wv = node.get("widgets_values") or []
        for i, name in enumerate(names):
            if i >= len(wv):
                continue
            if name == "control_after_generate":
                continue
            if name in inputs:
                continue
            inputs[name] = wv[i]
        if node["type"] == "Power Lora Loader (rgthree)":
            n = 0
            for row in wv:
                if isinstance(row, dict) and "lora" in row:
                    n += 1
                    inputs["lora_%d" % n] = row
        if node["type"] in ("LoadImage", "LoadImageOutput"):
            v = inputs.get("image")
            if isinstance(v, str):
                inputs["image"] = v.replace(" [output]", "")
        entry["inputs"] = inputs
        # 必需输入检查
        for name in required_names(defn):
            if name not in inputs:
                PROBLEMS.append("%s(%s) 缺必需输入 %s"
                                % (key, node["type"], name))
        return key

    def outputs(self):
        res = []
        for n in self.wf["nodes"]:
            defn = self.oi.get(n["type"])
            if not defn:
                continue
            if not defn.get("output_node"):
                continue
            if n.get("mode", 0) != 0:
                continue
            res.append(n)
        return res

    def run(self):
        for n in self.outputs():
            self.ensure(self.root, n["id"])
        return self.prompt


# --------------------------------------------------------------- 场景工具
def by_role(wf, role, key=None):
    out = []
    for n in wf["nodes"]:
        p = n.get("properties") or {}
        if p.get("cc_dock_role") != role:
            continue
        if key is not None and p.get("cc_dock_key") != key:
            continue
        out.append(n)
    return out


def one(wf, role, key=None):
    r = by_role(wf, role, key)
    if len(r) != 1:
        raise AssertionError("%s/%s 数量 %d" % (role, key, len(r)))
    return r[0]


def set_mode(wf, nid, mode):
    for n in wf["nodes"]:
        if n["id"] == nid:
            n["mode"] = mode
            return
    raise KeyError(nid)


def pick_pipeline(wf, key):
    for n in by_role(wf, "save"):
        n["mode"] = 0 if (n["properties"] or {}).get("cc_dock_key") == key else 2


def set_module(wf, key, on):
    for n in by_role(wf, "module", key):
        n["mode"] = 0 if on else 4


def set_widget(wf, nid, name, value, oi):
    for n in wf["nodes"]:
        if n["id"] != nid:
            continue
        set_widget_of(n, name, value, oi[n["type"]])
        return
    raise KeyError(nid)


def set_widget_of(node, name, value, defn):
    """直接改某个节点上的 widget 值（不做 id 查找）。"""
    names = widget_names(defn)
    i = names.index(name)
    wv = node.setdefault("widgets_values", [])
    while len(wv) <= i:
        wv.append(None)
    wv[i] = value


def node_by_id(wf, nid):
    for n in wf["nodes"]:
        if n["id"] == nid:
            return n
    raise KeyError(nid)


def deref(prompt, key, name):
    """把某个输入上的连线解析成上游 entry；连线就返回 [id, slot]。"""
    ent = prompt.get(key)
    if not ent:
        return None
    v = ent["inputs"].get(name)
    if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
        return prompt.get(v[0]) or v
    return v


def wire_string(wf, src_nid, dst_nid, input_name, value=""):
    """在测试用的工作流副本上现加一条 STRING 连线（模拟用户手连插件）。"""
    dst = node_by_id(wf, dst_nid)
    idx = [s["name"] for s in dst.get("inputs") or []].index(input_name)
    for l in wf["links"]:
        if l[3] == dst_nid and l[4] == idx:
            wf["links"].remove(l)
            break
    lid = max([l[0] for l in wf["links"]] or [0]) + 1
    wf["links"].append([lid, src_nid, 0, dst_nid, idx, "STRING"])
    dst["inputs"][idx]["link"] = lid
    wf["last_link_id"] = max(wf.get("last_link_id", 0), lid)
    return lid


def add_string_node(wf, nid, value, title):
    wf["nodes"].append({
        "id": nid, "type": "PrimitiveStringMultiline",
        "pos": [0, 4000], "size": [220, 60], "flags": {}, "order": 999,
        "mode": 0,
        "inputs": [{"name": "value", "type": "STRING", "link": None}],
        "outputs": [{"name": "STRING", "type": "STRING", "links": []}],
        "properties": {"Node name for S&R": "PrimitiveStringMultiline"},
        "widgets_values": [value], "title": title,
    })
    wf["last_node_id"] = max(wf.get("last_node_id", 0), nid)
    return node_by_id(wf, nid)


def apply_model_preset(wf, oi, ckpt):
    """复刻面板逻辑：切模型 → 步数/CFG/取层/姿势族。"""
    anima = "anima" in ckpt.lower()
    set_widget(wf, one(wf, "model_slot")["id"], "ckpt_name", ckpt, oi)
    set_mode(wf, one(wf, "preset_sdxl")["id"], 4 if anima else 0)
    set_widget(wf, one(wf, "param", "steps")["id"], "value",
               30 if anima else 28, oi)
    set_widget(wf, one(wf, "param", "cfg")["id"], "value",
               4.5 if anima else 5.5, oi)
    # CLIP / VAE 来源开关跟模型族走（1 = ckpt 自带，2 = ANIMA 专用 loader）
    for k in ("clip", "vae"):
        for n in by_role(wf, "family", k):
            set_widget(wf, n["id"], "Input", 2 if anima else 1, oi)
    return anima


def classes(prompt):
    return sorted({e["class_type"] for e in prompt.values()})


def count(prompt, ctype):
    return sum(1 for e in prompt.values() if e["class_type"] == ctype)


def entry_of(prompt, ctype):
    for k, e in prompt.items():
        if e["class_type"] == ctype:
            return k, e
    return None, None


def linked_value(prompt, entry, name):
    """输入若是连线，顺着 PrimitiveXxx.value 取出真实数值。"""
    v = entry["inputs"].get(name)
    while isinstance(v, list) and isinstance(v[0], str):
        src = prompt.get(v[0])
        if not src:
            return v
        if "value" in src["inputs"]:
            v = src["inputs"]["value"]
            continue
        if "ckpt_name" in src["inputs"]:
            v = src["inputs"]["ckpt_name"]
            continue
        return v
    return v


def check_dangling(prompt, tag):
    for k, e in prompt.items():
        for name, v in e["inputs"].items():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                if v[0] not in prompt:
                    PROBLEMS.append("%s: %s.%s 指向不存在的节点 %s"
                                    % (tag, k, name, v[0]))


def sim(wf, oi, tag, expect_problems=0):
    del PROBLEMS[:]
    prompt = Sim(copy.deepcopy(wf), oi).run()
    check_dangling(prompt, tag)
    if len(PROBLEMS) != expect_problems:
        print("  [%s] 问题 %d 条：" % (tag, len(PROBLEMS)))
        for p in PROBLEMS[:12]:
            print("      - %s" % p)
        return prompt, False
    print("  [%s] OK  prompt 节点 %d 个" % (tag, len(prompt)))
    return prompt, True


def main():
    if not os.path.exists(OI_PATH):
        print("缺少节点定义快照：%s" % OI_PATH)
        print("先跑一次（要用 ComfyUI 自带的 python）：")
        print("    python_embeded\\python.exe tools/dump_object_info.py")
        return 2
    wf = json.load(open(WF_PATH, encoding="utf-8"))
    oi = json.load(open(OI_PATH, encoding="utf-8"))
    # 画布文件里存着上次用的状态（停在图生图 / 开着某个模块），
    # 下面每条场景都从「文生图 + 模块全关」这个干净基线出发
    pick_pipeline(wf, "t2i")
    for _k in MOD_KEYS:
        set_module(wf, _k, False)

    def modules_all_off(w):
        for k2 in MOD_KEYS:
            set_module(w, k2, False)
        return w

    bad = 0
    print("=" * 66)

    # 1 默认：文生图
    # 画布上可能停着上次的状态（别的模型族 / 别的管线 / 开着模块），
    # 先显式切回「SDXL + 文生图 + 模块全关」再断言，测的是结构而不是当前状态
    w0 = copy.deepcopy(wf)
    apply_model_preset(w0, oi, "waiIllustriousSDXL_v170.safetensors")
    pick_pipeline(w0, "t2i")
    for key in MOD_KEYS:
        set_module(w0, key, False)
    p, ok = sim(w0, oi, "默认文生图")
    bad += not ok
    need = ["CheckpointLoaderSimple", "CLIPSetLastLayer", "CLIPTextEncode",
            "KSampler", "VAEDecode", "SaveImage",
            "Power Lora Loader (rgthree)"]
    for c in need:
        if count(p, c) == 0:
            print("      ! 缺 %s" % c)
            bad += 1
    if count(p, "SaveImage") != 1:
        print("      ! 同时只该跑一条出图管线，实际 SaveImage=%d"
              % count(p, "SaveImage"))
        bad += 1
    live_saves = [n for n in by_role(w0, "save") if n.get("mode", 0) == 0]
    if len(live_saves) != 1:
        print("      ! 工作流文件里该只有一条管线是活的，实际 %d 条" % len(live_saves))
        bad += 1
    if "WanImageToVideo" in classes(p) or "CreateVideo" in classes(p):
        print("      ! 默认不该跑视频")
        bad += 1
    for k, nid in (("clip", "112"), ("vae", "113")):
        ent = p.get(nid)
        if not ent or ent["inputs"].get("Input") != 1:
            print("      ! 默认（SDXL）下 %s 来源开关应为 1，实际 %s"
                  % (k, (ent or {}).get("inputs", {}).get("Input")))
            bad += 1

    # 2 文生图 + 全部模块
    w2 = copy.deepcopy(wf)
    pick_pipeline(w2, "t2i")
    for key in ("pose_sdxl", "detailer", "upscale"):
        set_module(w2, key, True)
    p, ok = sim(w2, oi, "文生图 + 姿势/手眼/高清")
    bad += not ok
    for c in ["ControlNetLoader", "SetUnionControlNetType",
              "ControlNetApplyAdvanced", "UltralyticsDetectorProvider",
              "FaceDetailer", "CR Upscale Image",
              "UltimateSDUpscaleNoUpscale", "ColorMatch",
              "OpenposePreprocessor"]:
        if count(p, c) == 0:
            print("      ! 缺 %s" % c)
            bad += 1
    # 收尾那段「再 4xUltrasharp 一次 + 缩回 1/4」v6.4 已删掉：
    # 4x 放大模型只该跑一次（「先放大」那步），跑两遍会把栅格放大成网纹
    if count(p, "ImageUpscaleWithModel") != 0:
        print("      ! 不该再有收尾的第二次 4x 放大，实际 %d 处"
              % count(p, "ImageUpscaleWithModel"))
        bad += 1
    if count(p, "FaceDetailer") != 3:
        print("      ! FaceDetailer 应为 3 级，实际 %d" % count(p, "FaceDetailer"))
        bad += 1

    # 3 切 ANIMA
    w3 = copy.deepcopy(w2)
    if not apply_model_preset(w3, oi, "oneObsession_anima29BV1.safetensors"):
        print("      ! anima 预设没识别")
        bad += 1
    set_module(w3, "pose_anima", True)
    set_module(w3, "pose_sdxl", False)
    p, ok = sim(w3, oi, "ANIMA（LLLite 姿势）")
    bad += not ok
    for c in ("ModelPatchLoader", "AnimaLLLiteApply"):
        if count(p, c) == 0:
            print("      ! 缺 %s" % c)
            bad += 1
    if count(p, "CLIPSetLastLayer") != 0:
        print("      ! ANIMA 下 CLIPSetLastLayer 应被旁路")
        bad += 1
    if count(p, "ControlNetApplyAdvanced") != 0:
        print("      ! ANIMA 下不该用 SDXL ControlNet")
        bad += 1
    # 只认「文生图子图」里那台采样器：高清模块的「整体细化」是独立配方
    # （12 步 / CFG 6.0），不该跟着模型族预设走
    t2i_entry = p.get("201:2")
    if not t2i_entry or t2i_entry.get("class_type") != "KSampler":
        print("      ! 找不到文生图采样器，现有 KSampler：%s"
              % [(k, (e.get("_meta") or {}).get("title")) for k, e in p.items()
                 if e.get("class_type") == "KSampler"])
        bad += 1
    else:
        for fld, want in (("steps", 30), ("cfg", 4.5)):
            got = linked_value(p, t2i_entry, fld)
            if got != want:
                print("      ! ANIMA %s 应为 %s，实际 %s" % (fld, want, got))
                bad += 1
    # ANIMA 裸 DiT：文本编码器 / VAE 必须来自 110 / 111，开关在 2
    for cls, fld, want in (("CLIPLoader", "clip_name",
                            "qwen_3_06b_base.safetensors"),
                           ("VAELoader", "vae_name",
                            "wan_2.1_vae.safetensors")):
        _k, ent = entry_of(p, cls)
        got = (ent or {}).get("inputs", {}).get(fld)
        if got != want:
            print("      ! ANIMA 应由 %s 供 %s=%s，实际 %s"
                  % (cls, fld, want, got))
            bad += 1
    for k, nid in (("clip", "112"), ("vae", "113")):
        ent = p.get(nid)
        if not ent or ent["inputs"].get("Input") != 2:
            print("      ! ANIMA 下 %s 来源开关应切到 2，实际 %s"
                  % (k, (ent or {}).get("inputs", {}).get("Input")))
            bad += 1

    # 4 图生图
    w4 = copy.deepcopy(wf)
    pick_pipeline(w4, "i2i")
    p, ok = sim(w4, oi, "图生图精修")
    bad += not ok
    for c in ["LoadImageOutput", "VAEEncode", "KSampler", "VAEDecode",
              "SaveImage"]:
        if count(p, c) == 0:
            print("      ! 缺 %s" % c)
            bad += 1
    k, e = entry_of(p, "SaveImage")
    if e and e["inputs"].get("filename_prefix") != "refine":
        print("      ! 图生图应存 refine_*，实际 %s"
              % e["inputs"].get("filename_prefix"))
        bad += 1

    # 5 I2V
    w5 = copy.deepcopy(wf)
    pick_pipeline(w5, "i2v")
    p, ok = sim(w5, oi, "图生视频 I2V")
    bad += not ok
    for c in ["UNETLoader", "CLIPLoader", "VAELoader", "WanImageToVideo",
              "KSamplerAdvanced", "CreateVideo", "SaveVideo",
              "ModelSamplingSD3"]:
        if count(p, c) == 0:
            print("      ! 缺 %s" % c)
            bad += 1
    if count(p, "UNETLoader") != 2:
        print("      ! 应加载 high/low 两个 UNET，实际 %d" % count(p, "UNETLoader"))
        bad += 1
    loras = [e for e in p.values()
             if e["class_type"] == "Power Lora Loader (rgthree)"]
    pre = [v for e in loras for k, v in e["inputs"].items()
           if k.startswith("lora_") and v.get("on")]
    if len(pre) != 2 or not all("lightx2v" in str(x.get("lora"))
                                for x in pre):
        print("      ! 视频 4 步加速 LoRA 没预挂：%s" % pre)
        bad += 1

    # 6 FLF2V
    w6 = copy.deepcopy(wf)
    pick_pipeline(w6, "flf2v")
    p, ok = sim(w6, oi, "首尾帧 FLF2V")
    bad += not ok
    if count(p, "WanFirstLastFrameToVideo") == 0:
        print("      ! 缺 WanFirstLastFrameToVideo")
        bad += 1

    # 7 T2V
    w7 = copy.deepcopy(wf)
    pick_pipeline(w7, "t2v")
    p, ok = sim(w7, oi, "文生视频 T2V")
    bad += not ok
    for c in ["CheckpointLoaderSimple", "EmptyHunyuanLatentVideo", "KSampler",
              "CreateVideo", "SaveVideo"]:
        if count(p, c) == 0:
            print("      ! 缺 %s" % c)
            bad += 1
    if count(p, "UNETLoader") != 0:
        print("      ! T2V 不该用分离式 UNET")
        bad += 1

    # 7b 视频后处理（v6.6）：视频高清化 → 视频补帧 → 封装 → 存盘
    # 全关时：两张后处理节点一个都不该跑，帧 / 帧率原样透传到封装步
    w7b = modules_all_off(copy.deepcopy(wf))
    pick_pipeline(w7b, "i2v")
    p_off, ok = sim(w7b, oi, "I2V · 后处理全关")
    bad += not ok
    for c in ("RIFE_VFI_Opt", "UpscaleWithModelAdvanced", "ImageScaleBy",
              "UpscaleModelLoader", "CM_FloatToInt JK"):
        if count(p_off, c):
            print("      ! 后处理关着时不该跑 %s（实际 %d 个）"
                  % (c, count(p_off, c)))
            bad += 1
    if count(p_off, "CreateVideo") != 1 or count(p_off, "SaveVideo") != 1:
        print("      ! 后处理关着时也该有 1 个封装 + 1 个存盘，实际 %d / %d"
              % (count(p_off, "CreateVideo"), count(p_off, "SaveVideo")))
        bad += 1
    else:
        cv = entry_of(p_off, "CreateVideo")[1]
        if cv["inputs"].get("images") != ["431:4", 0]:
            print("      ! 旁路时封装该直接吃管线解出来的帧，实际 %s"
                  % cv["inputs"].get("images"))
            bad += 1
        if cv["inputs"].get("fps") != ["424", 0]:
            print("      ! 旁路时帧率该原样透传参数 424，实际 %s"
                  % cv["inputs"].get("fps"))
            bad += 1

    # 7c 两个模块全开：高清（逐帧放大 + 缩回目标）→ 补帧（插帧 + 帧率×倍数）
    w7c = modules_all_off(copy.deepcopy(wf))
    pick_pipeline(w7c, "i2v")
    set_module(w7c, "vupscale", True)
    set_module(w7c, "vfi", True)
    p_on, ok = sim(w7c, oi, "I2V + 视频高清化 + 视频补帧")
    bad += not ok
    for c in ("UpscaleModelLoader", "UpscaleWithModelAdvanced", "ImageScaleBy",
              "RIFE_VFI_Opt", "CM_FloatBinaryOperation JK", "CM_FloatToInt JK",
              "CreateVideo", "SaveVideo"):
        if count(p_on, c) == 0:
            print("      ! 缺 %s" % c)
            bad += 1
    if count(p_on, "RIFE_VFI_Opt") != 1 or count(p_on, "UpscaleWithModelAdvanced") != 1:
        print("      ! 只该跑 1 套后处理，实际 RIFE=%d 放大=%d"
              % (count(p_on, "RIFE_VFI_Opt"),
                 count(p_on, "UpscaleWithModelAdvanced")))
        bad += 1
    # 高清链：帧 → 逐帧放大 → 缩到目标（系数 = 目标倍数 ÷ 模型倍率）
    up = p_on.get("492:2")
    if not up or up["class_type"] != "UpscaleWithModelAdvanced":
        print("      ! 找不到视频放大节点")
        bad += 1
    else:
        ui = up["inputs"]
        if ui.get("image") != ["431:4", 0]:
            print("      ! 放大该吃管线解出来的帧，实际 %s" % ui.get("image"))
            bad += 1
        for name, pid in (("max_batch_size", 484), ("tile_size", 485)):
            if ui.get(name) != [str(pid), 0]:
                print("      ! %s 该接参数节点 %d，实际 %s" % (name, pid, ui.get(name)))
                bad += 1
    sc = p_on.get("492:3")
    if not sc or sc["class_type"] != "CM_FloatBinaryOperation JK":
        print("      ! 缩放系数该由浮点运算节点算出来")
        bad += 1
    else:
        si = sc["inputs"]
        if si.get("op") != "Div" or si.get("a") != ["482", 0] \
                or si.get("b") != ["483", 0]:
            print("      ! 缩放系数应是「目标倍数(482) ÷ 模型倍率(483)」，实际 %s" % si)
            bad += 1
    rs = p_on.get("492:4")
    if not rs or rs["class_type"] != "ImageScaleBy" \
            or rs["inputs"].get("scale_by") != ["492:3", 0]:
        print("      ! 缩到目标尺寸该吃缩放系数节点，实际 %s"
              % ((rs or {}).get("inputs") or {}).get("scale_by"))
        bad += 1
    # 补帧链：吃高清化的输出 → RIFE；倍数经「浮点→整数」转换（RIFE 只吃整数）
    rf = p_on.get("491:1")
    if not rf or rf["class_type"] != "RIFE_VFI_Opt":
        print("      ! 找不到 RIFE 节点")
        bad += 1
    else:
        ri = rf["inputs"]
        if ri.get("frames") != ["492:4", 0]:
            print("      ! 补帧该吃高清化出来的帧，实际 %s" % ri.get("frames"))
            bad += 1
        if ri.get("multiplier") != ["491:3", 0]:
            print("      ! 补帧倍数该由 491:3 转成整数，实际 %s" % ri.get("multiplier"))
            bad += 1
        if ri.get("ckpt_name") != "rife47.pth":
            print("      ! RIFE 权重应默认 rife47.pth，实际 %s" % ri.get("ckpt_name"))
            bad += 1
    conv = p_on.get("491:3")
    if not conv or conv["inputs"].get("a") != ["481", 0]:
        print("      ! 倍数转换节点该吃参数 481，实际 %s"
              % ((conv or {}).get("inputs") or {}).get("a"))
        bad += 1
    # 帧率：× 倍数由浮点乘法算，参数 424 与 481 一起进去；封装吃这个结果
    mul = p_on.get("491:2")
    if not mul or mul["class_type"] != "CM_FloatBinaryOperation JK" \
            or mul["inputs"].get("op") != "Mul" \
            or mul["inputs"].get("a") != ["424", 0] \
            or mul["inputs"].get("b") != ["481", 0]:
        print("      ! 帧率该 = 424（帧率）× 481（倍数），实际 %s"
              % ((mul or {}).get("inputs") or {}))
        bad += 1
    cv_on = entry_of(p_on, "CreateVideo")[1]
    if cv_on["inputs"].get("images") != ["491:1", 0]:
        print("      ! 封装该吃补完帧的输出，实际 %s" % cv_on["inputs"].get("images"))
        bad += 1
    if cv_on["inputs"].get("fps") != ["491:2", 0]:
        print("      ! 封装帧率该吃「帧率 × 倍数」，实际 %s"
              % cv_on["inputs"].get("fps"))
        bad += 1
    # 补帧只在链子上下游乘一次，参数节点本身（424）不该被改写
    if one(w7c, "param", "video_fps")["widgets_values"][0] != 16.0:
        print("      ! 视频帧率参数不该被补帧改写")
        bad += 1

    # 7d 只开补帧 / 只开高清化：两条链互不牵连
    w7d = modules_all_off(copy.deepcopy(wf))
    pick_pipeline(w7d, "flf2v")
    set_module(w7d, "vfi", True)
    p_vfi, ok = sim(w7d, oi, "首尾帧 · 只开补帧")
    bad += not ok
    if count(p_vfi, "RIFE_VFI_Opt") != 1 or count(p_vfi, "UpscaleWithModelAdvanced"):
        print("      ! 只开补帧时该跑 1 个 RIFE、0 个放大，实际 %d / %d"
              % (count(p_vfi, "RIFE_VFI_Opt"),
                 count(p_vfi, "UpscaleWithModelAdvanced")))
        bad += 1
    if p_vfi.get("493:1", {}).get("inputs", {}).get("frames") != ["441:4", 0]:
        print("      ! 高清关着时补帧该直接吃管线的帧，实际 %s"
              % (p_vfi.get("493:1", {}).get("inputs", {}).get("frames")))
        bad += 1
    if entry_of(p_vfi, "CreateVideo")[1]["inputs"].get("fps") != ["493:2", 0]:
        print("      ! 只开补帧时帧率也要走 × 倍数")
        bad += 1
    w7e = modules_all_off(copy.deepcopy(wf))
    pick_pipeline(w7e, "t2v")
    set_module(w7e, "vupscale", True)
    p_up, ok = sim(w7e, oi, "文生视频 · 只开视频高清化")
    bad += not ok
    if count(p_up, "UpscaleWithModelAdvanced") != 1 or count(p_up, "RIFE_VFI_Opt"):
        print("      ! 只开高清时该跑 1 个放大、0 个 RIFE，实际 %d / %d"
              % (count(p_up, "UpscaleWithModelAdvanced"),
                 count(p_up, "RIFE_VFI_Opt")))
        bad += 1
    # 补帧关着 → 帧率不走乘法，直接透传 424（否则视频会变速）
    if entry_of(p_up, "CreateVideo")[1]["inputs"].get("fps") != ["424", 0]:
        print("      ! 补帧关着时帧率必须原样透传，实际 %s"
              % entry_of(p_up, "CreateVideo")[1]["inputs"].get("fps"))
        bad += 1
    if entry_of(p_up, "CreateVideo")[1]["inputs"].get("images") != ["496:4", 0]:
        print("      ! 高清开着时封装该吃放大后的帧，实际 %s"
              % entry_of(p_up, "CreateVideo")[1]["inputs"].get("images"))
        bad += 1

    # 8 图生图 + 视频 同开
    w8 = copy.deepcopy(wf)
    for n in by_role(w8, "save"):
        n["mode"] = 0 if (n["properties"] or {}).get("cc_dock_key") in (
            "i2i", "i2v") else 2
    p, ok = sim(w8, oi, "图生图 + I2V 同开")
    bad += not ok
    if count(p, "SaveImage") != 1 or count(p, "SaveVideo") != 1:
        print("      ! 应各一个保存节点，实际 image=%d video=%d"
              % (count(p, "SaveImage"), count(p, "SaveVideo")))
        bad += 1

    # 9 LoRA 行
    w9 = copy.deepcopy(wf)
    lora = one(w9, "lora_group", "image")
    rows = lora["widgets_values"]
    # rgthree 的 Power Lora Loader 里，只有带 "lora" 键的才是真正的 LoRA 行
    # （前后还有分隔用的空 widget 和表头 widget）
    ridx = [i for i, r in enumerate(rows)
            if isinstance(r, dict) and "lora" in r]
    if len(ridx) < 8:
        print("      ! 图像 LoRA 至少应有 8 行，实际 %d" % len(ridx))
        bad += 1
    rows[ridx[0]] = {"lora": "test_style.safetensors", "on": True, "strength": 0.8}
    rows[ridx[1]] = {"lora": "off_row.safetensors", "on": False, "strength": 1.0}
    p, ok = sim(w9, oi, "图像 LoRA 行")
    bad += not ok
    k, e = entry_of(p, "Power Lora Loader (rgthree)")
    loras = {n: v for n, v in e["inputs"].items() if n.startswith("lora_")}
    if len(loras) != len(ridx):
        print("      ! 应传出全部 %d 行 lora 输入，实际 %d"
              % (len(ridx), len(loras)))
        bad += 1
    if loras.get("lora_1", {}).get("strength") != 0.8:
        print("      ! lora_1 强度没传对：%s" % loras.get("lora_1"))
        bad += 1
    if (loras.get("lora_1", {}).get("on") is not True
            or loras.get("lora_2", {}).get("on") is not False):
        print("      ! LoRA 行的 on 没传对：1=%s 2=%s"
              % (loras.get("lora_1", {}).get("on"),
                 loras.get("lora_2", {}).get("on")))
        bad += 1

    # 9b 随机种子：参数节点进 prompt，控制 widget 不序列化
    seed_ent = p.get("125")
    if not seed_ent:
        print("      ! 图像种子节点没进 prompt")
        bad += 1
    elif "control_after_generate" in seed_ent["inputs"]:
        print("      ! 种子的控制项不该进 prompt：%s" % seed_ent["inputs"].keys())
        bad += 1
    if one(wf, "param", "seed")["widgets_values"][1] != "randomize":
        print("      ! 图像种子默认应为 randomize（面板默认随机）")
        bad += 1
    if one(wf, "param", "video_seed")["widgets_values"][1] != "randomize":
        print("      ! 视频种子默认应为 randomize")
        bad += 1

    # 10 模块逐个开关
    # 基线用「模块全关」，不跟着画布上当前留着哪些模块转
    base = sim(modules_all_off(copy.deepcopy(wf)), oi, "基线（模块全关）")[0]
    for key in ("pose_sdxl", "detailer", "upscale"):
        w10 = modules_all_off(copy.deepcopy(wf))
        set_module(w10, key, True)
        p_on, ok1 = sim(w10, oi, "单开模块 %s" % key)
        p_off, ok2 = sim(modules_all_off(copy.deepcopy(wf)), oi,
                         "单关模块 %s" % key)
        bad += (not ok1) + (not ok2)
        if classes(p_off) != classes(base):
            print("      ! 关掉 %s 后执行集合与基线不一致" % key)
            bad += 1
        if set(p_on) == set(p_off):
            print("      ! 打开 %s 没产生任何影响" % key)
            bad += 1

    # 10b 脸手眼矫正参数：面板上那 6 个值真的接到了三级 FaceDetailer
    w10b = modules_all_off(copy.deepcopy(wf))
    set_module(w10b, "detailer", True)
    p10b, ok = sim(w10b, oi, "脸手眼矫正参数（阈值 / 羽化 / 三级重绘）")
    bad += not ok
    fds = [e for e in p10b.values() if e.get("class_type") == "FaceDetailer"]
    if len(fds) != 3:
        print("      ! 该跑三级 FaceDetailer，实际 %d" % len(fds))
        bad += 1
    else:
        refs = {}
        for e in fds:
            for name in ("denoise", "feather", "bbox_threshold",
                         "guide_size", "max_size", "bbox_crop_factor"):
                refs.setdefault(name, []).append(e["inputs"].get(name))

        def ref_of(v):
            return str(v[0]) if isinstance(v, list) and v else str(v)

        # 脸 / 手 共用一个阈值参数，眼单独一个（1295）；羽化三级共用；重绘三级各一个；
        # v6.5 起「检测框放大尺寸 / 放大上限 / 裁剪倍率」（137/138/139）也三级共用
        want = {"bbox_threshold": ["1295", "130"], "feather": ["131"],
                "denoise": ["132", "133", "134"],
                "guide_size": ["137"], "max_size": ["138"],
                "bbox_crop_factor": ["139"]}
        for name, ids in want.items():
            got = sorted({ref_of(v) for v in refs.get(name, [])})
            if got != sorted(ids):
                print("      ! %s 应接参数节点 %s，实际 %s"
                      % (name, ids, refs.get(name)))
                bad += 1
        # v6.4 的稳定守则：detailer 不许再出现「cfg 8 + euler/normal + 裁剪 ×3 + 羽化 5」
        # 那一组在 SDXL / ANIMA 上会把脸和头发画成栅格网纹（画面被修烂）
        for e in fds:
            ins = e.get("inputs") or {}
            title = (e.get("_meta") or {}).get("title", "?")
            if ins.get("sampler_name") != "dpmpp_2m" or ins.get("scheduler") != "karras":
                print("      ! %s 的采样器应为 dpmpp_2m/karras，实际 %s/%s"
                      % (title, ins.get("sampler_name"), ins.get("scheduler")))
                bad += 1
            cfg = ins.get("cfg")
            if not isinstance(cfg, (int, float)) or float(cfg) > 5.0:
                print("      ! %s 的 cfg=%s 偏高（会过饱和 / 发红），应 ≤ 5.0" % (title, cfg))
                bad += 1
            # 裁剪范围现在从参数节点 139 进来，得顺着连线取真实数值
            crop = (linked_value(p10b, e, "bbox_crop_factor")
                    if "bbox_crop_factor" in ins else None)
            if not isinstance(crop, (int, float)) or float(crop) > 2.5:
                print("      ! %s 的裁剪范围 ×%s 偏大（重画面积过大），应 ≤ 2.5"
                      % (title, crop))
                bad += 1
            # v6.5：guide 必须回到 512 档（1024 会把小脸放大 2~5 倍再采样，
            # 模型在裁剪区里画「整张脸 + 头发 + 肩膀」，缩回去就是「脸被贴上去」）
            gd = (linked_value(p10b, e, "guide_size")
                  if "guide_size" in ins else None)
            if not isinstance(gd, (int, float)) or float(gd) > 768:
                print("      ! %s 的检测框放大尺寸 %s 偏大（脸会被放大重画后贴回），应 ≤ 768"
                      % (title, gd))
                bad += 1
            ms = (linked_value(p10b, e, "max_size")
                  if "max_size" in ins else None)
            if not isinstance(ms, (int, float)) or float(ms) > 1536:
                print("      ! %s 的放大上限 %s 偏大，应 ≤ 1536" % (title, ms))
                bad += 1
            dn = linked_value(p10b, e, "denoise") if "denoise" in ins else None
            # 画布上的值会被结转（用户自己调过），所以只卡「极端值」；
            # 常规安全区由面板默认值那道检查（见 [13]）负责
            if isinstance(dn, (int, float)) and float(dn) > 0.80:
                print("      ! %s 的重绘强度 %s 高到会改内容了（>0.80）" % (title, dn))
                bad += 1
            elif isinstance(dn, (int, float)) and float(dn) > 0.55:
                print("      [提示] %s 的重绘强度 %s 偏高（>0.55 开始会改内容）"
                      % (title, dn))
            ft = linked_value(p10b, e, "feather") if "feather" in ins else None
            if isinstance(ft, (int, float)) and float(ft) < 8:
                print("      ! %s 的羽化 %s 硬到会露出方块拼接痕（<8）" % (title, ft))
                bad += 1
            elif isinstance(ft, (int, float)) and float(ft) < 16:
                print("      [提示] %s 的羽化 %s 偏硬（<16 容易出现方块痕）" % (title, ft))
        if count(p10b, "ColorMatch") != 1:
            print("      ! 脸手眼矫正子图里该有 1 个色彩回正，实际 %d"
                  % count(p10b, "ColorMatch"))
            bad += 1

    # 10b2 三级独立开关 + SAM（v6.5）：关掉的那一级走旁路，图穿过去、链子不断
    def set_stage(w, key, mode):
        hit = 0
        for sg in (w.get("definitions") or {}).get("subgraphs") or []:
            for node in sg.get("nodes") or []:
                pr = node.get("properties") or {}
                if pr.get("cc_dock_role") == "detailer_stage" \
                        and pr.get("cc_dock_key") == key:
                    node["mode"] = mode
                    hit += 1
        return hit

    def set_sam(w, mode):
        hit = 0
        for sg in (w.get("definitions") or {}).get("subgraphs") or []:
            for node in sg.get("nodes") or []:
                pr = node.get("properties") or {}
                if pr.get("cc_dock_role") == "detailer_sam" \
                        and pr.get("cc_dock_key") == "sam":
                    node["mode"] = mode
                    hit += 1
        return hit

    for k in ("face", "hand", "eye"):
        if set_stage(copy.deepcopy(wf), k, 4) < 1:
            print("      ! 子图里找不到 stage=%s 的 FaceDetailer（面板开关接不上）" % k)
            bad += 1
    if set_sam(copy.deepcopy(wf), 0) < 1:
        print("      ! 子图里找不到 SAMLoader（面板 SAM 开关接不上）")
        bad += 1

    # (a) 只留脸：手 / 眼旁路 → 只剩 1 个 FaceDetailer
    w10d = modules_all_off(copy.deepcopy(wf))
    set_module(w10d, "detailer", True)
    set_stage(w10d, "hand", 4)
    set_stage(w10d, "eye", 4)
    p10d, ok = sim(w10d, oi, "只留脸（手 / 眼旁路）")
    bad += not ok
    if count(p10d, "FaceDetailer") != 1:
        print("      ! 只留脸时该跑 1 个 FaceDetailer，实际 %d" % count(p10d, "FaceDetailer"))
        bad += 1
    if count(p10d, "UltralyticsDetectorProvider") != 1:
        print("      ! 只留脸时只该加载 1 个检测器，实际 %d"
              % count(p10d, "UltralyticsDetectorProvider"))
        bad += 1

    # (b) 三级全关：一个 FaceDetailer 都不跑，链子照样通（色彩回正还在）
    w10e = modules_all_off(copy.deepcopy(wf))
    set_module(w10e, "detailer", True)
    for k in ("face", "hand", "eye"):
        set_stage(w10e, k, 4)
    p10e, ok = sim(w10e, oi, "三级全关（整块等于没开）")
    bad += not ok
    if count(p10e, "FaceDetailer") or count(p10e, "UltralyticsDetectorProvider"):
        print("      ! 三级全关时不该跑 FaceDetailer / 检测器")
        bad += 1

    # (c) SAM：开着 → SAMLoader 进 prompt 且 sam_model_opt 有连线；关掉 → 两者都没了
    w10f = modules_all_off(copy.deepcopy(wf))
    set_module(w10f, "detailer", True)
    p10f, ok = sim(w10f, oi, "SAM 轮廓遮罩（开）")
    bad += not ok
    if count(p10f, "SAMLoader") != 1:
        print("      ! SAM 开着时该加载 1 个 SAMLoader，实际 %d" % count(p10f, "SAMLoader"))
        bad += 1
    for e in [x for x in p10f.values() if x.get("class_type") == "FaceDetailer"]:
        if "sam_model_opt" not in (e.get("inputs") or {}):
            print("      ! %s 没接上 sam_model_opt" % (e.get("_meta") or {}).get("title"))
            bad += 1
    set_sam(w10f, 2)
    p10g, ok = sim(w10f, oi, "SAM 轮廓遮罩（关）")
    bad += not ok
    if count(p10g, "SAMLoader"):
        print("      ! SAM 关掉后不该再加载 SAMLoader")
        bad += 1
    for e in [x for x in p10g.values() if x.get("class_type") == "FaceDetailer"]:
        if "sam_model_opt" in (e.get("inputs") or {}):
            print("      ! %s 关掉 SAM 后不该再有 sam_model_opt"
                  % (e.get("_meta") or {}).get("title"))
            bad += 1

    # 10c 高清化：整体细化 + 分块精修的分块参数（防「拼图感」）
    w10c = modules_all_off(copy.deepcopy(wf))
    set_module(w10c, "upscale", True)
    p10c, ok = sim(w10c, oi, "高清化参数（整体细化 + 接缝修复）")
    bad += not ok
    ks = [(k, e) for k, e in p10c.items()
          if e.get("class_type") == "KSampler"
          and "整体细化" in (e.get("_meta") or {}).get("title", "")]
    if len(ks) != 1:
        print("      ! 该跑 1 个「整体细化」KSampler，实际 %d" % len(ks))
        bad += 1
    else:
        ka = ks[0][1]["inputs"]
        for name in ("model", "positive", "negative", "latent_image"):
            if name not in ka:
                print("      ! 整体细化缺 %s" % name)
                bad += 1
        # 这个值面板上可以自己调（默认 0.12），画布上的值会被结转，所以只卡「安全区间」：
        # 0.05~0.20 之间是「只加细节、不改内容」；超过就容易改内容了
        ka_dn = linked_value(p10c, ks[0][1], "denoise")
        if not isinstance(ka_dn, (int, float)) or not (0.03 <= float(ka_dn) <= 0.20):
            print("      ! 整体细化 denoise=%s 超出稳当区间 0.03~0.20" % (ka_dn,))
            bad += 1
    ud = [(k, e) for k, e in p10c.items()
          if e.get("class_type") == "UltimateSDUpscaleNoUpscale"]
    if len(ud) != 1:
        print("      ! 该跑 1 个分块精修，实际 %d" % len(ud))
        bad += 1
    else:
        ui = ud[0][1]["inputs"]
        # 这两个值由面板参数节点（1291 接缝修复 / 129 精修）提供。
        # 注意：画布上被用户改过的值会在重建时结转，所以这里只卡范围，
        # 「默认值」由面板的 PARAM_DEFAULTS 决定（见 [13] 面板测试）。
        for name, pkey, lo, hi in (("denoise", "upscale_denoise", 0.05, 0.20),
                                   ("seam_fix_denoise", "upscale_seam_fix",
                                    0.15, 0.50)):
            got = ui.get(name)
            if not isinstance(got, list):
                print("      ! 分块精修的 %s 应接参数节点，实际 %s" % (name, got))
                bad += 1
                continue
            pnode = one(w10c, "param", pkey)
            expect = str(pnode["id"])
            if str(got[0]) != expect:
                print("      ! %s 应接参数节点 %s（%s），实际接 %s"
                      % (name, expect, pkey, got[0]))
                bad += 1
            cur = pnode.get("widgets_values", [None])[0]
            if not isinstance(cur, (int, float)) or not (lo <= float(cur) <= hi):
                print("      ! 参数 %s=%s 超出稳妥范围 %s~%s（出拼图感就调这个）"
                      % (pkey, cur, lo, hi))
                bad += 1
        ka_denoise = one(w10c, "param", "upscale_whole_denoise")
        cur = float(ka_denoise.get("widgets_values", [None])[0])
        if not (0.03 <= cur <= 0.20):
            print("      ! 参数 upscale_whole_denoise=%s 超出稳当区间 0.03~0.20" % cur)
            bad += 1
        for name, want in (("sampler_name", "dpmpp_2m"),
                           ("scheduler", "karras"),
                           ("seam_fix_mode", "Half Tile + Intersections"),
                           ("tile_padding", 48), ("mask_blur", 16)):
            if ui.get(name) != want:
                print("      ! 分块精修 %s 应为 %r，实际 %r"
                      % (name, want, ui.get(name)))
                bad += 1
        if float(ui.get("cfg", 0)) > 7.0:
            print("      ! 分块精修 CFG 偏高（%s），块与块容易长歪" % ui.get("cfg"))
            bad += 1

    # 10c2 采样器 / 调度器：面板「参数」里那两个下拉写的就是子图里这两格
    w10s = modules_all_off(copy.deepcopy(wf))
    pick_pipeline(w10s, "t2i")
    touched = 0
    for sub in (w10s.get("definitions") or {}).get("subgraphs") or []:
        if sub.get("name") not in ("文生图", "图生图精修"):
            continue
        for node in sub.get("nodes") or []:
            if node.get("type") != "KSampler":
                continue
            set_widget_of(node, "sampler_name", "uni_pc", oi["KSampler"])
            set_widget_of(node, "scheduler", "sgm_uniform", oi["KSampler"])
            touched += 1
    p10s, ok = sim(w10s, oi, "采样器 / 调度器下拉（文生图 + 图生图共用）")
    bad += not ok
    ent = p10s.get("201:2")
    if touched != 2 or not ent or ent.get("class_type") != "KSampler":
        print("      ! 该改 2 台图像采样器，实际 %d（entry=%s）"
              % (touched, bool(ent)))
        bad += 1
    else:
        for fld, want in (("sampler_name", "uni_pc"),
                          ("scheduler", "sgm_uniform")):
            got = ent["inputs"].get(fld)
            if got != want:
                print("      ! 文生图采样器的 %s 应为 %s，实际 %s"
                      % (fld, want, got))
                bad += 1
    # 高清化的「整体细化」是独立配方，不该被面板的采样器下拉带跑
    for sub in (w10s.get("definitions") or {}).get("subgraphs") or []:
        if sub.get("name") != "高清化":
            continue
        for node in sub.get("nodes") or []:
            if node.get("type") != "KSampler":
                continue
            names = widget_names(oi["KSampler"])
            wv = node.get("widgets_values") or []
            got = wv[names.index("sampler_name")] if len(wv) > names.index(
                "sampler_name") else None
            if got != "dpmpp_2m":
                print("      ! 高清化的整体细化不该跟着换采样器，实际 %s" % got)
                bad += 1

    # 10d 高清倍数语义 + 分块自适配：填 2 就是 2 倍，链子里只放大一次
    try:
        from blueprint import generator as _gen
        want_default = _gen.auto_tile_size(1216, 832, 2.0)
        if _gen.DEFAULT_TILE != want_default or want_default != 1216:
            print("      ! 生成器默认分块 %s 与公式 %s 不符（1216×832 × 2 → 1216）"
                  % (_gen.DEFAULT_TILE, want_default))
            bad += 1
        else:
            print("  [分块公式] OK  1216×832 × 2 → 分块 %d（对齐 64，限 %d~%d）"
                  % (want_default, _gen.TILE_MIN, _gen.TILE_MAX))
    except Exception as exc:
        print("      ! 读不到 blueprint/generator.py 的分块公式：%s" % exc)
        bad += 1

    w10d = modules_all_off(copy.deepcopy(wf))
    set_module(w10d, "upscale", True)
    pick_pipeline(w10d, "i2i")
    set_mode(w10d, one(w10d, "save", "t2i")["id"], 0)   # 文生图 + 图生图 两条链同开
    p10d, ok = sim(w10d, oi, "高清倍数（两条链都只放大一次）")
    bad += not ok
    # 只该有一处「放大倍数」：CR Upscale Image（rescale_factor 接参数 128）。
    # 结尾那段 4xUltrasharp + 缩回 1/4 v6.4 已删（它会把栅格放大成网纹，还白跑一遍算力）
    up = [(k, e) for k, e in p10d.items()
          if e.get("class_type") == "CR Upscale Image"]
    if len(up) != 2:
        print("      ! 两条图像链该各有一处「先放大」，实际 %d" % len(up))
        bad += 1
    for k, e in up:
        si = e.get("inputs") or {}
        if si.get("mode") != "rescale" or not isinstance(si.get("rescale_factor"), list):
            print("      ! %s 应按倍数缩放且倍数接参数节点，实际 %s / %s"
                  % (k, si.get("mode"), si.get("rescale_factor")))
            bad += 1
    if count(p10d, "ImageUpscaleWithModel") != 0:
        print("      ! 不该再有第二次 4x 放大（收尾那段已删），实际 %d 处"
              % count(p10d, "ImageUpscaleWithModel"))
        bad += 1
    if count(p10d, "ColorMatch") != 2:
        print("      ! 两条图像链该各有一处色彩回正（高清化里），实际 %d"
              % count(p10d, "ColorMatch"))
        bad += 1
    if count(p10d, "ImageScaleBy") != 0:
        print("      ! 不该再有「缩回 1/4」那一步（旧 4 倍链的一半），实际 %d 处"
              % count(p10d, "ImageScaleBy"))
        bad += 1
    # CR 的 supersample 必须关：上游本来就是 4x 放大模型的大图，
    # 再「先放 8 倍再缩回来」纯烧显存（2048 → 16384 那一下要几个 G），结果还更糊
    sup_bad = [k for k, e in up
               if (e.get("inputs") or {}).get("supersample") != "false"]
    if sup_bad or len(up) != 2:
        print("      ! CR Upscale Image 的 supersample 该是 false，实际有问题的是 %s"
              % sup_bad)
        bad += 1
    else:
        print("  [高清 supersample] OK  两条链都关了「先放 8 倍再缩回」")

    tile_p = one(w10d, "param", "upscale_tile")
    tp = tile_p.get("widgets_values", [None])[0]
    if not isinstance(tp, (int, float)) or not (1024 <= float(tp) <= 1536) or float(tp) % 64:
        print("      ! 分块参数 %s 应在 1024~1536 且对齐 64，实际 %s" % (tile_p["id"], tp))
        bad += 1
    ud_all = [(k, e) for k, e in p10d.items()
              if e.get("class_type") == "UltimateSDUpscaleNoUpscale"]
    if len(ud_all) != 2:
        print("      ! 两条图像链该各有一个分块精修，实际 %d" % len(ud_all))
        bad += 1
    for k, e in ud_all:
        si = e.get("inputs") or {}
        for name in ("tile_width", "tile_height"):
            got = si.get(name)
            if not isinstance(got, list) or str(got[0]) != str(tile_p["id"]):
                print("      ! %s 的 %s 应接参数节点 %s（分块大小），实际 %s"
                      % (k, name, tile_p["id"], got))
                bad += 1
        tw, th = si.get("tile_width"), si.get("tile_height")
        if isinstance(tw, list) and isinstance(th, list) and tw[0] != th[0]:
            print("      ! %s 的分块长宽不一致：%s / %s" % (k, tw, th))
            bad += 1

    # 11 分段提示词总线：8 段拼接 + 每段「手填 / 插件」二选一
    w11 = copy.deepcopy(wf)
    pos = one(w11, "prompt", "image_pos")
    seg_ids = [141 + i for i in range(8)]
    for i, t in enumerate(["AAA", "BBB", "CCC"]):
        sw = node_by_id(w11, seg_ids[i])
        if sw["type"] != "CR Text Input Switch JK":
            print("      ! 第 %d 段不是二选一开关：%s" % (i + 1, sw["type"]))
            bad += 1
            continue
        set_widget_of(sw, "text_false", t, oi[sw["type"]])
        set_widget_of(sw, "text_true", t, oi[sw["type"]])
        # 画布上可能留着上次勾的「插件输入」，这里显式关掉，测的是纯手填
        set_widget_of(sw, "boolean_value", False, oi[sw["type"]])
    set_widget_of(pos, "enable2", False, oi[pos["type"]])
    p, ok = sim(w11, oi, "分段提示词（纯手填）")
    bad += not ok
    yog = p.get("104")
    if not yog:
        print("      ! 正向拼接器没进 prompt")
        bad += 1
    else:
        for i in range(3):
            sw = deref(p, "104", "text%d" % (i + 1))
            want = ["AAA", "BBB", "CCC"][i]
            ctype = sw.get("class_type") if isinstance(sw, dict) else None
            if ctype != "CR Text Input Switch JK":
                print("      ! text%d 没接到二选一开关：%s" % (i + 1, ctype))
                bad += 1
                continue
            if sw["inputs"].get("text_false") != want:
                print("      ! 第 %d 段手填文字没进 prompt：%r"
                      % (i + 1, sw["inputs"].get("text_false")))
                bad += 1
            if sw["inputs"].get("boolean_value") is not False:
                print("      ! 第 %d 段默认应走手填（boolean_value=False）：%r"
                      % (i + 1, sw["inputs"].get("boolean_value")))
                bad += 1
        if yog["inputs"].get("enable2") is not False:
            print("      ! enable2=False 没进 prompt：%r"
                  % yog["inputs"].get("enable2"))
            bad += 1

    # 插件接上：boolean 关着仍用 text_false；打开就吃 text_true 那根线
    add_string_node(w11, 9901, "PLUGIN_TEXT", "假插件")
    wire_string(w11, 9901, seg_ids[2], "text_true")
    sw3 = node_by_id(w11, seg_ids[2])
    set_widget_of(sw3, "text_false", "CCC", oi[sw3["type"]])
    p2, ok = sim(w11, oi, "分段提示词（插件关）")
    bad += not ok
    e3 = deref(p2, "104", "text3")
    if not isinstance(e3, dict) or e3["inputs"].get("text_true") != ["9901", 0]:
        print("      ! 插件连线没进 prompt：%r"
              % ((e3 or {}).get("inputs", {}).get("text_true") if isinstance(e3, dict) else e3))
        bad += 1
    if isinstance(e3, dict) and e3["inputs"].get("boolean_value") is not False:
        print("      ! 插件关着时 boolean_value 应为 False")
        bad += 1
    set_widget_of(sw3, "boolean_value", True, oi[sw3["type"]])
    p3, ok = sim(w11, oi, "分段提示词（插件开）")
    bad += not ok
    e3 = deref(p3, "104", "text3")
    if isinstance(e3, dict) and e3["inputs"].get("boolean_value") is not True:
        print("      ! 打开插件后 boolean_value 应为 True")
        bad += 1
    # 负面提示词不分段：只有一个单框，没有开关、没有拼接器
    if count(p3, "CR Text Input Switch JK") != 8:
        print("      ! 图像管线只该有正向那 8 个分段开关，实际 %d"
              % count(p3, "CR Text Input Switch JK"))
        bad += 1
    if count(p3, "YogurtStringConcat") != 1:
        print("      ! 图像管线只该跑正向一个拼接器，实际 %d"
              % count(p3, "YogurtStringConcat"))
        bad += 1
    neg = p3.get("105")
    if not isinstance(neg, dict) or neg.get("class_type") != "PrimitiveStringMultiline":
        print("      ! 负面提示词应是单框 PrimitiveStringMultiline：%r"
              % (neg.get("class_type") if isinstance(neg, dict) else neg))
        bad += 1
    else:
        if len(neg.get("inputs") or {}) != 1 or "value" not in neg["inputs"]:
            print("      ! 负面单框只该有一个 value 输入：%r" % (neg.get("inputs"),))
            bad += 1
        if not str(neg["inputs"].get("value", "")).strip():
            print("      ! 负面单框里的文本是空的")
            bad += 1
        enc = deref(p3, "107", "text")
        if not isinstance(enc, dict) or enc.get("class_type") != "PrimitiveStringMultiline":
            print("      ! 负向编码没直接吃到单框：%r"
                  % (enc.get("class_type") if isinstance(enc, dict) else enc))
            bad += 1

    # 12 视频管线：换成视频那两组提示词
    w12 = copy.deepcopy(wf)
    pick_pipeline(w12, "i2v")
    p5, ok = sim(w12, oi, "分段提示词（视频管线）")
    bad += not ok
    if "104" in p5 or "105" in p5:
        print("      ! 视频管线不该跑图像提示词")
        bad += 1
    if "401" not in p5 or "402" not in p5:
        print("      ! 视频管线应跑视频正/负提示词")
        bad += 1
    if count(p5, "YogurtStringConcat") != 1:
        print("      ! 视频管线只该跑正向一个拼接器，实际 %d"
              % count(p5, "YogurtStringConcat"))
        bad += 1
    vneg = p5.get("402")
    if not isinstance(vneg, dict) or vneg.get("class_type") != "PrimitiveStringMultiline":
        print("      ! 视频负面同样该是单框：%r"
              % (vneg.get("class_type") if isinstance(vneg, dict) else vneg))
        bad += 1

    # 13 面板默认值：这才是「出厂配方」，画布上被结转的用户值不在这条线上
    # （用户自己调过的值上面只给提示，见 10b）。
    print()
    print("[13] 面板默认值（重置默认值写回画布的那一套）")
    dock_path = os.path.join(os.path.dirname(HERE), "web", "dock.js")
    try:
        with open(dock_path, encoding="utf-8") as fh:
            dock = fh.read()
    except Exception:
        dock = ""
    m = re.search(r"const PARAM_DEFAULTS = \{(.*?)\n\};", dock, re.S)
    if not m:
        print("      ! 读不到 dock.js 的 PARAM_DEFAULTS")
        bad += 1
    else:
        defs = {k: float(v) for k, v in
                re.findall(r"(\w+):\s*(-?\d+(?:\.\d+)?)", m.group(1))}
        # 脸手眼 / 高清 / 视频后处理的安全区（[下限, 上限]）
        band = [
            ("detailer_feather", 16, 40, "羽化低于 16 会露方块拼接痕"),
            ("detailer_denoise_face", 0.10, 0.35, "脸重绘 >0.35 会改长相"),
            ("detailer_denoise_hand", 0.10, 0.35, "手重绘 >0.35 会重画内容"),
            ("detailer_denoise_eye", 0.10, 0.30, "眼重绘 >0.30 会糊成一块"),
            ("detailer_threshold", 0.45, 0.70, "检测阈值"),
            ("detailer_threshold_eye", 0.55, 0.90, "眼检测阈值"),
            ("detailer_guide", 384, 768, "检测框放大尺寸 >768 = 脸被贴上去"),
            ("detailer_max_size", 512, 1536, "放大上限"),
            ("detailer_crop", 2.0, 3.0, "裁剪倍率 >3 会改到背景"),
            ("upscale_whole_denoise", 0.05, 0.20, "整体细化强度"),
            ("upscale_denoise", 0.05, 0.20, "分块精修强度"),
            ("upscale_seam_fix", 0.15, 0.50, "接缝修复强度"),
            ("upscale_factor", 1.0, 3.0, "图像高清倍数"),
            ("pose_strength", 0.50, 1.0, "姿势强度"),
            ("denoise", 0.30, 0.70, "图生图重绘强度"),
            ("vfi_multiplier", 1, 4, "补帧倍数（>4 只会更糊更慢）"),
            ("video_upscale_factor", 1.0, 3.0, "视频高清目标倍数"),
            ("video_upscale_base", 1.0, 8.0, "放大模型倍率"),
            ("video_upscale_batch", 1, 64, "每批帧数（0 会有炸显存风险）"),
            ("video_upscale_tile", 0, 2048, "分块大小（0 = 自动）"),
            ("video_fps", 8, 60, "视频帧率"),
            ("video_length", 17, 257, "视频帧数（Wan 要 4n+1）"),
        ]
        miss = [k for k, lo, hi, _t in band if k not in defs]
        if miss:
            print("      ! 面板默认值缺这些键：%s" % miss)
            bad += 1
        bad_default = []
        for k, lo, hi, tip in band:
            if k not in defs:
                continue
            if not (lo <= defs[k] <= hi):
                bad_default.append("%s=%s 超出 %s~%s（%s）"
                                   % (k, defs[k], lo, hi, tip))
        if bad_default:
            print("      ! 默认值越界：")
            for line in bad_default:
                print("        - %s" % line)
            bad += 1
        else:
            print("      ok   共 %d 项默认值都在安全区（脸手眼 / 高清 / 视频后处理）"
                  % len(band))
        # 视频后处理的三件套语义：目标倍数 ÷ 模型倍率 = 缩回系数，
        # 默认 2 ÷ 4 = 0.5（也就是「填 2 出 2 倍」，不是 4 倍）
        got = defs.get("video_upscale_factor", 0) / (defs.get("video_upscale_base") or 1)
        if abs(got - 0.5) > 1e-6:
            print("      ! 默认「目标 2 倍 ÷ 4x 模型」应缩回 0.5，实际 %s" % got)
            bad += 1
        else:
            print("      ok   默认缩放系数 = 目标 %s ÷ 模型 %s = %s（填几就是几倍）"
                  % (defs.get("video_upscale_factor"),
                     defs.get("video_upscale_base"), got))
        if int(defs.get("vfi_multiplier", 0)) != 2:
            print("      ! 补帧倍数默认该是 2（每两帧插 1 帧），实际 %s"
                  % defs.get("vfi_multiplier"))
            bad += 1

    print("=" * 66)
    print("场景矩阵：%s" % ("全部通过" if bad == 0 else "%d 项失败" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
