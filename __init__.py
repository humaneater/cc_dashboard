# -*- coding: utf-8 -*-
"""cc_dashboard —— ComfyUI 总控台：浮动面板 + 蓝图生成器（纯本地、不联网）。

装完这个插件你会得到两样东西：
  1. web/dock.js  —— 浮动控制面板（只在带 cc_dock_role 标记的工作流里出现）
  2. blueprint/   —— 00_总控台.json 蓝图生成器 + 预置蓝图，可一键重建

对外只有两个本机接口（都不涉及外网）：
  GET  /cc_dashboard/status     版本 / 路径 / 蓝图是否就位
  POST /cc_dashboard/blueprint  {"mode":"update"|"fresh"} 重新生成蓝图
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

__version__ = "1.4.0"

try:                                    # 作为插件包导入
    from .blueprint import generator as _generator
    from .tools import paths as _paths
except ImportError:                     # 以顶层模块 / 脚本方式导入
    from blueprint import generator as _generator
    from tools import paths as _paths

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
WEB_DIRECTORY = "web"


def ensure_blueprint_installed():
    """第一次装插件时把预置蓝图放进工作流目录；已存在就绝不覆盖。"""
    dst = _paths.workflow_path()
    src = _paths.blueprint_json()
    if os.path.exists(dst) or not os.path.exists(src):
        return False
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(src, "rb") as fh:
            data = fh.read()
        with open(dst, "wb") as fh:
            fh.write(data)
    except Exception as e:              # 放不进去也不能影响 ComfyUI 启动
        print("[cc_dashboard] 预置蓝图放置失败：%r" % (e,))
        return False
    print("[cc_dashboard] 已放置预置蓝图：%s" % dst)
    return True


def _register_routes():
    """注册两个本机接口（不在 ComfyUI 里运行时静默跳过）。"""
    try:
        from aiohttp import web
        from server import PromptServer
    except Exception:
        return False
    inst = getattr(PromptServer, "instance", None)
    if inst is None or getattr(inst, "routes", None) is None:
        return False
    routes = inst.routes

    @routes.get("/cc_dashboard/status")
    async def cc_dashboard_status(request):
        wf = _paths.workflow_path()
        return web.json_response({
            "ok": True,
            "version": __version__,
            "plugin_dir": _paths.plugin_dir(),
            "workflows_dir": _paths.workflows_dir(),
            "workflow": wf,
            "installed": os.path.exists(wf),
            "blueprint": _paths.blueprint_json(),
        })

    @routes.post("/cc_dashboard/blueprint")
    async def cc_dashboard_blueprint(request):
        try:
            data = await request.json()
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        mode = "fresh" if str(data.get("mode", "")).lower() == "fresh" else "update"
        # 面板会把画布现况一起传过来做参数结转（画布可能比磁盘那份新，
        # 结构仍然由 generator 重建，所以旧画布也只会救回参数）
        canvas = data.get("canvas")
        if not (isinstance(canvas, dict)
                and isinstance(canvas.get("nodes"), list)):
            canvas = None
        try:
            res = _generator.write_blueprint(mode=mode, guard=True,
                                             prev_override=canvas)
        except Exception as e:
            return web.json_response({"ok": False, "error": "%r" % (e,)},
                                     status=500)
        res["version"] = __version__
        print("[cc_dashboard] 蓝图已生成：%s（mode=%s，备份=%s）"
              % (res.get("path"), mode, res.get("backup")))
        return web.json_response(res)

    return True


ensure_blueprint_installed()
_register_routes()

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS",
           "WEB_DIRECTORY", "__version__"]
