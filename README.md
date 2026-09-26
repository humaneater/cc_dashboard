# cc_dashboard —— ComfyUI 总控台

一个**纯本地**插件：给你一条「一条龙」多管线蓝图 + 一个浮动控制面板。

装完之后工作流列表里会多出一个 `00_总控台.json`：

```
文生图（多模型：Illustrious / ANIMA / 任意 SDXL ckpt）
   → 图生图精修（拿刚出的图继续改）
   → 图生视频 / 首尾帧 / 文生视频（Wan 2.2）
```

图像管线能挂三个模块（**姿势 / 脸手眼矫正 / 高清化**），视频管线能挂两个
（**视频高清化 / 视频补帧**），随时开关；
提示词、LoRA、参数全部收在一个**可拖动、可缩放、可弹出成独立窗口**的浮动面板上。

- 不联网、不下载权重、不调用任何外部 API（唯一可选下载是中→英 Opus-MT 模型，
  约 300 MB，装了也是本机离线跑，见「面板速览 → 中→英提示词翻译」）
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
| `CM_FloatBinaryOperation JK` / `CM_FloatToInt JK` | ComfyUI-JakeUpgrade |
| `UltimateSDUpscaleNoUpscale` | ComfyUI_UltimateSDUpscale |
| `YogurtStringConcat` | yogurtnodes |
| `OpenposePreprocessor` | comfyui_controlnet_aux |
| `RIFE_VFI_Opt` / `UpscaleWithModelAdvanced` | comfyui-WhiteRabbit（`https://github.com/Artificial-Sweetener/comfyui-WhiteRabbit`） |
| ANIMA 28 块 LoRA / LLLite 用在 40 块 2.9B 模型（无节点，启动时打补丁） | ComfyUI-Anima-LoRA-ControlNet-Patch（`https://github.com/INuBq8/ComfyUI-Anima-LoRA-ControlNet-Patch`） |

> 不知道缺哪个？打开蓝图时**面板顶上会有一条黄条**，点一下复制缺件清单，
> 再到 ComfyUI Manager → `Install Missing Custom Nodes` 一键装齐。
>
> 最后那个是**无节点补丁**，黄条检测不到它——但它决定了 28 块 ANIMA LoRA / LLLite
> 能不能在 40 块的 2.9B 模型上落到正确的层，装完要重启一次 ComfyUI。

---

## 二、模型清单

文件名不一样没关系：在画布上把下拉换成你自己的就行，面板是跟着画布走的。

| 用途 | 放哪个目录 | 蓝图默认用的文件 |
|---|---|---|
| 图像主模型（SDXL / Illustrious） | `models/checkpoints/` | `waiIllustriousSDXL_v170.safetensors` |
| 图像主模型（ANIMA） | `models/checkpoints/` | `oneObsession_anima29BV1.safetensors` |
| 文本编码器（ANIMA，外挂） | `models/text_encoders/` | `qwen_3_06b_base.safetensors`（约 1.1 GB） |
| VAE（ANIMA，外挂） | `models/vae/` | `qwen_image_vae.safetensors`（约 242 MB） |
| 姿势控制（SDXL） | `models/controlnet/` | `diffusion_pytorch_model_promax.safetensors`（ControlNet Union SDXL 1.0 Promax） |
| 姿势控制（ANIMA） | `models/model_patches/` | `anima-lllite-pose-1.safetensors` |
| 放大模型（图像高清化 + 视频高清化共用） | `models/upscale_models/` | `4xUltrasharp_4xUltrasharpV10.pt` |
| 补帧权重（RIFE） | `custom_nodes/comfyui-frame-interpolation/ckpts/rife/` | `rife47.pth`（约 21 MB，装 WhiteRabbit 时缺了自己会去 GitHub release 拉那份） |
| 视频主模型（Wan 2.2 I2V） | `models/diffusion_models/` | `wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors` + `wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors` |
| 视频主模型（GGUF 版，可选） | `models/diffusion_models/`（和上面同一个目录） | 比如 `wan22RemixI2VGGUFV20_highQ80.gguf` + `..._lowQ80.gguf`。要装 `ComfyUI-GGUF`，面板会自己把 406 / 407 换成 `UnetLoaderGGUF` |
| 视频加速 LoRA | `models/loras/` | `wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors` + `..._low_noise.safetensors` |
| 文本编码器（视频，外挂） | `models/text_encoders/` | `umt5_xxl_fp8_e4m3fn_scaled.safetensors` |
| VAE（视频，外挂） | `models/vae/` | `wan_2.1_vae.safetensors` |
| 脸 / 手 / 眼检测模型 | `models/ultralytics/bbox/` | `face_yolov8m.pt` / `hand_yolov8s.pt` / `Eyes.pt` |
| SAM 轮廓遮罩（可选，建议装） | `models/sams/` | `sam_vit_b_01ec64.pth`（约 375 MB）。没有这个文件就把面板上的「SAM 轮廓遮罩」取消，遮罩回到检测框矩形 |

