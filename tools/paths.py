# -*- coding: utf-8 -*-
"""cc_dashboard 的路径解析：插件目录、ComfyUI 根、工作流目录、备份目录。

只依赖标准库：插件被 ComfyUI 加载时用 folder_paths 拿用户目录，
在纯命令行下（ComfyUI 没起、甚至没装在旁边）走目录上溯的兜底。
"""
import os

WORKFLOW_NAME = "00_总控台.json"
PLUGIN_NAME = "cc_dashboard"


def plugin_dir():
    """<ComfyUI>/custom_nodes/cc_dashboard"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def comfy_root():
    """从插件目录往上找到 ComfyUI 根（认 main.py + folder_paths.py）。"""
    cur = plugin_dir()
    for _ in range(6):
        cur = os.path.dirname(cur)
        if not cur or cur == os.path.dirname(cur):
            break
        if os.path.exists(os.path.join(cur, "main.py")) \
                and os.path.exists(os.path.join(cur, "folder_paths.py")):
            return cur
    return os.path.dirname(os.path.dirname(plugin_dir()))


def user_dir():
    """ComfyUI 的用户配置目录（含 profiles），例如 <ComfyUI>/user/default。"""
    env = os.environ.get("CC_DASHBOARD_USER_DIR")
    if env:
        return os.path.abspath(env)
    root = comfy_root()
    try:                       # 服务里跑：直接用 ComfyUI 自己的解析结果
        import folder_paths
        base = folder_paths.get_user_directory()
        if base:
            cand = os.path.join(base, "default")
            return cand if os.path.isdir(cand) else base
    except Exception:
        pass
    return os.path.join(root, "user", "default")


def workflows_dir():
    return os.path.join(user_dir(), "workflows")


def workflow_path(name=WORKFLOW_NAME):
    return os.path.join(workflows_dir(), name)


def backup_dir():
    """备份放在 workflows 之外：免得备份文件混进工作流列表里。"""
    return os.path.join(user_dir(), "cc_dashboard_backups")


def backup_path(src_path, stamp=None):
    import time
    name = os.path.basename(src_path)
    stem, ext = os.path.splitext(name)
    stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
    return os.path.join(backup_dir(), "%s.%s%s" % (stem, stamp, ext or ".json"))


def blueprint_json():
    """插件自带的那份蓝图（别人装完插件就能直接用）。"""
    return os.path.join(plugin_dir(), "blueprint", WORKFLOW_NAME)


def object_info_path():
    """/object_info 的本地快照（离线校验用）。

    维护脚本 dump_object_info.py 会把它写进 tools/；ComfyUI 安装目录的上一层
    （比如 D:\\AI\\ComfyUI\\_object_info.json）里如果有，也认。多个都在时取最新的一份，
    免得用了过期快照还以为校验通过了。
    """
    cands = []
    env = os.environ.get("CC_DASHBOARD_OBJECT_INFO")
    if env:
        cands.append(env)
    root = comfy_root()
    cands.append(os.path.join(plugin_dir(), "tools", "_object_info.json"))
    cands.append(os.path.join(os.path.dirname(root), "_object_info.json"))
    cands.append(os.path.join(root, "_object_info.json"))
    cands.append(os.path.join(plugin_dir(), "blueprint", "_object_info.json"))
    alive = [p for p in cands if os.path.exists(p)]
    if not alive:
        return cands[1]
    return max(alive, key=lambda p: os.path.getmtime(p))


def web_dir():
    return os.path.join(plugin_dir(), "web")


def inside(path, root):
    """path 是否落在 root 里（防越界写盘）。"""
    p = os.path.normcase(os.path.abspath(path))
    r = os.path.normcase(os.path.abspath(root))
    return p == r or p.startswith(r + os.sep)
