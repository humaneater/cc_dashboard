# -*- coding: utf-8 -*-
"""把 ComfyUI 的 /object_info 落成 JSON 快照，不用起服务。

给生成器 / 校验脚本离线核对节点定义用（服务器没开也能跑）。
镜像 server.py:node_info() 的行为。

用法（必须用 ComfyUI 自带的 python，普通 python 看不到自定义节点）：
    python_embeded\\python.exe tools/dump_object_info.py [--out 路径]
"""
import asyncio
import argparse
import json
import os
import sys
import traceback

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(HERE))
from tools import paths                                     # noqa: E402

COMFY_DIR = paths.comfy_root()

os.chdir(COMFY_DIR)
sys.path.insert(0, COMFY_DIR)

import nodes  # noqa: E402
from comfy_api.internal import _ComfyNodeInternal  # noqa: E402


def node_info(node_class):
    obj_class = nodes.NODE_CLASS_MAPPINGS[node_class]
    if issubclass(obj_class, _ComfyNodeInternal):
        return obj_class.GET_NODE_INFO_V1()
    info = {}
    info["input"] = obj_class.INPUT_TYPES()
    info["input_order"] = {k: list(v.keys())
                           for k, v in obj_class.INPUT_TYPES().items()}
    info["is_input_list"] = getattr(obj_class, "INPUT_IS_LIST", False)
    info["output"] = obj_class.RETURN_TYPES
    info["output_is_list"] = (obj_class.OUTPUT_IS_LIST
                              if hasattr(obj_class, "OUTPUT_IS_LIST")
                              else [False] * len(obj_class.RETURN_TYPES))
    info["output_name"] = (obj_class.RETURN_NAMES
                           if hasattr(obj_class, "RETURN_NAMES") else info["output"])
    info["name"] = node_class
    info["display_name"] = nodes.NODE_DISPLAY_NAME_MAPPINGS.get(node_class,
                                                               node_class)
    info["description"] = getattr(obj_class, "DESCRIPTION", "")
    info["python_module"] = getattr(obj_class, "RELATIVE_PYTHON_MODULE", "nodes")
    info["category"] = getattr(obj_class, "CATEGORY", "sd")
    info["output_node"] = bool(getattr(obj_class, "OUTPUT_NODE", False))
    info["has_intermediate_output"] = bool(
        getattr(obj_class, "HAS_INTERMEDIATE_OUTPUT", False))
    if getattr(obj_class, "DEPRECATED", False):
        info["deprecated"] = True
    if getattr(obj_class, "EXPERIMENTAL", False):
        info["experimental"] = True
    if getattr(obj_class, "DEV_ONLY", False):
        info["dev_only"] = True
    if hasattr(obj_class, "API_NODE"):
        info["api_node"] = obj_class.API_NODE
    info["search_aliases"] = getattr(obj_class, "SEARCH_ALIASES", [])
    return info


async def main(out_path):
    # Some custom nodes (Impact Pack, Jake) touch PromptServer.instance at import
    # time.  Creating the (never-started) instance keeps them loading exactly as
    # they do under the real server, without binding a port.
    from server import PromptServer  # noqa: E402
    PromptServer(asyncio.get_event_loop())
    await nodes.init_extra_nodes()
    out = {}
    for name in nodes.NODE_CLASS_MAPPINGS:
        try:
            out[name] = node_info(name)
        except Exception:
            sys.stderr.write("failed to introspect %s\n%s\n"
                             % (name, traceback.format_exc()))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    print("wrote %s (%d node types)" % (out_path, len(out)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="落一份 /object_info 快照")
    ap.add_argument("--out", help="输出路径，默认 tools/_object_info.json")
    args = ap.parse_args()
    asyncio.run(main(args.out or os.path.join(HERE, "_object_info.json")))