### 模型资源：ANIMA / 视频为什么要外挂 文本编码器 + VAE

不是所有模型都自带「文本编码器（TE）」和「VAE」：

- **Illustrious / SDXL 的 ckpt** 是打包好的，一个文件里就有 `conditioner.`（TE）和
  `first_stage_model.`（VAE），**不用管这一行**。
- **ANIMA 的模型是裸 DiT**（里面只有 `model.diffusion_model.*` / `llm_adapter`），
  既没有 TE 也没有 VAE，**必须外挂**，不然加载就报错或出灰图。
- **Wan 2.2 这类视频模型本来就是分离式**：`UNETLoader` 只给模型本体，
  TE 和 VAE 永远要外挂。

面板在**模型下拉下面**多了一行「外挂资源」：`文本编码器` + `VAE` 两个下拉，
右边 `⟳` 重新拉清单（新丢进 `models\text_encoders` / `models\vae` 的文件点一下就能选，
不用重启），`⌖` 跳到画布上对应的节点（图像侧 110 / 111，视频侧 403 / 412）。

- **自带就不用管**：面板会读 ckpt 头部的张量名（只读几十毫秒，**不加载权重、不占显存**），
  自带 TE / VAE 的模型这一行会**自动收起来**，只留一个 `🛠 外挂` 小按钮
  （想给 SDXL 强换一个 VAE 时点它展开即可）。
- **缺什么显示什么**：裸 DiT 一选中就自动预填（ANIMA → `qwen_3_06b_base.safetensors`
  + `qwen_image_vae.safetensors`），建议直接出图；想换别的在下拉里挑。
- **每个模型记一份**：给某个模型选过的文件会记住，切走再切回来自动还原。
- 选「（用模型自带）」= 把画布上的来源开关（112 / 113）切回 1；选文件 = 切到 2。
  视频侧（403 / 412）没有「用模型自带」这一项，因为分离式模型必须外挂。
- 读不到头部（`.gguf` / 老 `.ckpt`）或插件没重启时，面板退回**按名字判断**
  （名字含 `anima` 就当裸模型），不会卡住。

两个 ANIMA 文件从官方仓库下（`circlestone-labs/Anima` 的 `split_files/`，
和 civitai 上那份是同一份文件）：

```bat
set HF_ENDPOINT=https://hf-mirror.com
python -c "from huggingface_hub import hf_hub_download as d; d('circlestone-labs/Anima','split_files/text_encoders/qwen_3_06b_base.safetensors',local_dir='.'); d('circlestone-labs/Anima','split_files/vae/qwen_image_vae.safetensors',local_dir='.')"
```

下完是这样两层目录（`split_files\...`），把文件搬到 ComfyUI 认的位置：

