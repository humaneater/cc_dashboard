# cc_dashboard —— ComfyUI 总控台

一个**纯本地**插件：给你一条「一条龙」多管线蓝图 + 一个浮动控制面板。

装完之后工作流列表里会多出一个 `00_总控台.json`：

```
文生图（多模型：Illustrious / ANIMA / 任意 SDXL ckpt）
   → 图生图精修（拿刚出的图继续改）
   → 图生视频 / 首尾帧 / 文生视频（Wan 2.2）
```

每条管线上都能挂三个模块（**姿势 / 脸手眼矫正 / 高清化**），随时开关；
提示词、LoRA、参数全部收在一个**可拖动、可缩放、可弹出成独立窗口**的浮动面板上。

- 不联网、不下载权重、不调用任何外部 API
- 面板只在带 `cc_dock_role` 标记的蓝图里出现，不影响你其它工作流
- 蓝图可以一键重建（结转你现在用的模型 / 提示词 / LoRA / 参数，写前自动备份）
- 面板第二排就是**队列**：数量（▲ 翻倍 / ▼ 减半）、▶ 运行、⇥ 插队、✕ 停止、活动任务数
  （点数字开任务历史）——跑图不用再去找 ComfyUI 顶栏那排

---

## 一、先装这些插件包（必需）

蓝图用到了第三方节点，**装漏了不会崩，只会出不了图**：

| 蓝图里用到的节点 | 来自哪个插件包 |
|---|---|
| `Power Lora Loader (rgthree)` | rgthree-comfy |
| `FaceDetailer` | ComfyUI-Impact-Pack |
| `UltralyticsDetectorProvider` | ComfyUI-Impact-Subpack |
| `ColorMatch` | comfyui-kjnodes |
| `CR Upscale Image` / `CR Clip Input Switch` / `CR VAE Input Switch` | ComfyUI_Comfyroll_CustomNodes |
| `CR Text Input Switch JK` | ComfyUI-JakeUpgrade |
| `UltimateSDUpscaleNoUpscale` | ComfyUI_UltimateSDUpscale |
| `YogurtStringConcat` | yogurtnodes |
| `OpenposePreprocessor` | comfyui_controlnet_aux |

> 不知道缺哪个？打开蓝图时**面板顶上会有一条黄条**，点一下复制缺件清单，
> 再到 ComfyUI Manager → `Install Missing Custom Nodes` 一键装齐。

---

## 二、模型清单

文件名不一样没关系：在画布上把下拉换成你自己的就行，面板是跟着画布走的。

| 用途 | 放哪个目录 | 蓝图默认用的文件 |
|---|---|---|
| 图像主模型（SDXL / Illustrious） | `models/checkpoints/` | `waiIllustriousSDXL_v170.safetensors` |
| 图像主模型（ANIMA） | `models/checkpoints/` | `oneObsession_anima29BV1.safetensors` |
| ANIMA 文本编码器 | `models/text_encoders/` | `qwen_3_06b_base.safetensors` |
| 姿势控制（SDXL） | `models/controlnet/` | `diffusion_pytorch_model_promax.safetensors`（ControlNet Union SDXL 1.0 Promax） |
| 姿势控制（ANIMA） | `models/model_patches/` | `anima-lllite-pose-1.safetensors` |
| 放大模型 | `models/upscale_models/` | `4xUltrasharp_4xUltrasharpV10.pt` |
| 视频主模型（Wan 2.2 I2V） | `models/diffusion_models/` | `wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors` + `wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors` |
| 视频加速 LoRA | `models/loras/` | `wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors` + `..._low_noise.safetensors` |
| 视频文本编码器 | `models/text_encoders/` | `umt5_xxl_fp8_e4m3fn_scaled.safetensors` |
| VAE（ANIMA / 视频共用） | `models/vae/` | `wan_2.1_vae.safetensors` |
| 脸 / 手 / 眼检测模型 | `models/ultralytics/bbox/` | `face_yolov8m.pt` / `hand_yolov8s.pt` / `Eyes.pt` |
| SAM 轮廓遮罩（可选，建议装） | `models/sams/` | `sam_vit_b_01ec64.pth`（约 375 MB）。没有这个文件就把面板上的「SAM 轮廓遮罩」取消，遮罩回到检测框矩形 |

---

## 三、安装

### 方式 A：拿到 zip（最简单）

1. 把 zip 解压到 `<ComfyUI>/custom_nodes/`，结果应该是
   `<ComfyUI>/custom_nodes/cc_dashboard/__init__.py`
2. 重启 ComfyUI，浏览器 `Ctrl+Shift+R`
3. 打开工作流列表里的 `00_总控台`（首次安装会自动放一份）

