# -*- coding: utf-8 -*-
"""离线校验 00_总控台.json（v4，含子图）。

不需要启动 ComfyUI：节点定义来自 _object_info.json。
检查项：
  1. 根图 / 子图的必需字段与 schema（对照前端 zod 定义）
  2. 节点类型存在、id 唯一、widgets_values 数量（警告级）
  3. 连线合法性：index 合法、类型一致、input.link 与 links 双向一致
  4. 子图 IO：sg.inputs/outputs 与内部 -10/-20 连线一致
  5. 子图实例节点：inputs/outputs 与定义逐项对齐，proxyWidgets 指向真实内部节点
  6. 旁路（mode 4）端口序号对齐：关掉模块不断链
  7. 必需输入无悬空（widget 输入除外）
  8. 面板 role/key 与 dock.js 声明一致

运行： python tools/check_dashboard.py
"""
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
DOCK_PATH = os.path.join(paths.web_dir(), "dock.js")

WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN"}
DYN_NODES = {"LoadImage", "LoadImageOutput", "SaveVideo", "MarkdownNote",
             "Note", "Power Lora Loader (rgthree)"}
# 前端虚拟节点，不出现在 object_info 里
VIRTUAL_NODES = {"MarkdownNote", "Note"}

ERRORS = []
WARNS = []

# 服务器下拉列表是启动时缓存的：新下载的权重要重启才出现。
# 这里对“列表里没有但磁盘上确实存在”的情况只提示，不判错。
_DISK_FILES = None


def on_disk(name):
    global _DISK_FILES
    if _DISK_FILES is None:
        _DISK_FILES = set()
        root = os.path.join(paths.comfy_root(), "models")
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                _DISK_FILES.add(fn)
    return name in _DISK_FILES


_NEW_PROXY_NOTE = [False]


def err(msg):
    ERRORS.append(msg)


def warn(msg):
    WARNS.append(msg)


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def widgetable(spec):
    """object_info 里的某个输入能否在画布上表现为 widget。"""
    if not isinstance(spec, list) or not spec:
        return False
    t = spec[0]
    if isinstance(t, list) or t in ("COMBO", "COMFY_DYNAMICCOMBO_V3"):
        return True
    return t in WIDGET_TYPES


def widget_order(defn):
    """widgets_values 的下标顺序（前端按定义顺序建 widget，seed 后多一个控制项）。"""
    names = []
    for sec in ("required", "optional"):
        for name, spec in (defn["input"].get(sec) or {}).items():
            opts = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
            if opts.get("forceInput") or opts.get("hidden"):
                continue
            if widgetable(spec):
                names.append(name)
                # 前端给「带 control_after_generate 的 INT」自动挂一个控制 widget：
                # 老节点叫 seed / noise_seed，ComfyUI 新的 PrimitiveInt 直接写在
                # spec 的第二项里，所以两种都认。
                if spec[0] == "INT" and (name in ("seed", "noise_seed")
                                         or "control_after_generate" in opts):
                    names.append("control_after_generate")
    return names


def expected_widgets(defn):
    return len(widget_order(defn))


def check_link_array(links, nodes_by_id, where):
    """根图连线是数组 [id, src, sslot, dst, dslot, type]。"""
    seen = set()
    for item in links:
        if not isinstance(item, list) or len(item) != 6:
            err("%s: 连线格式错误 %s" % (where, item))
            continue
        lid, src, sslot, dst, dslot, ltype = item
        if lid in seen:
            err("%s: 连线 id 重复 %s" % (where, lid))
        seen.add(lid)
        sn, dn = nodes_by_id.get(src), nodes_by_id.get(dst)
        if sn is None:
            err("%s: 连线 %s 源头节点 %s 不存在" % (where, lid, src))
            continue
        if dn is None:
            err("%s: 连线 %s 目标节点 %s 不存在" % (where, lid, dst))
            continue
        if sslot >= len(sn.get("outputs") or []):
            err("%s: 连线 %s 源 slot %s 越界" % (where, lid, sslot))
            continue
        if dslot >= len(dn.get("inputs") or []):
            err("%s: 连线 %s 目标 slot %s 越界" % (where, lid, dslot))
            continue
        out, inp = sn["outputs"][sslot], dn["inputs"][dslot]
        if out["type"] != inp["type"]:
            err("%s: 连线 %s 类型不符 %s.%s -> %s.%s (%s != %s)"
                % (where, lid, src, out["name"], dst, inp["name"],
                   out["type"], inp["type"]))
        if ltype not in (out["type"], "*", ""):
            err("%s: 连线 %s 记录类型 %s 与源 %s 不符"
                % (where, lid, ltype, out["type"]))
        if inp.get("link") != lid:
            err("%s: 连线 %s 未回写到 %s.%s.link（=%s）"
                % (where, lid, dst, inp["name"], inp.get("link")))
        if lid not in (out.get("links") or []):
            err("%s: 连线 %s 未登记在 %s.%s.links"
                % (where, lid, src, out["name"]))


