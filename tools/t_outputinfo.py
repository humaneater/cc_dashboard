# -*- coding: utf-8 -*-
"""outputinfo 自检：output 清单（历史选择）+ 视频尾帧抽取。

全程在临时目录里跑（CC_DASHBOARD_OUTPUT_DIR 指过去），不碰真实 output：
  · 图片 / 视频过滤、子目录、cc_tail 排除、时间倒序
  · 路径越界（.. / 绝对路径）拒绝
  · PyAV 现场编一段每帧不同颜色的小视频 → 抽尾帧 → 断言 PNG 落地且像素 = 最后一帧

运行： python tools/t_outputinfo.py
"""
import os
import shutil
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
if PLUGIN not in sys.path:
    sys.path.insert(0, PLUGIN)

from outputinfo import extract_tail_frame, list_output, output_dir    # noqa: E402

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


def touch(path, mtime, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)
    os.utime(path, (mtime, mtime))


def make_video(path):
    """6 帧纯色视频：前三帧红、后三帧蓝（尾帧=蓝），64×48。"""
    import av
    from PIL import Image
    os.makedirs(os.path.dirname(path), exist_ok=True)
    container = av.open(path, mode="w")
    stream = container.add_stream("mpeg4", rate=5)
    stream.width = 64
    stream.height = 48
    stream.pix_fmt = "yuv420p"
    colors = [(255, 0, 0)] * 3 + [(0, 0, 255)] * 3
    for color in colors:
        frame = av.VideoFrame.from_image(Image.new("RGB", (64, 48), color))
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()


def main():
    print("=" * 66)
    print("cc_dashboard outputinfo 自检（历史选择 / 视频尾帧）")
    print("=" * 66)

    tmp = tempfile.mkdtemp(prefix="cc_dashboard_out_")
    old_env = os.environ.get("CC_DASHBOARD_OUTPUT_DIR")
    os.environ["CC_DASHBOARD_OUTPUT_DIR"] = tmp
    try:
        print("\n[1] output 清单：过滤 / 排序 / 排除 cc_tail")
        touch(os.path.join(tmp, "a_old.png"), 1000)
        touch(os.path.join(tmp, "b_mid.jpg"), 2000)
        touch(os.path.join(tmp, "sub", "c_new.png"), 3000)
        touch(os.path.join(tmp, "sub", "note.txt"), 3500)
        touch(os.path.join(tmp, "cc_tail", "ignored.png"), 4000)
        touch(os.path.join(tmp, "video", "v1.mp4"), 5000, b"not-a-real-mp4")
        ok(os.path.abspath(output_dir()) == os.path.abspath(tmp),
           "环境变量能指向临时 output：%s" % output_dir())

        imgs = list_output("image")
        names = [it["value"] for it in imgs["items"]]
        ok(imgs["ok"] is True and imgs["count"] == 3,
           "只认图片（png/jpg），txt 不算：count=%d" % imgs["count"])
        ok(names == ["sub/c_new.png [output]", "b_mid.jpg [output]",
                     "a_old.png [output]"],
           "时间倒序、子目录带前缀：%s" % names)
        ok(all(it["value"] == (it["subfolder"] + "/" + it["name"] + " [output]"
                               if it["subfolder"] else it["name"] + " [output]")
               for it in imgs["items"]),
           "value 一律带 [output] 后缀（LoadImageOutput 认这个）")
        ok(all(n.startswith("cc_tail") is False for n in names),
           "cc_tail/ 里的尾帧不混进历史列表")

        vids = list_output("video")
        vnames = [it["value"] for it in vids["items"]]
        ok(vids["count"] == 1 and vnames == ["video/v1.mp4 [output]"],
           "视频清单认子目录里的 mp4：%s" % vnames)
        ok(list_output("script")["kind"] == "image",
           "kind 只认 image / video，其它按 image 处理")

        print("\n[2] 路径安全：.. / 绝对路径 / 非视频都拒绝")
        for bad, label in [
            ({"name": "../evil.mp4"}, ".. 上跳"),
            ({"file": "../../etc/passwd"}, "多级上跳"),
            ({"file": "C:\\Windows\\evil.mp4"}, "别的盘符 / 绝对路径"),
            ({"name": "b_mid.jpg"}, "图片当视频"),
            ({"name": "not_there.mp4"}, "不存在的视频"),
        ]:
            try:
                extract_tail_frame(bad)
                ok(False, "%s 应该被拒绝：%s" % (label, bad))
            except ValueError as e:
                ok(True, "%s 被拒绝（%s）" % (label, e))

        print("\n[3] 视频尾帧：真抽一帧、落盘、像素 = 最后一帧")
        vid = os.path.join(tmp, "video", "cc_tail_src.mp4")
        make_video(vid)
        res = extract_tail_frame({"file": "video/cc_tail_src.mp4 [output]"})
        ok(res["ok"] is True and res["subfolder"] == "cc_tail",
           "尾帧写进 output/cc_tail/：%s" % res.get("value"))
        ok(res["value"].endswith(" [output]"),
           "返回给面板的值带 [output] 后缀（可直接写进取图节点）")
        ok(not os.path.isfile(os.path.join(tmp, res["name"])),
           "  └ 不落在 output 根目录（所以不会混进 output 那份图片清单）")
        full = os.path.join(tmp, "cc_tail", res["name"])
        ok(os.path.isfile(full), "  └ PNG 真的落盘：%s" % full)
        ok((res["width"], res["height"]) == (64, 48),
           "尺寸跟视频一致：%dx%d" % (res["width"], res["height"]))
        ok(res["frames"] >= 6, "解出 %d 帧（至少 6）" % res["frames"])
        from PIL import Image
        with Image.open(full) as img:
            r, g, b = img.convert("RGB").getpixel((32, 24))
        ok(r < 60 and b > 200,
           "尾帧像素是最后一帧的蓝色（r=%d b=%d，不是首帧的红）" % (r, b))
        # 抽出来的尾帧不出现在图片历史里
        names2 = [it["value"] for it in list_output("image")["items"]]
        ok(all("cc_tail" not in n for n in names2),
           "抽完尾帧后历史列表还是干净的三张")

        print("\n[4] 重复抽同一段视频不会互相覆盖")
        res2 = extract_tail_frame("video/cc_tail_src.mp4")
        ok(res2["name"] != res["name"]
           and os.path.isfile(os.path.join(tmp, "cc_tail", res2["name"])),
           "同一秒里连截两次 → 第二个自动加序号：%s" % res2["name"])

        print("\n[5] 列表上限参数生效")
        lim = list_output("image", limit=2)
        ok(len(lim["items"]) == 2 and lim["count"] == 3,
           "limit=2 只返回 2 条，count 仍是全量 3")
    finally:
        if old_env is None:
            os.environ.pop("CC_DASHBOARD_OUTPUT_DIR", None)
        else:
            os.environ["CC_DASHBOARD_OUTPUT_DIR"] = old_env
        time.sleep(0.05)
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 66)
    print("结果：%d 通过，%d 失败" % (PASS, FAIL))
    print("=" * 66)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