### 方式 B：从 Git 仓库装（方便更新）

ComfyUI Manager → `Install via Git URL` → 填
`https://github.com/humaneater/cc_dashboard` → 装完重启。
以后更新：Manager 里点 Update，或 `git pull`。

### 方式 C：手动拷目录

把整个 `cc_dashboard/` 目录拷到 `<ComfyUI>/custom_nodes/` 下，重启。

---

## 四、面板速览

面板是个浮动窗：**拖标题栏移动、拖边角缩放**，位置尺寸自动记住。

| 位置 | 作用 |
|---|---|
| 顶栏 5 个管线按钮 | 文生图 / 图生图精修 / 图生视频 / 首尾帧 / 文生视频。只让选中的那条 Save 出图，其它静音不白跑 |
| 模型下拉 | 覆盖 Illustrious / ANIMA / 其它 ckpt。切到名字含 `anima` 的模型会自动套 30 步 / CFG 4.5 / 不取层 / 姿势换 LLLite |
| 模块按钮 ×3 | 姿势 / 脸手眼矫正 / 高清化。内部走子图旁路，关掉不断链、不报错 |
| 脸手眼矫正 · 三级开关 | 参数页最上面那排勾：**脸 / 手 / 眼** 单独开关（关掉的那级走旁路，不检测不重绘）。手（hand_yolov8s）和眼（Eyes.pt）在多人交叠 / 复杂花纹上容易误检，误检一小块再重画就是「凭空长出多余的肢体 / 一片假眼」，遇到怪图先关这两个。旁边「SAM 轮廓遮罩」用 `models/sams/` 的 SAM 把检测框细化成贴合人物轮廓的遮罩（取消就回矩形遮罩） |
| 脸手眼矫正 · 尺寸 | 检测框放大尺寸（默认 512，Impact 默认值）/ 放大上限（1024）/ 裁剪倍率（2.5）。填 1024 会把 400px 的脸放大 2.5 倍再采样，模型在裁剪区里画「整张脸 + 头发 + 肩膀」，缩回去贴回原处 —— 看起来就是「脸被贴上去」，所以别往大调 |
| `⟳ 取图` / `↻ 同步` | 把最后产出的图传给下游（文生图 → 图生图 / 图生视频 / 首尾帧） |
| `◎` | 跟随执行：跑图时自动聚焦正在执行的节点（默认开） |
| `⧉` | 弹出成独立窗口（Chrome / Edge 的 Document PiP），可以拖到别的屏幕 |
| `📌` | 在「浮动窗」和「钉回窗口顶部通栏」之间切换 |
| 提示词页 | 正向 8 段可拼接，每段「手填 / 插件输入」二选一，`⌖` 跳到那一段去连线；负向就是一个整框 |
| LoRA 页 | 图像一份（文生图 + 图生图共用），视频 high / low 各一份；行数跟画布节点走，显示触发词与未启用提醒 |
| 参数页 | 按模块分区（生成 / 姿势 / 脸手眼矫正 / 高清 / 视频），**模块开着才显示**；鼠标悬停有说明；`↺ 重置默认值` 一键回默认 |
| 分辨率下拉 | 每个模型族的「★ 推荐」= 训练分辨率（SDXL / Illustrious / ANIMA 1024×1024、SD1.5 512×512），另收 SDXL 官方训练桶与主流 16:9 / 9:16；`⇄` 一键横竖互换，选「自定义」就手填宽高 |
| 采样器 / 调度器下拉 | 值直接从 KSampler 定义里拉（装了什么就有什么）；图像一套写文生图 + 图生图，视频一套写 I2V / 首尾帧 / T2V，各改各的、互不串味 |
| 说明页 | 每个模块的原理、参数怎么调、以及生成 / 更新蓝图按钮 |

---

## 五、生成 / 更新蓝图

三种入口，效果一样（写盘前都会先备份旧版）：

1. 面板「说明」页 → `🏗 生成 / 更新蓝图`（结转你现在画布上的模型 / 提示词 / LoRA / 参数）
2. 面板「说明」页 → `🧱 以默认值重建`（忽略画布改动，回到出厂值）
3. 命令行（在插件目录下）：

```bash
python tools/gen_dashboard.py            # 结转重建
python tools/gen_dashboard.py --fresh    # 默认值重建
python tools/gen_dashboard.py --out D:\somewhere\wf.json
```

备份写在 `<ComfyUI>/user/default/cc_dashboard_backups/`（故意放在工作流目录外，
免得备份混进工作流列表）。

---

## 六、常见问题

**面板没出现？**
确认 `custom_nodes/cc_dashboard/web/dock.js` 在，然后 `Ctrl+Shift+R`。面板只认带
`cc_dock_role` 标记的蓝图（也就是 `00_总控台.json` 这种），别的图它不出来。