def bypass_slot(inputs, outputs, slot):
    """复刻前端 _getBypassSlotIndex：按序号对齐，找不到就按类型找第一个。"""
    if slot >= len(outputs):
        return -1
    otype = outputs[slot]["type"]
    if slot < len(inputs) and inputs[slot]["type"] == otype:
        return slot
    for i, s in enumerate(inputs):
        if s["type"] == otype:
            return i
    return -1


def check_node_common(node, where, oi, is_instance=False):
    nid = node.get("id")
    for key in ("id", "type", "pos", "size", "flags", "order", "mode",
                "properties"):
        if key not in node:
            err("%s: 节点 %s 缺字段 %s" % (where, nid, key))
    for s in (node.get("inputs") or []):
        if "name" not in s or "type" not in s:
            err("%s: 节点 %s 有非法 input %s" % (where, nid, s))
    for s in (node.get("outputs") or []):
        if "name" not in s or "type" not in s:
            err("%s: 节点 %s 有非法 output %s" % (where, nid, s))
    if is_instance or node.get("type") not in oi:
        return
    defn = oi[node["type"]]
    wv = node.get("widgets_values")
    if isinstance(wv, list) and node["type"] not in DYN_NODES:
        exp = expected_widgets(defn)
        if len(wv) != exp:
            warn("%s: 节点 %s(%s) widgets_values=%d，定义推算=%d（前端会补默认值）"
                 % (where, nid, node["type"], len(wv), exp))
    # 下拉值必须真的在服务器给出的列表里（缺失权重会直接拒单）
    names = widget_order(defn)
    for i, name in enumerate(names):
        if not isinstance(wv, list) or i >= len(wv):
            break
        spec = ((defn["input"].get("required") or {}).get(name) or
                (defn["input"].get("optional") or {}).get(name))
        if not spec:
            continue
        t = spec[0]
        opts = t if isinstance(t, list) else (
            t.get("options") if isinstance(t, dict) else None)
        if not isinstance(opts, list) or not opts:
            continue
        val = wv[i]
        if isinstance(val, str) and val not in opts:
            if on_disk(val):
                warn("%s: 节点 %s(%s) 的 %s='%s' 不在服务器缓存列表里"
                     "（文件已在 models/ 下，重启后自动出现）"
                     % (where, nid, node["type"], name, val))
                continue
            err("%s: 节点 %s(%s) 的 %s='%s' 不在服务器列表里（缺文件？）"
                % (where, nid, node["type"], name, val))


def check_required_inputs(node, where, oi, is_instance=False):
    if is_instance:
        return
    defn = oi.get(node["type"])
    if not defn:
        return
    required = set((defn["input"].get("required") or {}).keys())
    if not required:
        return
    for s in (node.get("inputs") or []):
        if s["name"] not in required:
            continue
        if s.get("widget"):
            continue
        if s.get("link") is None:
            err("%s: 节点 %s(%s) 必需输入 %s 悬空"
                % (where, node["id"], node["type"], s["name"]))