```bat
copy split_files\text_encoders\qwen_3_06b_base.safetensors  <ComfyUI>\models\text_encoders\
copy split_files\vae\qwen_image_vae.safetensors             <ComfyUI>\models\vae\
```

（视频侧那两个沿用 Wan 2.2 官方那套：`umt5_xxl_fp8_e4m3fn_scaled.safetensors` + `wan_2.1_vae.safetensors`。）

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
| 顶栏 6 个管线按钮 | 文生图 / 图生图精修 / 图生图 / 图生视频 / 首尾帧 / 文生视频。只让选中的那条 Save 出图，其它静音不白跑 |
| 图生图 vs 图生图精修 | 精修在原图尺寸上重绘（源图 2K 就出 2K），适合画完接着改；**图生图**先把源图缩到你选的分辨率（等比缩放 + 中心裁剪）再重绘，**出图尺寸固定等于面板上的宽 × 高**，P 图 / 换风格 / 固定尺寸出图用它。两条都用同一套模型 / 提示词 / LoRA / 重绘强度，也都能挂脸手眼矫正 + 高清化 |
| 图像模型下拉 | 管**文生图 / 图生图**（画布 101 模型槽）：Illustrious / ANIMA / 任意 ckpt。切到名字含 `anima` 的会自动套 30 步 / CFG 4.5 / 不取层 / 姿势换 LLLite |
| 外挂资源（模型下面一行） | `文本编码器` + `VAE` 两个下拉。**自带就自动收起**（只留 `🛠` 强制展开），裸模型（ANIMA 那类）缺什么显示什么并自动预填；`⟳` 重拉清单、`⌖` 跳到画布节点。图像侧 110 / 111、视频侧 403 / 412，视频那行恒显示（Wan 2.2 必须外挂）。详见「二、模型清单 → 模型资源」 |
| 视频模型 high / low | 管**图生视频 / 首尾帧 / 文生视频**（画布 406 / 407 两个加载器，safetensors 用 `UNETLoader`、GGUF 用 `UnetLoaderGGUF`，面板按文件后缀自动换）。Wan 2.2 这类模型是 high、low 两个专家各跑一半步数，必须成套：勾着「⇄ 成对」时改一个会自动把另一个换成配对的（`high_noise` ↔ `low_noise`、`highQ80` ↔ `lowQ80`、`Q8H` ↔ `Q8L` …），两边的族名对不上会在旁边出黄字。切管线时才显示对应的那一套 |
| 模块按钮 ×5 | 图像管线显示 姿势 / 脸手眼矫正 / 高清化，视频管线显示 视频高清化 / 视频补帧。内部走子图旁路，关掉不断链、不报错 |
| 脸手眼矫正 · 三级开关 | 参数页最上面那排勾：**脸 / 手 / 眼** 单独开关（关掉的那级走旁路，不检测不重绘）。手（hand_yolov8s）和眼（Eyes.pt）在多人交叠 / 复杂花纹上容易误检，误检一小块再重画就是「凭空长出多余的肢体 / 一片假眼」，遇到怪图先关这两个。旁边「SAM 轮廓遮罩」用 `models/sams/` 的 SAM 把检测框细化成贴合人物轮廓的遮罩（取消就回矩形遮罩） |
| 脸手眼矫正 · 尺寸 | 检测框放大尺寸（默认 512，Impact 默认值）/ 放大上限（1024）/ 裁剪倍率（2.5）。填 1024 会把 400px 的脸放大 2.5 倍再采样，模型在裁剪区里画「整张脸 + 头发 + 肩膀」，缩回去贴回原处 —— 看起来就是「脸被贴上去」，所以别往大调 |
| `⟳ 取图` / `↻ 同步` | 把最后产出的图传给下游（文生图 → 图生图精修 / 图生图 / 图生视频 / 首尾帧，图生图精修 → 图生图 / 视频，图生图 → 视频） |
| `◎` | 跟随执行：跑图时自动聚焦正在执行的节点（默认开） |
| `⧉` | 弹出成独立窗口（Chrome / Edge 的 Document PiP），可以拖到别的屏幕 |
| `📌` | 在「浮动窗」和「钉回窗口顶部通栏」之间切换 |
| 提示词页 | 正向 8 段可拼接，每段「手填 / 插件输入」二选一，`⌖` 跳到那一段去连线；负向就是一个整框 |
| LoRA 页 | 图像一份（文生图 / 图生图精修 / 图生图共用），视频 high / low 各一份；行数跟画布节点走，显示触发词与未启用提醒。每组的标题右边有**排序**（名称 A→Z / Z→A、下载时间 新→旧 / 旧→新，选择记在本地）和 **⟳ 刷新**（重扫 `models\loras`，刚下好的 LoRA 不用重启就能选；会告诉你新增了几个）。排序/刷新只动面板下拉，画布里那几行和你选中的那个不会被改掉 |
| 参数页 | 按模块分区（生成 / 姿势 / 脸手眼矫正 / 高清 / 视频生成 / 视频补帧 / 视频高清），**模块开着才显示**；鼠标悬停有说明；`↺ 重置默认值` 一键回默认 |
| 分辨率下拉 | 「★ 推荐」= **读模型头部算出来的训练分辨率**（只读张量表，不加载权重）：① 文件里写了（`ss_resolution` / `ss_bucket_info` / `modelspec.resolution`）直接用它，标「读自文件」；② 没写（本机 18 个成品 ckpt 实测 0 个写）就按张量结构判架构族 —— SDXL / Illustrious / ANIMA 1024²、SD1.5 512²、SD2.x 768²、FLUX / SD3 1024²、Wan 832×480；③ 读不到头部（.gguf）才退回按模型名猜。kohya 训练桶会额外列成选项；`⇄` 一键横竖互换，选「自定义」就手填宽高 |
| 采样器 / 调度器下拉 | 值直接从 KSampler 定义里拉（装了什么就有什么）；图像一套写文生图 + 图生图精修 + 图生图，视频一套写 I2V / 首尾帧 / T2V，各改各的、互不串味。**默认值按模型族取**：SDXL `dpmpp_2m + karras`、ANIMA 这类流匹配模型 `er_sde + simple`；切到 ANIMA 时若调度器还停在 `karras` 会自动换成 `simple`，手动选回去会在那一行下面出黄字 |
| 说明页 | 每个模块的原理、参数怎么调、以及生成 / 更新蓝图按钮 |

