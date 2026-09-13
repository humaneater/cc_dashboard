# -*- coding: utf-8 -*-
"""cc_dashboard 的维护脚本（命令行用，不影响 ComfyUI 运行）。

- paths.py           路径解析（插件目录 / 工作流目录 / 备份目录）
- gen_dashboard.py   生成蓝图：python tools/gen_dashboard.py
- check_dashboard.py 静态校验蓝图与面板契约
- t_sim.py           离线复刻前端 graphToPrompt 的场景矩阵
- t_dock.mjs         面板冒烟测试（需要 node）
- t_plugin.py        插件包自检（版本号 / 预置蓝图 / 接口）
- make_zip.py        打包成可分享的 zip
"""
