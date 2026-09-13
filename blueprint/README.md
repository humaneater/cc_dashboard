# blueprint/ —— 蓝图（工作流）这一半

这个目录负责「生成 `00_总控台.json`」这件事，和面板（`web/dock.js`）合起来才是完整插件。

## 文件

| 文件 | 作用 |
|---|---|
| `generator.py` | 蓝图的结构定义 + 用户改动结转 + 落盘。对外两个函数：`build_workflow(prev)` 只构造不写盘，`write_blueprint(mode, out_path, backup, guard, prev_override)` 构造并写盘 |
| `00_总控台.json` | **预置蓝图**。别人装完插件，工作流目录里没有同名文件时会自动放一份 |

## 蓝图结构（顶层三区，顺序就是工作流顺序）

```
A 图像共用前端：模型槽 → CLIP 取层(-2，ANIMA 自动旁路) → 提示词(正/负) → 文本编码 → 图像 LoRA 组
B 文生图：文生图子图 → 姿势 → 脸手眼矫正 → 高清化 → SaveImage(refined_*)
C 图生图精修：取图 LoadImageOutput → 图生图子图 → 脸手眼矫正#2 → 高清化#2 → SaveImage(refine_*)
D 视频：视频提示词 → 视频地基(UNET high/low + LoRA 组 + CLIP/VAE) → I2V / FLF2V / T2V → SaveVideo
```

模块与管线全是 **subgraph**：双击进去看内部连线，外面只暴露关键参数——
所以顶层不会拖得很长，面板只遥控那几个参数节点。

## 生成规则（改动必须知道的三件事）

1. **`properties.cc_dock_role` / `cc_dock_key` 是面板和蓝图之间的契约**。
   面板靠这两个字段认节点，`tools/check_dashboard.py` 会校验两边一致。
   改名会让面板找不到节点（你画布上的参数记忆也会失效）。
2. **结转按节点 id 走**：`carry_over()` 只认 id 和类型都一致的老节点，
   把你改过的模型槽 / LoRA / 参数 / 取图 / 提示词 / 开关状态搬过来。
   所以**改结构时尽量别改老节点的 id**，否则那部分用户设置会回到默认。
3. **旧默认值迁移**：`PARAM_MIGRATE` 里记着「以前的默认值本身有问题」的那几项，
   如果画布上还停在老默认（说明没动过），重建时自动升级；你自己调过的值一律保留。
4. **`BLUEPRINT_REV` 是给面板看的版本戳**（写进 `extra.cc_dashboard_blueprint`）。
   改了会影响出图结果的结构就 +1，面板的 `BLUEPRINT_REV` 要同步改——
   它和「高清链结构检查」一起，用来认出「画布上跑的还是旧蓝图」（顶上的橙色警告条）。

## 常用命令

```bash
python tools/gen_dashboard.py                 # 结转重建（平时用这个）
python tools/gen_dashboard.py --fresh         # 默认值重建
python tools/gen_dashboard.py --out X:\wf.json
python tools/gen_dashboard.py --preset        # 维护者：把默认蓝图写回 blueprint/00_总控台.json
```

面板调接口时会把自己的画布现况（`app.graph.serialize()`）一起传过来，
走的就是 `prev_override`：参数按**你现在画布上**的样子结转，结构永远来自 `build()`，
所以哪怕传的是旧画布，也只会救回参数、不会把旧结构带回来。

每次重建前会把现有蓝图备份到 `<ComfyUI>/user/default/cc_dashboard_backups/`。

## 改完怎么验

```bash
python tools/check_dashboard.py   # 结构 / 连线 / 旁路端口 / 面板契约 / 必需输入
python tools/t_sim.py             # 复刻前端 graphToPrompt：各管线各模块跑出来的节点集合
```

`tools/_object_info.json` 是节点定义的本地快照（跑 `python tools/dump_object_info.py`
刷新，要用 ComfyUI 自带的 python）。没有它，校验脚本会跳过基于节点定义的那部分检查。