### 中→英提示词翻译

提示词框里可以直接写中文：

- 每段行尾的 **「译」** 翻这一段；提示词组标题的 **「中→英」** 一次翻完整组。
- 装了本机 **Opus-MT**（可选，约 300 MB，**纯离线**）时就是**真翻译**：含中文的文本
  一律走模型，长句先切成小句、再按预算合并成块逐块翻译拼回，**不截断丢尾**，
  译完状态栏标「NMT」。第一次点「译」才加载模型（1–3 秒；模型权重约 0.3 GB，
  只用系统内存、**不占显存**），之后常驻复用，随 ComfyUI 关闭释放。
- 没装模型（或加载失败）时自动回落到内置绘画词典：1000+ 词、danbooru 风格标签
  （`1girl` / `long hair` / `smile`），空段自动跳过、纯英文段不动，
  没收录的词在右边黄字列出、不会被硬译。**纯本地、不联网。**
- 装模型（ModelScope 优先、失败自动换 hf-mirror，断点续传）：

  ```bat
  cd custom_nodes\cc_dashboard
  ..\..\python_embeded\python.exe tools\install_translate.py
  ```

  装完**重启一次 ComfyUI**（改的是后端模块）；之后浏览器 Ctrl+Shift+R 刷新即可。
  查状态：`python tools\install_translate.py --status`；
  验效果：`python tools\t_translate.py`（会打印短标签 / 长句 / 长段落的译文与耗时）。
  环境变量 `CC_TRANSLATE_KEEP=0` 可改成“翻完就卸”，`CC_TRANSLATE_BEAMS=2` 可以更快。
