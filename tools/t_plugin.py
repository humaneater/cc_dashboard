# -*- coding: utf-8 -*-
"""插件包自检：版本号一致 / 预置蓝图与生成器同步 / 接口与装载逻辑可用。

不需要启动 ComfyUI：全程在临时目录里跑，不碰你的工作流和参数。

运行： python tools/t_plugin.py
"""
import json
import os
import re
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
if PLUGIN not in sys.path:
    sys.path.insert(0, PLUGIN)

from blueprint import generator                             # noqa: E402
from tools import paths                                     # noqa: E402

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def versions():
    out = {}
    m = re.search(r'^__version__\s*=\s*"([^"]+)"',
                  read(os.path.join(PLUGIN, "__init__.py")), re.M)
    out["__init__.py"] = m.group(1) if m else None
    m = re.search(r'const\s+CC_DASHBOARD_VERSION\s*=\s*"([^"]+)"',
                  read(os.path.join(PLUGIN, "web", "dock.js")))
    out["web/dock.js"] = m.group(1) if m else None
    py = read(os.path.join(PLUGIN, "pyproject.toml"))
    try:
        import tomllib
        out["pyproject.toml"] = tomllib.loads(py)["project"]["version"]
    except Exception:
        m = re.search(r'^version\s*=\s*"([^"]+)"', py, re.M)
        out["pyproject.toml"] = m.group(1) if m else None
    return out


def role_keys(wf):
    out = set()
    for node in wf.get("nodes") or []:
        props = node.get("properties") or {}
        role = props.get("cc_dock_role")
        if role:
            out.add(role + ":" + str(props.get("cc_dock_key")))
    return out


def shape(wf):
    """蓝图骨架：节点 id+类型、连线数、子图名单（不看用户的数值）。"""
    nodes = tuple((n.get("id"), n.get("type")) for n in wf.get("nodes") or [])
    subs = tuple(sg.get("name") for sg in
                 (wf.get("definitions") or {}).get("subgraphs") or [])
    return nodes, len(wf.get("links") or []), subs