**顶上黄条说缺节点？**
点黄条复制清单 → Manager → `Install Missing Custom Nodes` → 重启。

**LoRA 没锁住角色？**
看 LoRA 行下面的状态：`⚠ 已选但未启用`（取消勾选又选了文件）或
`⚠ 与当前模型族可能不匹配`（ANIMA 模型配了 IL 系 LoRA）。有触发词的话要写进提示词。

**修完偏红 / 饱和度变高？**
脸手眼矫正和放大链末尾各有一道**色彩回正（ColorMatch）**，专门压这个。
还偏就把「脸重绘 / 手重绘」降到 0.25 左右——重绘强度越高越容易偏色。

**画面里凭空长出多余的肢体 / 一片假眼 / 脸像被贴上去？**
几乎都是脸手眼矫正那三级干的，按这个顺序排：

1. 看「手重绘」和「眼重绘」——≥0.35 / ≥0.30 就不是「修」而是「重画那一块」了。
   面板会在这两行下面直接给黄字提醒。手那级用的 `hand_yolov8s` 在肢体交叠处极易误检，
   误检一小块再按 0.6 重画，就是一条多余的胳膊。
2. 看「检测框放大尺寸」——填 1024 时，一张 400px 的脸会被放大 2.5 倍再采样，
   模型于是在裁剪区里画「整张脸 + 头发 + 肩膀」，缩回去贴到原处，看起来就是脸被贴上去。
   默认 512 就是 Impact 自己的值，别往大调。
3. 还不对就把**手 / 眼**两个勾取消（只留脸，脸的检测器最准），再不行整块关掉对比。

多人交叠的构图配 `1girl, solo` 这种提示词时，脸那级会按「单人」重画一块，也会打架。

**高清化之后像很多张拼起来？**
先降「整体细化强度」到 0.08~0.10，再降「分块精修强度」到 0.08~0.10，
把「接缝修复强度」加到 0.35~0.40；还重就把高清倍数降到 1.5 或直接关掉高清化模块。
（详细原理见画布上那张「高清化」说明卡）

**「高清倍数」填 2 出来是几倍？**
就是 2 倍。链子里只有**一次**放大，最终尺寸 = 原图 × 倍数。

**面板写 2 倍，出图却是 4 倍？（顶上一条橙色警告）**
那说明画布里跑的**不是磁盘上最新的蓝图**。两种常见来源：

- ComfyUI 前端打开时会恢复「上次内存里那份图」，而不是磁盘上最新那份；
  插件、蓝图更新之后如果只刷新页面、没重新打开 `00_总控台.json`，就会这样。
- 你手动改过高清链（比如自己接了个 4x 放大模型再缩回一半）。

橙条右边有个 **`载入最新蓝图`**：点一下会拿你现在画布上的提示词 / LoRA / 参数做结转，
把节点结构换成当前版本，然后直接载进画布，不用手动找文件。
同时「参数 → 高清参数 → 输出尺寸」也会临时报**真会出来的尺寸**，不会再出现面板和出图对不上的情况。

**每次出图种子都一样？**
参数页「种子」右边的 `🎲 随机` 默认是开的；关掉它就按输入框里的数字慢慢调。

---

## 七、目录结构 / 维护脚本

```
cc_dashboard/
  __init__.py            插件入口：WEB_DIRECTORY + 两个本地接口 + 首次放置蓝图
  web/dock.js            浮动面板（唯一的前端代码）
  blueprint/
    generator.py         蓝图生成器（build_workflow / write_blueprint）
    00_总控台.json        预置蓝图（随插件分发给别人）
  tools/                 命令行维护脚本，不影响 ComfyUI 运行
    paths.py             路径解析（ComfyUI 根 / 工作流目录 / 备份目录）
    gen_dashboard.py     生成蓝图
    check_dashboard.py   静态校验蓝图（节点 / 连线 / 旁路端口 / 面板契约）
    t_sim.py             离线复刻前端 graphToPrompt 的场景矩阵
    t_dock.mjs           面板冒烟测试（需要 node）
    t_plugin.py          插件包自检（版本号 / 预置蓝图 / 接口装载）
    dump_object_info.py  落一份 /object_info 快照（离线校验用）
    make_zip.py          打包成可分享的 zip
```

改完蓝图或面板，跑一遍这几条再发出去：

```bash
python tools/t_plugin.py
python tools/check_dashboard.py
python tools/t_sim.py
node   tools/t_dock.mjs
```

分享给别人怎么打包 / 建仓库 / 发更新：见 [SHARE.md](SHARE.md)。

---

## 八、许可

MIT，见 [LICENSE](LICENSE)。
