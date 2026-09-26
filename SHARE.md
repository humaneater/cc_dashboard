# 怎么把这套工具分享给别人

插件目录本身就是一套自包含的包：`cc_dashboard/`。
发给别人有两条路——**发 zip** 和 **建 Git 仓库**，两条都建议留一份。

---

## 0. 发之前先自检

> **发布节奏（约定）**：改完先跑自检，再让用户在 ComfyUI 里**实测跑通**，
> 确认没问题之后才 commit / push / 打 tag / 发 Release。
> 没测过就只留在本地 —— 本地改动本来也不需要联网。

在 `<ComfyUI>/custom_nodes/cc_dashboard/` 目录下跑：

```bash
python tools/t_plugin.py        # 版本号一致 / 预置蓝图没落后 / 接口装载正常
python tools/check_dashboard.py # 蓝图结构、旁路端口、面板契约
python tools/t_sim.py           # 各管线各模块的执行集合
node   tools/t_dock.mjs         # 面板行为（需要 node，没有就跳过）
python tools/t_translate.py     # 翻译自检（装了 Opus-MT 才跑；没装可跳过）
python tools/t_modelinfo.py     # 模型头部探测（架构族 / 训练分辨率 / 缺不缺 TE·VAE）
python tools/t_lorainfo.py      # LoRA 清单（名字 + 文件时间 + 刷新重扫）
```

全绿再往外发。`t_plugin.py` 还会提醒你「预置蓝图落后于生成器」——
那说明你改了生成器但没刷新 `blueprint/00_总控台.json`，跑一次下面这条即可：

```bash
python tools/gen_dashboard.py        # 顺手刷新你自己的工作流（会结转你的参数）
python tools/gen_dashboard.py --preset   # 刷新预置蓝图（纯默认值，发出去的就是这份）
```

> 预置蓝图必须是**默认值**那份。别直接把 `user/default/workflows/00_总控台.json`
> 拷成预置——那里面带着你的模型槽、LoRA、提示词。

改过会影响出图结果的结构时，记得把 `blueprint/generator.py` 和 `web/dock.js`
里的 `BLUEPRINT_REV` 一起 +1，否则老用户那台机器上的面板认不出自己跑的是旧蓝图。

---

## 1. 发给别人：zip（最省事）

```bash
python tools/make_zip.py
```

产出 `dist/cc_dashboard-<版本>.zip`，里面只有一层 `cc_dashboard/` 目录。
别人拿到之后：

1. 解压到 `<ComfyUI>/custom_nodes/` → 得到 `<ComfyUI>/custom_nodes/cc_dashboard/`
2. 重启 ComfyUI，浏览器 `Ctrl+Shift+R`
3. 打开工作流列表里的 `00_总控台`

想先看看包里都有什么：`python tools/make_zip.py --list`

---

## 2. Git 仓库（方便别人更新）

这套工具的公开仓库已经建好了：

**https://github.com/humaneater/cc_dashboard**（public）

别人装的时候走 ComfyUI Manager：
`Install via Git URL` → 填 `https://github.com/humaneater/cc_dashboard` → 重启。
以后更新：Manager 里点 Update，或 `git pull`。

### 如果你想换成自己的账号

先在 `pyproject.toml` 和 `README.md` 里把
`https://github.com/humaneater/cc_dashboard` 换成你自己的仓库地址，然后：

```bash
cd <ComfyUI>/custom_nodes/cc_dashboard
git remote set-url origin https://github.com/<你的账号>/cc_dashboard.git
git push -u origin main --tags
```

> 仓库是公开还是私有都行；私有仓库对方要有权限。

---

## 3. 以后怎么发更新

1. 改代码 / 改蓝图
2. **三处版本号一起改**（有一个脚本会帮你检查）：
   - `__init__.py` 里的 `__version__`
   - `web/dock.js` 里的 `CC_DASHBOARD_VERSION`
   - `pyproject.toml` 里的 `version`
3. 跑第 0 节的自检（全绿）
4. 提交并打新 tag：