def check_subgraph(sg, oi, sg_ids):
    name = sg.get("name") or sg.get("id")
    where = "子图[%s]" % name
    for key in ("id", "version", "revision", "name", "state", "nodes",
                "inputNode", "outputNode"):
        if key not in sg:
            err("%s 缺字段 %s" % (where, key))
    if sg.get("version") != 1:
        err("%s version 必须为 1（当前 %s）" % (where, sg.get("version")))
    for key in ("inputNode", "outputNode"):
        io = sg.get(key) or {}
        if not isinstance(io.get("id"), int):
            err("%s %s.id 必须是整数" % (where, key))
        b = io.get("bounding")
        if not (isinstance(b, list) and len(b) == 4):
            err("%s %s.bounding 必须是 4 元数组" % (where, key))
    st = sg.get("state") or {}
    for key in ("lastNodeId", "lastLinkId", "lastGroupId", "lastRerouteId"):
        if not isinstance(st.get(key), int):
            err("%s state.%s 缺失或非整数" % (where, key))
    nodes = sg.get("nodes") or []
    ids = [n["id"] for n in nodes]
    if len(ids) != len(set(ids)):
        err("%s 内部节点 id 重复" % where)
    if st.get("lastNodeId", 0) < max(ids or [0]):
        err("%s state.lastNodeId 小于最大节点 id" % where)
    by_id = {n["id"]: n for n in nodes}
    for n in nodes:
        check_node_common(n, where, oi)
        check_required_inputs(n, where, oi)
        t = n["type"]
        if t in sg_ids:
            warn("%s 内部节点 %s 又是子图实例（嵌套）" % (where, n["id"]))
        elif t not in oi and t not in VIRTUAL_NODES:
            err("%s 内部节点 %s 类型 %s 不在 object_info" % (where, n["id"], t))

    # 内部连线（dict 形式）
    links = sg.get("links") or []
    lid_map = {}
    for l in links:
        for key in ("id", "origin_id", "origin_slot", "target_id",
                    "target_slot", "type"):
            if key not in l:
                err("%s 内部连线缺字段 %s：%s" % (where, key, l))
        lid_map[l["id"]] = l
    for l in links:
        oid, tid = l["origin_id"], l["target_id"]
        if oid == -10:
            if l["origin_slot"] >= len(sg.get("inputs") or []):
                err("%s 连线 %s origin_slot 越界（-10）" % (where, l["id"]))
        elif oid not in by_id:
            err("%s 连线 %s 源节点 %s 不存在" % (where, l["id"], oid))
        else:
            outs = by_id[oid].get("outputs") or []
            if l["origin_slot"] >= len(outs):
                err("%s 连线 %s 源 slot 越界" % (where, l["id"]))
            elif outs[l["origin_slot"]]["type"] != l["type"]:
                err("%s 连线 %s 类型与源不符" % (where, l["id"]))
        if tid == -20:
            if l["target_slot"] >= len(sg.get("outputs") or []):
                err("%s 连线 %s target_slot 越界（-20）" % (where, l["id"]))
        elif tid not in by_id:
            err("%s 连线 %s 目标节点 %s 不存在" % (where, l["id"], tid))
        else:
            ins = by_id[tid].get("inputs") or []
            if l["target_slot"] >= len(ins):
                err("%s 连线 %s 目标 slot 越界" % (where, l["id"]))
            else:
                if ins[l["target_slot"]]["type"] != l["type"]:
                    err("%s 连线 %s 类型与目标不符" % (where, l["id"]))
                if ins[l["target_slot"]].get("link") != l["id"]:
                    err("%s 连线 %s 未回写到目标输入 link" % (where, l["id"]))

    # 子图 IO
    for i, s in enumerate(sg.get("inputs") or []):
        if not re.match(r"^[0-9a-f-]{8,40}$", str(s.get("id", ""))):
            err("%s inputs[%d].id 不是 uuid" % (where, i))
        for key in ("name", "type", "linkIds"):
            if key not in s:
                err("%s inputs[%d] 缺字段 %s" % (where, i, key))
        for lid in s.get("linkIds") or []:
            l = lid_map.get(lid)
            if l is None:
                err("%s inputs[%d] linkIds 指向不存在的连线 %s"
                    % (where, i, lid))
                continue
            if l["origin_id"] != -10 or l["origin_slot"] != i:
                err("%s inputs[%d] 的连线 %s 起点不是 -10 slot %d"
                    % (where, i, lid, i))
    for i, s in enumerate(sg.get("outputs") or []):
        if not re.match(r"^[0-9a-f-]{8,40}$", str(s.get("id", ""))):
            err("%s outputs[%d].id 不是 uuid" % (where, i))
        for lid in s.get("linkIds") or []:
            l = lid_map.get(lid)
            if l is None:
                err("%s outputs[%d] linkIds 指向不存在的连线 %s"
                    % (where, i, lid))
                continue
            if l["target_id"] != -20 or l["target_slot"] != i:
                err("%s outputs[%d] 的连线 %s 终点不是 -20 slot %d"
                    % (where, i, lid, i))
    return by_id, lid_map