def main():
    print("=" * 66)
    print("cc_dashboard 插件自检")
    print("=" * 66)

    print("\n[1] 版本号三处一致")
    vs = versions()
    for k, v in vs.items():
        ok(bool(v), "%s 写了版本号：%s" % (k, v))
    ok(len(set(vs.values())) == 1, "三处版本号一致：%s" % (sorted(set(vs.values())),))

    print("\n[2] 文件齐全")
    for rel in ("__init__.py", "web/dock.js", "blueprint/00_总控台.json",
                "blueprint/generator.py", "pyproject.toml", "README.md",
                "SHARE.md", "tools/gen_dashboard.py", "tools/check_dashboard.py",
                "tools/t_sim.py", "tools/t_dock.mjs", "tools/make_zip.py",
                "translate.py", "web/zh_en_dict.json",
                "tools/install_translate.py"):
        ok(os.path.exists(os.path.join(PLUGIN, rel)), "有 %s" % rel)
    init_src = read(os.path.join(PLUGIN, "__init__.py"))
    ok('WEB_DIRECTORY = "web"' in init_src, "WEB_DIRECTORY 指向 web/")
    ok("/cc_dashboard/status" in init_src and "/cc_dashboard/blueprint" in init_src
       and "/cc_dashboard/translate" in init_src,
       "注册了 status / blueprint / translate 三个接口")
    ok("CCTranslateZhEn" in init_src, "注册了「中→英 翻译」画布节点")
    ok("ensure_blueprint_installed" in init_src, "首次安装会放置预置蓝图")

    print("\n[3] 预置蓝图与生成器同步")
    # 蓝图版本号：generator 写进 extra.cc_dashboard_blueprint，dock.js 用它判断
    # 「画布上这份是不是旧蓝图」。两边不一致 = 橙色提示条要么乱报要么不报，所以卡住。
    dock_src = read(os.path.join(PLUGIN, "web", "dock.js"))
    m_js = re.search(r"const BLUEPRINT_REV\s*=\s*(\d+)", dock_src)
    ok(bool(m_js), "dock.js 写了 BLUEPRINT_REV")
    eq_ok = m_js and int(m_js.group(1)) == int(generator.BLUEPRINT_REV)
    ok(eq_ok, "蓝图版本两边一致：dock.js=%s / generator.py=%s"
       % (m_js.group(1) if m_js else "?", generator.BLUEPRINT_REV))
    bundled = json.load(open(os.path.join(PLUGIN, "blueprint", "00_总控台.json"),
                            encoding="utf-8"))
    fresh, report = generator.build_workflow(None)
    ok(shape(bundled) == shape(fresh),
       "预置蓝图 = 生成器当前产出（%d 节点 / %d 连线 / %d 子图）"
       % (report["nodes"], report["links"], report["subgraphs"]))
    ok(role_keys(bundled) == role_keys(fresh),
       "面板认领的 role:key 共 %d 项，两边一致" % len(role_keys(fresh)))
    ok(len(role_keys(fresh)) > 0, "蓝图里带了面板标记（不是普通工作流）")

    print("\n[3b] 中→英翻译（内置词典 + 可选 Opus-MT）")
    import translate as trans                                   # noqa: E402
    dict_doc = json.load(open(os.path.join(PLUGIN, "web", "zh_en_dict.json"),
                              encoding="utf-8"))
    nwords = len(dict_doc.get("dict") or {})
    ok(nwords > 800, "词典词条 %d 条" % nwords)
    ok("女孩" in (dict_doc.get("dict") or {}), "词典含常用词（女孩）")
    r1 = trans.translate("银发女孩微笑", engine="dict")
    ok("1girl" in r1["text"] and "smile" in r1["text"],
       "词典翻译可用：银发女孩微笑 → %s" % r1["text"])
    r2 = trans.translate("一只叫做咪咪的猫在弹钢琴", engine="dict")
    ok("cat" in r2["text"] and bool(r2["miss"]),
       "未收录词列出来不硬吞：%s" % r2["miss"])
    st = trans.status()
    ok(isinstance(st, dict) and "installed" in st and "dir" in st,
       "翻译状态可用（Opus-MT %s）" % ("已装" if st.get("installed") else "未装"))
    r3 = trans.translate("银发女孩微笑")          # 默认引擎：装了模型就是真翻译
    if st.get("installed"):
        ok(r3.get("engine") == "opus-mt",
           "装了模型时默认走本机 Opus-MT（真翻译）→ %s" % r3["text"])
        ok(not r3.get("miss"), "NMT 模式不报未收录")
    else:
        ok(r3.get("engine") == "dict", "没装模型时回落词典 → %s" % r3["text"])

    print("\n[4] 面板契约与面板脚本对得上")
    dock = read(os.path.join(PLUGIN, "web", "dock.js"))
    ids = set(re.findall(r"\b([a-z_]+):\s*\[", dock))
    for role in ("model_slot", "prompt", "param", "lora_group", "module",
                 "save", "source_image"):
        ok(role in dock, "面板里有 role=%s 的处理" % role)
    ok("cc_dock_role" in dock and "cc_dock_ui_v1" in dock,
       "沿用 cc_dock_role / cc_dock_ui_v1 老契约（不会丢你现有的参数记忆）")

    print("\n[5] 生成 / 备份 / 越界保护（全程在临时目录）")
    tmp = tempfile.mkdtemp(prefix="cc_dashboard_test_")
    old_env = os.environ.get("CC_DASHBOARD_USER_DIR")
    os.environ["CC_DASHBOARD_USER_DIR"] = tmp
    try:
        out = paths.workflow_path()
        ok(paths.inside(out, tmp), "默认输出落在用户目录里：%s" % out)
        res1 = generator.write_blueprint(mode="update")
        ok(res1["ok"] and os.path.exists(out), "第一次生成写出蓝图")
        ok(res1["backup"] is None, "没有旧文件时不产生空备份")
        res2 = generator.write_blueprint(mode="update")
        ok(bool(res2["backup"]) and os.path.exists(res2["backup"]),
           "第二次生成前先备份：%s" % res2["backup"])
        ok(os.path.dirname(res2["backup"]).startswith(tmp),
           "备份放在用户目录里（不混进工作流列表）")
        res3 = generator.write_blueprint(mode="fresh")
        ok(shape(res3["workflow"]) == shape(res1["workflow"]),
           "fresh 重建的骨架与 update 一致（只是不结转数值）")
        # 采样器 / 调度器（面板下拉写的就是子图里这两格）重建时要结转
        with open(out, encoding="utf-8") as fh:
            doc = json.load(fh)
        touched = 0
        for sub in (doc.get("definitions") or {}).get("subgraphs") or []:
            for node in sub.get("nodes") or []:
                order = generator.SAMPLER_WIDGET_ORDER.get(node.get("type"))
                if not order:
                    continue
                wv = node.setdefault("widgets_values", [])
                while len(wv) < len(order):
                    wv.append(None)
                wv[order.index("sampler_name")] = "uni_pc"
                wv[order.index("scheduler")] = "sgm_uniform"
                touched += 1
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
        res4 = generator.write_blueprint(mode="update")
        seen = set()
        for sub in (res4["workflow"].get("definitions") or {}).get("subgraphs") or []:
            for node in sub.get("nodes") or []:
                order = generator.SAMPLER_WIDGET_ORDER.get(node.get("type"))
                if not order:
                    continue
                wv = node.get("widgets_values") or []
                seen.add((wv[order.index("sampler_name")],
                          wv[order.index("scheduler")]))
        ok(touched > 0 and seen == {("uni_pc", "sgm_uniform")},
           "重建时结转子图里的采样器 / 调度器（%d 处采样节点）" % touched)
        # 视频模型槽要是 GGUF 加载器（面板上选 .gguf 会换过去），重建后得还是它，
        # 否则那格会挂一个核心 UNETLoader 清单里根本没有的 .gguf 文件名
        with open(out, encoding="utf-8") as fh:
            doc = json.load(fh)
        for node in doc["nodes"]:
            if node.get("id") in (406, 407):
                node["type"] = "UnetLoaderGGUF"
                node["widgets_values"] = ["wan22RemixI2VGGUFV20_highQ80.gguf"
                                          if node["id"] == 406
                                          else "wan22RemixI2VGGUFV20_lowQ80.gguf"]
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False)
        res5 = generator.write_blueprint(mode="update")
        got = {n["id"]: (n.get("type"), (n.get("widgets_values") or [None])[0])
               for n in res5["workflow"]["nodes"] if n.get("id") in (406, 407)}
        ok(got == {406: ("UnetLoaderGGUF", "wan22RemixI2VGGUFV20_highQ80.gguf"),
                   407: ("UnetLoaderGGUF", "wan22RemixI2VGGUFV20_lowQ80.gguf")},
           "重建时视频模型槽还是 GGUF 加载器 + 原来那个文件：%s" % got)
        outside = os.path.join(tempfile.gettempdir(),
                               "cc_dashboard_should_not_exist.json")
        if os.path.exists(outside):
            os.remove(outside)
        try:
            generator.write_blueprint(mode="fresh", out_path=outside, guard=True)
            ok(False, "越界写盘应该被拒绝")
        except ValueError:
            ok(not os.path.exists(outside), "拒绝写到工作流目录之外（guard）")
        # 首次安装放置预置蓝图：已存在时绝不覆盖
        parent = os.path.dirname(PLUGIN)
        if parent not in sys.path:
            sys.path.insert(0, parent)
        import cc_dashboard                                    # noqa: E402
        marker = os.path.join(tmp, "workflows", "00_总控台.json")
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write('{"mine": 1}')
        cc_dashboard.ensure_blueprint_installed()
        ok(read(marker) == '{"mine": 1}', "已存在同名工作流时不动它")
        os.remove(marker)
        cc_dashboard.ensure_blueprint_installed()
        ok(read(marker) == read(paths.blueprint_json()),
           "目录里没有蓝图时放进预置那份")
    finally:
        if old_env is None:
            os.environ.pop("CC_DASHBOARD_USER_DIR", None)
        else:
            os.environ["CC_DASHBOARD_USER_DIR"] = old_env
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 66)
    print("结果：%d 通过，%d 失败" % (PASS, FAIL))
    print("=" * 66)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
