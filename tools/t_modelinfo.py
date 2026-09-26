# -*- coding: utf-8 -*-
"""模型头部探测自检：自带不带 文本编码器 / VAE、属于哪个架构族、训练分辨率是多少。

面板靠它决定①「外挂资源」那一行显不显示 ②「★ 推荐分辨率」给多少。

用法（在插件目录下，用 ComfyUI 自带的 python）：
    ..\\..\\python_embeded\\python.exe tools\\t_modelinfo.py

只看不改：只读 safetensors 头部，不加载权重、不联网、不写任何文件。
"""
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
if PLUGIN not in sys.path:
    sys.path.insert(0, PLUGIN)

import modelinfo                                              # noqa: E402

ANIMA = [
    "oneObsession_anima29BV1.safetensors",
    "miaomiaoHarem_anima16.safetensors",
    "silvermoonmixAnimaEvolved_v2329B_bf16.safetensors",
]
SDXL = ["waiIllustriousSDXL_v170.safetensors", "pixelIllustrious_v30.safetensors"]

_FAILS = []


def ok(cond, msg):
    print(("  [ok]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        _FAILS.append(msg)


def skip(msg):
    print("  [skip] " + msg)


def main():
    print("=" * 70)
    print("外挂资源探测自检（modelinfo）")
    print("=" * 70)

    print("\n[1] ANIMA 裸 DiT：不自带 TE / VAE，且认得出是 anima 系")
    for name in ANIMA:
        r = modelinfo.probe(name)
        if not r.get("known"):
            skip("%s 不在本机（%s）" % (name, r.get("reason")))
            continue
        ok(r["has_te"] is False and r["has_vae"] is False,
           "%s 没有自带 TE / VAE（%d 个张量）" % (name, r["keys"]))
        ok(r["is_anima"] is True, "%s 认出是 ANIMA 系（有 llm_adapter）" % name)
        ok(r["arch"] == "anima", "%s 架构族 = anima（实测 %s）" % (name, r["arch"]))
        ok(r["res"] == [1024, 1024],
           "%s 推荐分辨率 1024×1024（实测 %s，来源 %s）" % (name, r["res"], r["res_src"]))
        ok(r["res_src"] == "family",
           "%s 分辨率来自结构判族（文件里没写训练分辨率 → res_src=family）" % name)
        ok("ANIMA" in r["res_why"], "%s 推荐理由写了族名：%s" % (name, r["res_why"]))

    print("\n[2] Illustrious / SDXL：两个都自带，且不是 anima 系")
    for name in SDXL:
        r = modelinfo.probe(name)
        if not r.get("known"):
            skip("%s 不在本机（%s）" % (name, r.get("reason")))
            continue
        ok(r["has_te"] is True and r["has_vae"] is True,
           "%s 自带 TE 与 VAE" % name)
        ok(r["is_anima"] is False, "%s 不是 ANIMA 系" % name)
        ok(r["arch"] == "sdxl", "%s 架构族 = sdxl（实测 %s）" % (name, r["arch"]))
        ok(r["res"] == [1024, 1024],
           "%s 推荐分辨率 1024×1024（实测 %s）" % (name, r["res"]))

    print("\n[3] 外挂文件本身：Qwen3-0.6B 认成文本编码器，qwen_image_vae 认成 VAE")
    r = modelinfo.probe("qwen_3_06b_base.safetensors")
    if r.get("known"):
        ok(r["has_te"] is True and r["has_vae"] is False,
           "qwen_3_06b_base.safetensors 是纯文本编码器")
    else:
        skip("qwen_3_06b_base.safetensors 不在本机")
    r = modelinfo.probe("qwen_image_vae.safetensors")
    if r.get("known"):
        ok(r["has_vae"] is True and r["has_te"] is False,
           "qwen_image_vae.safetensors 是纯 VAE")
    else:
        skip("qwen_image_vae.safetensors 不在本机")
    # umt5 这类 T5 里有 encoder.block.*，以前会被误判成 VAE（面板就会以为视频 VAE 已自带）
    r = modelinfo.probe("umt5_xxl_fp8_e4m3fn_scaled.safetensors")
    if r.get("known"):
        ok(r["has_te"] is True and r["has_vae"] is False,
           "umt5 是纯文本编码器（不能因为 encoder.block.* 被当成 VAE）")
        ok(r["arch"] == "other", "umt5 没有扩散主干 → arch=other")
    else:
        skip("umt5 不在本机")

    print("\n[3b] 视频 / 其它权重：Wan DiT 认出来就是 832×480，纯 VAE 不编分辨率")
    for name in ["wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
                 "wan2.1_i2v_480p_14B_fp16.safetensors"]:
        r = modelinfo.probe(name)
        if not r.get("known"):
            skip("%s 不在本机" % name)
            continue
        ok(r["arch"] == "wan", "%s 架构族 = wan（实测 %s）" % (name, r["arch"]))
        ok(r["res"] == [832, 480],
           "%s 推荐分辨率 832×480（Wan 官方 480P，实测 %s）" % (name, r["res"]))
    r = modelinfo.probe("wan_2.1_vae.safetensors")
    if r.get("known"):
        ok(r["has_vae"] is True and r["arch"] == "other" and r["res"] is None,
           "wan_2.1_vae 是纯 VAE：res=None（面板不该给它编分辨率）")
    else:
        skip("wan_2.1_vae.safetensors 不在本机")

    print("\n[4] 读不到就老实说读不到（面板会退回按名字判断）")
    for bad, why in [
        ("definitely_not_here.safetensors", "不存在的文件"),
        ("../../../windows/win.ini", "路径穿越"),
        ("D:\\AI\\ComfyUI\\main.py", "绝对路径"),
        ("", "空名字"),
    ]:
        r = modelinfo.probe(bad)
        ok(r.get("known") is False and r.get("ok") is True,
           "%s → known=False（%s）" % (why, r.get("reason")))
    ok(modelinfo.resolve("..\\..\\main.py") is None, "resolve 拒绝越界路径")

    print("\n[5] 只读 + 缓存：第二次不再读盘，且不加载权重")
    name = next((n for n in ANIMA + SDXL if modelinfo.resolve(n)), "")
    if name:
        t0 = time.perf_counter()
        a = modelinfo.probe(name)
        t1 = time.perf_counter()
        b = modelinfo.probe(name)
        t2 = time.perf_counter()
        ok(a == b, "两次结果一致")
        ok((t1 - t0) < 1.0, "第一次读头部 < 1s（实测 %.0f ms）" % ((t1 - t0) * 1000))
        ok((t2 - t1) < 0.05, "第二次走缓存 < 50ms（实测 %.0f ms）" % ((t2 - t1) * 1000))
        ok(len(modelinfo._CACHE) >= 1, "缓存里有 %d 条" % len(modelinfo._CACHE))
    else:
        skip("本机没有可测的 ckpt")

    print("\n[6] 合成头部：判族 / 元数据解析（不依赖本机文件，逻辑本身的自检）")
    def sh(*shape):
        return {"dtype": "F16", "shape": list(shape), "data_offsets": [0, 2]}

    cases = [
        ("anima", {"x.llm_adapter.w": sh(1)}),
        ("wan", {"patch_embedding.weight": sh(5120, 36, 1, 2, 2),
                 "blocks.0.self_attn.q.weight": sh(5120, 5120)}),
        ("flux", {"double_blocks.0.img_attn.qkv.weight": sh(1),
                  "single_blocks.0.linear1.weight": sh(1)}),
        ("sd3", {"joint_blocks.0.x_block.attn.qkv.weight": sh(1)}),
        ("sdxl", {"model.diffusion_model.label_emb.0.0.weight": sh(1280, 2816)}),
        ("sd15", {"model.diffusion_model.input_blocks.0.0.weight": sh(320, 4, 3, 3),
                  "model.diffusion_model.middle_block.1.transformer_blocks.0.attn2.to_k.weight":
                      sh(320, 768)}),
        ("sd21", {"model.diffusion_model.middle_block.1.transformer_blocks.0.attn2.to_k.weight":
                      sh(320, 1024)}),
        ("other", {"vae.decoder.conv_out.weight": sh(3, 3, 3, 3)}),
        ("unknown", {"whatever.weight": sh(1)}),
    ]
    for want, head in cases:
        got = modelinfo.detect_arch(head)
        ok(got == want, "合成头部 %s → %s" % (want, got))

    ok(modelinfo.is_wan_like({"patch_embedding.weight": sh(5120, 36, 1, 2, 2)}) is True,
       "Wan 签名：patch_embedding [5120, 36, 1, 2, 2] 命中")
    ok(modelinfo.is_wan_like({"patch_embedding.weight": sh(320, 4, 1, 2, 2)}) is False,
       "小维度 patch_embedding（dim=320）不误判成 Wan")
    ok(modelinfo.is_wan_like({"model.diffusion_model.input_blocks.0.0.weight": sh(320, 4, 3, 3)})
       is False, "SDXL 的 input_blocks 不是 Wan 签名")

    w, h, src, buckets = modelinfo.meta_resolution({"ss_resolution": "768, 768"})
    ok((w, h, src) == (768, 768, "ss_resolution"),
       "kohya ss_resolution → 768×768（%s）" % (src,))
    w, h, src, _ = modelinfo.meta_resolution({"modelspec.resolution": "1024x1024"})
    ok((w, h) == (1024, 1024), "ModelSpec modelspec.resolution → 1024×1024")
    w, h, src, _ = modelinfo.meta_resolution({"ss_resolution": "640"})
    ok((w, h) == (640, 640), "只写一条边 → 当正方形 640×640")
    bucket = {"buckets": {"1_1": {"0": [10, 1024, 1024]},
                          "16_9": {"0": [40, 1216, 832], "1": [3, 1344, 768]}}}
    w, h, src, rows = modelinfo.meta_resolution({"ss_bucket_info": __import__("json").dumps(bucket)})
    ok((w, h) == (1216, 832) and len(rows) == 3,
       "ss_bucket_info → 取用得最多的桶 1216×832（共 %d 个桶）" % len(rows))
    ok(modelinfo.meta_resolution({}) == (None, None, None, []), "没有元数据 → 老实返回空")

    print("\n[7] 接口与版本")
    init = os.path.join(PLUGIN, "__init__.py")
    txt = open(init, encoding="utf-8").read()
    ok("/cc_dashboard/model_info" in txt, "__init__.py 注册了 model_info 路由")
    ver = ""
    for line in txt.splitlines():
        if line.startswith("__version__"):
            ver = line.split("=")[1].strip().strip('"')
    dock = open(os.path.join(PLUGIN, "web", "dock.js"), encoding="utf-8").read()
    ok(('const CC_DASHBOARD_VERSION = "%s"' % ver) in dock,
       "面板版本号与 __init__.py 一致（%s）" % ver)
    ok("const BLUEPRINT_REV = 7" in dock, "面板蓝图版本是 7")

    print("\n" + "-" * 70)
    if _FAILS:
        print("[!] %d 项没过：" % len(_FAILS))
        for f in _FAILS:
            print("    - %s" % f)
        return 1
    print("[ok] 全部通过：探测结果与实机模型一致，读不了的时候也不会骗人。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