- 画布上还有一个节点 **「中→英 翻译（提示词）」**（`CCTranslateZhEn`）：
  输入中文、输出英文；`engine=auto`（默认）装了模型就是真翻译，`engine=dict`
  可强制只用词典（要纯 danbooru 标签时用），`missed` 口列出词典没收录的词。

---

## 五、视频后处理：高清化 → 补帧

三条视频管线（图生视频 / 首尾帧 / 文生视频）在采样结束之后各挂了一行后处理，
都是子图模块，**默认关着**，面板上点一下就开：

```
采样出帧 → [视频高清化] → [视频补帧] → 合成视频 → 保存
```

顺序是写死的：**先放大再补帧**。反过来的话补出来的帧也要一起过 4 倍放大，
时间差不多翻倍、显存也顶不住。

| 模块 | 面板参数 | 说明 |
|---|---|---|
| 视频高清化 | 目标倍数（默认 2）、放大模型倍率（默认 4）、每批帧数（默认 4）、分块大小（0=自动） | 逐帧用放大模型（和图像高清化共用 `4xUltrasharp`）放大，再按 `目标倍数 ÷ 放大模型倍率` 缩回。纯像素操作，**不做扩散采样**，所以不会像图像高清化那样把画面重构掉，也不吃 CFG |
| 视频补帧 | 补帧倍数（默认 2） | RIFE 在相邻两帧之间插帧（`rife47.pth`）。2 倍 = 每两帧插 1 帧，帧数和帧率一起翻倍，**播放速度和时长都不变**（16fps 81 帧 → 32fps 161 帧） |

几个容易踩的点：

- 「目标倍数」跟图像那套一样是**填几就是几倍**：填 2 就是 640×640 → 1280×1280。
  面板上「视频高清参数 → 输出尺寸」会直接报出最终尺寸和实际缩回系数。
- 高清化只补像素不补细节。源素材本身就糊的地方，放大完还是糊——
  真要清晰得从采样那头加步数 / 降分辨率压力。
- 补帧同理：源素材抖动、糊帧的地方，插出来的中间帧只会把抖动抹成拖影。
  常规 2 倍就够，`≥4` 面板会给橙字提醒。
- **显存不够**（OOM / 卡在放大那段）：先把「每批帧数」从 4 降到 2 或 1，
  再不行把「分块大小」从 0 改成 512 / 256。慢一点但不会炸。
- 补帧后帧率由面板自动写进合成节点，不用手动改；`视频生成参数 → 帧率`
  只管采样的帧率。

---

## 六、生成 / 更新蓝图

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

## 七、常见问题

**面板没出现？**
确认 `custom_nodes/cc_dashboard/web/dock.js` 在，然后 `Ctrl+Shift+R`。面板只认带
`cc_dock_role` 标记的蓝图（也就是 `00_总控台.json` 这种），别的图它不出来。

**顶上黄条说缺节点？**
点黄条复制清单 → Manager → `Install Missing Custom Nodes` → 重启。

**LoRA 没锁住角色？**
看 LoRA 行下面的状态：`⚠ 已选但未启用`（取消勾选又选了文件）或
`⚠ 与当前模型族可能不匹配`（ANIMA 模型配了 IL 系 LoRA）。有触发词的话要写进提示词。