```bash
git add . && git commit -m "cc_dashboard v1.0.1"
git tag v1.0.1 && git push && git push --tags
```

5. 对方怎么升级：
   - Git 装的：Manager 里点 `Update`，或自己 `git pull`
   - zip 装的：重新解压覆盖（他们的模型选择、LoRA、提示词、参数都在自己那边的
     `00_总控台.json` + 浏览器 localStorage 里，**覆盖插件目录不会丢**）

---

## 4. 别人装完插件，还要装什么

插件只带「面板 + 蓝图」，不含节点包和权重。对方还要：

1. **第三方节点包**：见 `README.md` 第一节；最省事的办法是打开蓝图后
   点面板顶上的**黄条**复制缺件清单 → Manager → `Install Missing Custom Nodes`
2. **ANIMA 2.9B 兼容补丁（无节点，黄条检测不到）**：装
   `ComfyUI-Anima-LoRA-ControlNet-Patch`
   （`https://github.com/INuBq8/ComfyUI-Anima-LoRA-ControlNet-Patch`）。
   28 块的 ANIMA LoRA / LLLite 放到 40 块的 2.9B 模型上不会报错，但会静默落到错误的层
   （表现是「LoRA 完全没生效」）；这个补丁在加载时自动做 28↔40↔52 双向重映射，
   装完重启一次，控制台会打印 `[Anima LoRA/ControlNet Patch] ... installed`。
3. **模型权重**：见 `README.md` 第二节；文件名不一样没关系，
   在画布上把下拉换成他们自己的即可。**外挂的 文本编码器 / VAE 也算权重**：
   ANIMA 那类裸 DiT 要 `models/text_encoders/qwen_3_06b_base.safetensors` +
   `models/vae/qwen_image_vae.safetensors`，Wan 2.2 要 `umt5_xxl_...safetensors` +
   `wan_2.1_vae.safetensors`（面板那一行「外挂资源」会自己认，缺件时自动预填）

---

## 5. 可选：上架 ComfyUI 官方 Registry

想让别人在 Manager 里**搜到插件名字**（而不是填 Git URL）时再走这条路：

1. 到 `registry.comfy.org` 注册并拿到 Publisher ID
2. 把 `pyproject.toml` 的 `[tool.comfy] PublisherId` 填成那个 ID
3. 装 `comfy-cli`，在插件目录里执行发布命令（`comfy node publish`）

只要发 zip / 自建 git 仓库的话，这一步可以永远不做（`PublisherId` 留空即可）。

---

## 6. 红线（别把不该发的发出去）

- **不要提交** `tools/_object_info.json`（那台机器上装了哪些节点，别人没用）、
  备份目录、`dist/`、`__pycache__/`（`.gitignore` 已经挡掉）
- **不要打包模型权重**：几十 GB，别人自己下。中→英的可选 Opus-MT 模型
  （约 300 MB，装在 `<ComfyUI>/models/cc_dashboard/opus-mt-zh-en`）同理**不进 zip**，
  对方跑一次 `python tools/install_translate.py` 就有（不装就自动用内置词典）
- 外挂的 **文本编码器 / VAE**（`models/text_encoders/`、`models/vae/` 里那几份，
  Qwen3-0.6B 1.1 GB、qwen_image_vae 242 MB、umt5 / wan_2.1_vae）同样**不进 zip**，
  对方按 `README.md` 第二节里的命令行自己下
- 蓝图里存的是**模型文件名**和提示词，不含绝对路径、不含你的账号信息，可以放心分享；
  但如果你在提示词里写了私人内容，发之前自己扫一眼

---

## 7. 一句话版本

```bash
python tools/t_plugin.py && python tools/check_dashboard.py && python tools/t_sim.py \
  && node tools/t_dock.mjs && python tools/t_translate.py && python tools/t_modelinfo.py \
  && python tools/t_lorainfo.py && python tools/make_zip.py
```

跑完把 `dist/cc_dashboard-*.zip` 发出去，或者 `git push` —— 对方解压/装完重启就能用。