def check_instance(node, sg, by_id, lid_map, where):
    """子图实例节点与定义逐项对齐 + proxyWidgets 校验。"""
    sg_ins = sg.get("inputs") or []
    sg_outs = sg.get("outputs") or []
    n_ins = node.get("inputs") or []
    n_outs = node.get("outputs") or []
    if len(n_ins) != len(sg_ins):
        err("%s: 实例输入数 %d != 子图输入数 %d"
            % (where, len(n_ins), len(sg_ins)))
    for i, (a, b) in enumerate(zip(n_ins, sg_ins)):
        if a.get("name") != b.get("name"):
            err("%s: 实例输入[%d] 名称 %s != %s"
                % (where, i, a.get("name"), b.get("name")))
        if a.get("type") != b.get("type"):
            err("%s: 实例输入[%d] 类型 %s != %s"
                % (where, i, a.get("type"), b.get("type")))
    if len(n_outs) != len(sg_outs):
        err("%s: 实例输出数 %d != 子图输出数 %d"
            % (where, len(n_outs), len(sg_outs)))
    for i, (a, b) in enumerate(zip(n_outs, sg_outs)):
        if a.get("name") != b.get("name") or a.get("type") != b.get("type"):
            err("%s: 实例输出[%d] 与定义不符（%s/%s vs %s/%s）"
                % (where, i, a.get("name"), a.get("type"), b.get("name"),
                   b.get("type")))
    proxy = (node.get("properties") or {}).get("proxyWidgets")
    # 新版前端（v0.34+）保存工作流时不再写 properties.proxyWidgets，而是把代理
    # widget 的值直接落在实例自己的 widgets_values 上 —— 这是合法格式，不当成错，
    # 只是没法定「哪一格对应哪个内部 widget」，那部分映射校验就跳过。
    new_proxy_fmt = proxy is None and bool(node.get("widgets_values"))
    if proxy is None:
        if new_proxy_fmt:
            proxy = []
            if not _NEW_PROXY_NOTE[0]:
                _NEW_PROXY_NOTE[0] = True
                warn("这份工作流是新版前端保存的格式：代理 widget 值写在实例上"
                     "（不做 proxyWidgets 映射校验，其余照常）")
        else:
            err("%s: 实例既没有 properties.proxyWidgets，也没有代理 widget 值" % where)
            return
    for entry in proxy:
        if not (isinstance(entry, list) and len(entry) == 2):
            err("%s: proxyWidgets 项非法 %s" % (where, entry))
            continue
        inner, wname = entry
        if str(inner) not in {str(k) for k in by_id}:
            err("%s: proxyWidgets 指向不存在的内部节点 %s" % (where, inner))
            continue
        node_inner = by_id[int(inner)] if str(inner).isdigit() else None
        if node_inner is None:
            err("%s: proxyWidgets 内部节点 %s 非法" % (where, inner))
            continue
        names = [s["name"] for s in (node_inner.get("inputs") or [])
                 if s.get("widget")]
        if wname not in names:
            err("%s: proxyWidgets [%s,%s] 对应的内部输入不存在（可选：%s）"
                % (where, inner, wname, names))
    # 每个提升成 widget 的子图输入都要在 proxyWidgets 里有映射；一个输入扇出到
    # 多个内部 widget 时（如三级 FaceDetailer 共用的检测阈值 / 羽化）有一条就够：
    # 运行时 -10 的连线会覆盖每一级的 widget 值。
    flat = [list(e) for e in proxy if isinstance(e, list) and len(e) == 2]
    for i, s in enumerate(sg_ins if not new_proxy_fmt else []):
        wants = []
        for lid in (s.get("linkIds") or []):
            l = lid_map.get(lid)
            if not l or l["origin_id"] != -10:
                continue
            inner = by_id.get(l["target_id"])
            if inner is None or l["target_slot"] >= len(inner.get("inputs") or []):
                continue
            tgt = inner["inputs"][l["target_slot"]]
            if not tgt.get("widget"):
                continue
            wants.append([str(l["target_id"]), tgt["name"]])
        if wants and not any(w in flat for w in wants):
            err("%s: 提升输入 %s 缺 proxyWidgets 映射 %s"
                % (where, s["name"], wants[0]))
    if len(n_ins) != len(set(x.get("name") for x in n_ins)):
        err("%s: 实例输入名重复" % where)
    # 旁路端口对齐
    if node.get("mode", 0) == 4 or (node.get("properties") or {}).get(
            "cc_dock_role") == "module":
        for i, out in enumerate(n_outs):
            if bypass_slot(n_ins, n_outs, i) == -1:
                err("%s: 旁路时输出[%d](%s) 找不到同类型输入，会断链"
                    % (where, i, out.get("type")))