**ANIMA LoRA 在 2.9B（40 块）模型上感觉完全没生效？**
这是 Anima 28 块底模 → 40 块 2.9B 的「插入式加深」：2.9B 在原有 28 块之间插了 12 块，
对应关系是 `0→0、1→1、2→3、3→4、4→6 … 27→39`（上游用真实权重逐张量对出来的表）。
不装兼容补丁时，`blocks.2` 以后的键名在 40 块模型里也都存在，所以 ComfyUI **不会报
`lora key not loaded`**，但权重落到了错误的层——表现就是「LoRA 没效果 / 强度拉高只会越
来越糊」。装 `ComfyUI-Anima-LoRA-ControlNet-Patch` 后会在加载时自动重映射
（28↔40↔52，双向）；本机实测 `qingxiao_anima_v1` / `_clean` / `light_lora` / `silhouette`
四条 28 块 LoRA 都会被移到 0/1/3/4/6…39，`anima-lllite-pose-1.safetensors` 这个 28 块
LLLite 也会一起重映射到 40 块模型。

重映射后上游建议先把 LoRA 强度从 **0.6~0.8** 试起（残差多经过 12 个新块，1.0 容易过强）。
另外 `qingxiao_anima_lora_clean` 的 alpha/rank = **8/16**，面板写强度 1.0 时实际只有
0.5；想按 1.0 的强度用就换 `qingxiao_anima_v1`（32/32），或把强度相应调高。
触发词方面：`v1` 的元数据里角色标签是 `qingxiaowuwa`（`_clean` 版元数据被清空，面板
读不到触发词），锁角色时把它写进正向提示词。

**刚下载的 LoRA 在面板下拉里看不到？**
点那一组标题右边的 **⟳**：面板会让 ComfyUI 丢掉目录缓存、重新扫一遍 `models\loras`
（含子目录），扫完提示「新增 N 个」，新文件立刻能选，**不用重启**。
顺序用标题右边的**排序**换：`名称 ↑/↓` 按文件名，`时间 ↓/↑` 按文件修改时间
（刚下完的在最前/最后），选择记在本地、下次打开还是它。排序和刷新都只改面板下拉，
**不会动画布上那几行**，你正选着的那个 LoRA 也不会被冲掉。
（后端接口 `GET /cc_dashboard/loras` 是 v1.9.3 加的，旧进程重启一次才有——
在那之前 ⟳ 走核心 `/object_info`，能刷出新文件，只是「按时间排序」用不了。）

**分辨率推荐老是 1024×1024，是不是没读模型？**
是读了，只是**大部分成品 ckpt 里压根没写训练分辨率**。面板从 v1.9.2 起三级取值：

1. `__metadata__` 里作者写了 `ss_resolution` / `ss_bucket_info` / `modelspec.resolution`
   → 直接用，推荐项会标「**读自文件**」；
2. 没写（本机 18 个 ckpt 实测 0 个写）→ 后端读**张量表**判架构族，
   SDXL / Illustrious 1024²、SD1.5 512²、SD2.x 768²、SD3 / FLUX 1024²、ANIMA 1024²、
   Wan 832×480，悬停推荐项能看到「**按模型结构判定：…**」；
3. 读不了头部（`.gguf`、非 safetensors）→ 才退回按**模型名**猜。

判定依据是张量名和形状，不是文件名：Illustrious 靠 `label_emb.0.0.weight` + 第二个
`conditioner.embedders.1`，ANIMA 靠 `llm_adapter`，Wan 2.2 靠
`patch_embedding.weight` 的 `[dim, in_ch, 1, 2, 2]` 形状。**改这条逻辑、加新架构后要重启一次
ComfyUI**（探测在 Python 侧）；只改面板 JS 刷新页面即可。诊断命令：
`python tools\t_modelinfo.py`。

**整个画面被洗白 / 只剩一层很淡的轮廓（换到 ANIMA 之后尤其常见）？**
ANIMA 和 Wan 2.2 都是**流匹配（flow matching）模型**，`KSampler` 的**调度器**必须是
`simple` / `beta` / `sgm_uniform` / `ddim_uniform`。`karras`、`exponential` 这类给扩散模型
退火的调度套上去会把噪声计划错配 —— 实测整张图均值 254、对比度 3，就是一片灰白，
换个种子偶尔又「正常」一次（其实是被别的噪声救回来了）。

v1.9.1 起不用自己记：切到 ANIMA 时面板**自动把 karras 换成 simple**，采样器默认给
`er_sde`（官方推荐），`↺ 重置默认值` 也按当前模型族取默认；你要是手动选回 karras，
那一行下面会出黄字提醒（值照样写进画布，不偷偷改你的选择）。

顺带说明：**外挂 VAE 不是这个问题的原因**。选完 VAE 面板会回一句
`✔ VAE 已写进画布 111，来源开关 113 → 外挂`，说明真的生效了；想要硬证据就看
Execution 日志里 `CR VAE Input Switch` 的 `Input` 是不是 2（2 = 走外挂 111）。
v1.9.1 之前那行下拉看起来会自己弹回「用模型自带」，那是清单刷新时的显示 bug ——
画布值从来没被改掉。

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

**切到视频管线之后，图像模型下拉不见了？**
面板按管线过滤：图像管线（文生图 / 图生图）显示**图像模型**，视频管线（图生视频 /
首尾帧 / 文生视频）显示**视频模型 high / low**。两套是分开的，改哪个都不影响另一套 ——
以前视频权重只能去画布上找那两个 `UNETLoader` 改，现在在面板顶栏就能换。

**视频模型下拉里的 high / low 要怎么选？**
Wan 2.2 是「两个专家」的模型：high noise 跑前半段、low noise 跑后半段，所以两个必须是
**同一套权重的两种噪声档**。勾着「⇄ 成对」时改一个会自动配另一个；想混搭（比如 i2v 的
high 配 t2v 的 low）就取消勾选，改错了面板会给黄字。

配对认这些写法：`high_noise ↔ low_noise`、`highQ80 ↔ lowQ80`、`Q8H ↔ Q8L`、
`_high ↔ _low`、以及文件名结尾的 `...14BHigh ↔ ...14BLow`。**另一档不在清单里就不动**
（比如只有 High 的半套），不会硬凑。

**safetensors 和 GGUF 混着用行吗？**
行，同一张下拉里都列着（GGUF 那几行后面标了「（GGUF）」）。选 `.gguf` 时面板会把画布上
的 406 / 407 换成 `UnetLoaderGGUF`，选回 safetensors 再换回核心 `UNETLoader`，下游连线
不动。前提是本机装了 `ComfyUI-GGUF`，没装的话 `.gguf` 根本不会出现在清单里 ——
这也是为什么 `.gguf` 不用从 `models/unet/` 挪到 `models/diffusion_models/`：
两个目录本来就是同一批，两类加载器各读各的。

**补帧 / 视频高清化按钮点了没反应？**
这两个模块只属于视频管线：切到「图生视频 / 首尾帧 / 文生视频」才会出现。
在图像管线（文生图 / 图生图）下面它们是不显示的。

**补帧要另外下模型吗？**
不要。RIFE 的 `rife47.pth` 是 `comfyui-frame-interpolation` 自带的，
已经在 `custom_nodes/comfyui-frame-interpolation/ckpts/rife/` 里（21 MB）。
视频高清化复用的是图像那套 `models/upscale_models/` 放大模型，不用额外下东西。

---

## 八、目录结构 / 维护脚本

```
cc_dashboard/
  __init__.py            插件入口：WEB_DIRECTORY + 本地接口 + 翻译节点 + 首次放置蓝图
  translate.py           中→英翻译（本机 Opus-MT 真翻译 + 词典兜底）+ 画布节点
  web/dock.js            浮动面板（唯一的前端代码）
  web/zh_en_dict.json    绘画提示词词典（1000+ 词，面板与节点共用）
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
    install_translate.py 可选：下载 Opus-MT 中英模型（约 300 MB）
    t_translate.py       翻译自检：短标签 / 长句 / 长段落（切块不丢尾）/ 模型复用
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

## 九、许可

MIT，见 [LICENSE](LICENSE)。