def dock_keys(path):
    if not os.path.exists(path):
        return None
    txt = open(path, encoding="utf-8").read()
    pairs = set()
    for role, k in re.findall(r'"(\w+):(\w+)"', txt):
        pairs.add((role, k))
    m = re.search(r"const HANDLED = \{(.*?)\n\};", txt, re.S)
    if not m:
        return pairs
    for rm in re.finditer(r"(\w+):\s*\[([^\]]*)\]", m.group(1)):
        role, arr = rm.group(1), rm.group(2)
        vals = re.findall(r'"([^"]+)"', arr)
        if not vals:
            pairs.add((role, None))
        for v in vals:
            pairs.add((role, v))
    return pairs


def main():
    if not os.path.exists(OI_PATH):
        print("缺少节点定义快照：%s" % OI_PATH)
        print("先跑一次（要用 ComfyUI 自带的 python）：")
        print("    python_embeded\\python.exe tools/dump_object_info.py")
        return 2
    wf = load(WF_PATH)
    oi = load(OI_PATH)
    subs = (wf.get("definitions") or {}).get("subgraphs") or []
    sg_ids = {s["id"] for s in subs}
    root_nodes = wf.get("nodes") or []
    by_id = {n["id"]: n for n in root_nodes}

    for key in ("id", "revision", "last_node_id", "last_link_id", "nodes",
                "links", "groups", "config", "extra", "version"):
        if key not in wf:
            err("根图缺字段 %s" % key)
    if len(by_id) != len(root_nodes):
        err("根图节点 id 重复")
    if wf.get("last_node_id", 0) < max(by_id or [0]):
        err("last_node_id 小于最大节点 id")
    if wf.get("last_link_id", 0) < max([l[0] for l in wf["links"]] or [0]):
        err("last_link_id 小于最大连线 id")

    check_link_array(wf["links"], by_id, "根图")
    for n in root_nodes:
        check_node_common(n, "根图", oi)
        if n["type"] in sg_ids:
            continue
        check_required_inputs(n, "根图", oi)
        if n["type"] not in oi and n["type"] not in VIRTUAL_NODES:
            err("根图: 节点 %s 类型 %s 不在 object_info"
                % (n["id"], n["type"]))

    inner_maps = {}
    for sg in subs:
        inner_maps[sg["id"]] = check_subgraph(sg, oi, sg_ids)
    sg_by_id = {s["id"]: s for s in subs}
    for n in root_nodes:
        if n["type"] in sg_by_id:
            by_id_inner, lid_map = inner_maps[n["type"]]
            check_instance(n, sg_by_id[n["type"]], by_id_inner, lid_map,
                           "根图实例 %s(%s)" % (n["id"], n["type"][-4:]))
        elif n["type"] not in oi and n["type"] not in VIRTUAL_NODES:
            err("根图: 节点 %s 类型 %s 既不是节点也不是子图"
                % (n["id"], n["type"]))

    # 面板 role/key 一致性
    gen = []
    for n in root_nodes + [x for sg in subs for x in sg["nodes"]]:
        p = n.get("properties") or {}
        if p.get("cc_dock_role"):
            gen.append((p["cc_dock_role"], p.get("cc_dock_key")))
    keys = dock_keys(DOCK_PATH)
    if keys is None:
        warn("未找到 %s，跳过面板 key 一致性检查" % DOCK_PATH)
    else:
        for role, key in gen:
            if (role, key) not in keys:
                err("面板 dock.js 未声明 key：%s:%s" % (role, key))

    print("=" * 66)
    print("工作流：%s" % WF_PATH)
    print("根图节点 %d / 连线 %d / 分组 %d / 子图 %d"
          % (len(root_nodes), len(wf["links"]), len(wf.get("groups") or []),
             len(subs)))
    modes = {}
    for n in root_nodes:
        modes[n.get("mode", 0)] = modes.get(n.get("mode", 0), 0) + 1
    print("节点 mode 分布 %s（0=正常 2=静音 4=旁路）" % modes)
    print("面板 role/key 共 %d 项" % len(gen))
    print("=" * 66)
    for w in WARNS:
        print("[warn] %s" % w)
    for e in ERRORS:
        print("[ERR ] %s" % e)
    print("=" * 66)
    print("结果：%d 个错误，%d 个警告" % (len(ERRORS), len(WARNS)))
    return 1 if ERRORS else 0


if __name__ == "__main__":
    sys.exit(main())
