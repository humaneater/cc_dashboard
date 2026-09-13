/**
 * cc_dashboard —— ComfyUI 总控台浮动面板 (v6)
 *
 * 只在带有 properties.cc_dock_role 标记的工作流里出现（例如 00_总控台.json）。
 * 面板是固定定位的 DOM，不随画布平移缩放；节点通过 role/key 定位，不依赖 id。
 *  v6 新增：
 *   · LoRA：修掉「选了却不生效」的写入缺陷，每行显示 未启用 / 模型族不匹配 / 触发词
 *     v6.6：LoRA 行不再抓住「建 DOM 时那个节点」，每次写入按键重查 + 读回校验，
 *     重开工作流（节点被换成新对象、行数不变）后也不会再出现「一开开关 LoRA 就没了」
 *   · 种子：🎲 随机开关（默认开）写 control_after_generate，关掉才按种子细调
 *   · 提示词：正向 8 段拼接（YogurtStringConcat），每段可「手填 / 插件输入」二选一，⌖ 跳去连线；
 *     负向就是一个整框，不分段、不带插件开关
 *   · 面板随顶栏管线过滤：图像那套（提示词 / 参数 / LoRA / 模块）与视频那套自动切换
 *   v6.7：标题栏下加一排「队列」——数量（▲翻倍/▼减半）+ ▶运行 + ⇥插队 + ✕停止 +
 *     活动任务数（点击开任务历史），和 ComfyUI 顶栏那排等价，不用来回找
 *     v6.8：修独立窗口（PiP）里「改了没效果」——focused() 以前只看主文档的
 *     activeElement，PiP 里永远是 false，1.2s 一轮的同步就把正在输入的文字
 *     盖回画布旧值（change 也就不再触发）；顺带在收回 / 关窗时提交没失焦的编辑
 *  v5：浮动窗 + 独立窗口（Document PiP）+ 跟随执行
 * 任何异常只 console.warn，不影响出图。
 *
 * 插件形态（v1.0）：本文件随 cc_dashboard 插件一起分发；「说明」页可一键
 * 生成 / 更新蓝图（POST /cc_dashboard/blueprint），缺插件时顶部黄条提示。
 */
import { app } from "../../scripts/app.js";

const ROOT_ID = "cc-dock-root";
const LS_KEY = "cc_dock_ui_v1";
const CC_DASHBOARD_VERSION = "1.3.0";   // 与 __init__.py / pyproject.toml 保持一致
// 与 blueprint/generator.py 的 BLUEPRINT_REV 一致：蓝图结构一改就两边一起 +1，
// 面板靠它 + 高清链结构两道判断认出「画布上跑的还是旧蓝图」
const BLUEPRINT_REV = 3;
const UPSCALE_CHAIN_NODES = ["CR Upscale Image", "KSampler", "VAEEncode",
  "VAEDecode", "UltimateSDUpscaleNoUpscale", "ColorMatch"];
const API_BASE = "/cc_dashboard";
const GEOM_MIN_W = 420;   // 浮动窗最小宽
const GEOM_MIN_H = 200;   // 浮动窗最小高
const GEOM_EDGE = 96;     // 至少留这么多像素在视口内，防止拖飞找不回来

const PIPES = [
  ["t2i", "文生图"],
  ["i2i", "图生图精修"],
  ["i2v", "图生视频"],
  ["flf2v", "首尾帧"],
  ["t2v", "文生视频"],
];
const MODULES = [
  ["pose", "姿势"],
  ["detailer", "脸手眼矫正"],
  ["upscale", "高清化"],
];
const PROMPTS = [
  ["image_pos", "图像 · 正向", "masterpiece, best quality, ...", "image", true],
  ["image_neg", "图像 · 负向", "lowres, bad anatomy, ...", "image", false],
  ["video_pos", "视频 · 正向", "The camera slowly pushes in, ...", "video", true],
  ["video_neg", "视频 · 负向", "色调艳丽，过曝，静态，...（中文负面）", "video", false],
];
// 提示词分段：YogurtStringConcat 每节点 8 段，每段由 CR Text Input Switch JK 决定
// "手填" 还是 "插件输入"（开关的 text_true 就是插件落点），text<i> 只是镜像显示
const SEG_MAX = 8;          // 每组上限（节点决定的硬上限）
const SEG_SHOWN_MIN = 3;    // 一开始露几行
// 管线属于哪一套：图像（提示词 / 参数 / LoRA / 模块）还是视频
const PIPE_KIND = {
  t2i: "image", i2i: "image",
  i2v: "video", flf2v: "video", t2v: "video",
};
// 每条管线显示哪些模块按钮
const PIPE_MODULES = {
  t2i: ["pose", "detailer", "upscale"],
  i2i: ["detailer", "upscale"],
  i2v: [], flf2v: [], t2v: [],
};

// ---------------------------------------------- 分辨率下拉（v6.5）
// 市面主流分辨率：SDXL 官方训练桶 + 常见 16:9 / 9:16 + SD1.5 那套。
// w/h 一律 8 的倍数（SDXL / ANIMA 要求），视频那份 16 的倍数（Wan 要求）。
const RES_PRESETS = {
  image: [
    { w: 512, h: 512, tag: "1:1 · SD1.5 训练分辨率" },
    { w: 512, h: 768, tag: "2:3 · SD1.5 竖图" },
    { w: 768, h: 512, tag: "3:2 · SD1.5 横图" },
    { w: 640, h: 640, tag: "1:1 · 小图 / 快速草稿" },
    { w: 768, h: 768, tag: "1:1 · SD1.5 高清" },
    { w: 1024, h: 1024, tag: "1:1 · SDXL / ANIMA 训练分辨率" },
    { w: 1152, h: 896, tag: "9:7 · SDXL 官方桶" },
    { w: 896, h: 1152, tag: "7:9 · SDXL 官方桶（竖）" },
    { w: 1216, h: 832, tag: "16:11 · SDXL 官方桶" },
    { w: 832, h: 1216, tag: "11:16 · SDXL 官方桶（竖）" },
    { w: 1344, h: 768, tag: "7:4 · SDXL 官方桶，最接近 16:9" },
    { w: 768, h: 1344, tag: "4:7 · 竖版" },
    { w: 1536, h: 640, tag: "12:5 · SDXL 官方桶（宽银幕）" },
    { w: 640, h: 1536, tag: "5:12 · 竖版宽银幕" },
    { w: 1280, h: 720, tag: "16:9 · 主流 720p（偏大，吃显存）" },
    { w: 720, h: 1280, tag: "9:16 · 主流竖屏 720p" },
    { w: 1536, h: 864, tag: "16:9 · 2K 级（SDXL 容易过冲，慎用）" },
    { w: 864, h: 1536, tag: "9:16 · 2K 级竖屏" },
  ],
  video: [
    { w: 640, h: 640, tag: "1:1 · Wan2.2 常用，显存友好" },
    { w: 832, h: 480, tag: "16:9 · Wan2.2 480p" },
    { w: 480, h: 832, tag: "9:16 · 竖屏 480p" },
    { w: 960, h: 544, tag: "16:9 · 540p" },
    { w: 544, h: 960, tag: "9:16 · 竖版 540p" },
    { w: 1024, h: 576, tag: "16:9 · 576p" },
    { w: 576, h: 1024, tag: "9:16 · 竖版 576p" },
    { w: 1280, h: 720, tag: "16:9 · 720p（很吃显存）" },
    { w: 720, h: 1280, tag: "9:16 · 竖屏 720p" },
  ],
};
// 模型推荐分辨率 = 这个模型「训练时用的分辨率」。元数据读不出来（ckpt 里没写），
// 所以按模型族/名字判断：认不出来就按 SDXL 级 1024²。
const MODEL_RES = [
  { re: /anima/i, w: 1024, h: 1024, why: "ANIMA 训练分辨率" },
  { re: /illustrious|sd_?xl|sdxl|noob|pony/i, w: 1024, h: 1024,
    why: "SDXL / Illustrious / Noob / Pony 训练分辨率" },
  { re: /flux/i, w: 1024, h: 1024, why: "Flux 官方分辨率" },
  { re: /(sd_?1[._-]?5|sd15|v1[._-]5)/i, w: 512, h: 512,
    why: "SD1.5 训练分辨率" },
];
const MODEL_RES_FALLBACK = { w: 1024, h: 1024, why: "SDXL 级默认（认不出模型族时）" };
const VIDEO_RES_FALLBACK = { w: 640, h: 640,
  why: "Wan2.2 起手常用（显存友好；要好画质就选 832×480）" };

function recommendedRes(name) {
  const n = String(name || "");
  for (const r of MODEL_RES) {
    if (r.re.test(n)) return r;
  }
  return MODEL_RES_FALLBACK;
}

// 采样器 / 调度器下拉（值直接从 KSampler 的节点定义里取，取不到用这份兜底）
const SAMPLER_FALLBACK = ["euler", "euler_ancestral", "dpmpp_2m", "dpmpp_2m_sde",
  "dpmpp_2m_cfg_pp", "dpmpp_2m_sde_heun", "dpmpp_2s_ancestral", "dpmpp_3m_sde",
  "dpmpp_sde", "heun", "heunpp2", "dpm_2", "dpm_2_ancestral", "lms", "ipndm",
  "uni_pc", "ddim", "lcm", "res_multistep", "er_sde"];
const SCHEDULER_FALLBACK = ["normal", "karras", "exponential", "sgm_uniform",
  "simple", "ddim_uniform", "beta", "linear_quadratic", "kl_optimal"];
// 图像 / 视频各一套采样器：改哪个只影响对应那几条管线
const SAMPLER_PIPES = {
  image: ["t2i", "i2i"],
  video: ["i2v", "flf2v", "t2v"],
};
const SAMPLER_DEFAULTS = {
  "__sampler_image": "dpmpp_2m", "__scheduler_image": "karras",
  "__sampler_video": "euler", "__scheduler_video": "simple",
};

// 参数按模块分区：每块对应画布上的一个模块，模块开着才显示那块。
// module = 需要哪个模块在跑（null 表示与模块无关）；字段可带 opts.pipes 限定管线。
// 每项：[key, 标签, 步进, 鼠标悬停说明, 附加规则]
const IMG_PARAM_SECTIONS = [
  { id: "gen", title: "生成参数", params: [
    ["__resolution_image", "分辨率", 0,
      "出图分辨率预设（下拉）。★ 那项是「当前模型推荐」= 这个模型训练时用的分辨率："
      + "SDXL / Illustrious / ANIMA 都是 1024×1024，SD1.5 是 512×512。"
      + "下面还收了一批市面主流比例（SDXL 官方训练桶 1152×896 / 1216×832 / 1344×768 / "
      + "1536×640，以及 16:9、9:16、竖屏等）。选了会同时写宽和高；"
      + "想自己填数字就选「自定义」再改下面的宽 / 高；⇄ 一键横竖互换。",
      { combo: "resolution", media: "image" }],
    ["width", "宽", 1,
      "出图宽度（像素，8 的倍数）。SDXL 系 1024×1024 最稳，1216×832 是 16:11 横图；"
      + "越大越吃显存"],
    ["height", "高", 1,
      "出图高度（像素，8 的倍数）。想要竖图点右边的 ⇄ 直接把长宽对调"],
    ["steps", "步数", 1,
      "采样步数。SDXL 28 / ANIMA 30 是各自甜点；再往上收益很小，只是变慢"],
    ["cfg", "CFG", 0.1,
      "提示词跟随强度。SDXL 5.5 / ANIMA 4.5；太高容易过曝、崩结构，太低不听话"],
    ["__sampler_image", "采样器", 0,
      "采样算法（KSampler 的 sampler_name）。dpmpp_2m 稳、dpmpp_2m_sde 更细、"
      + "euler_ancestral 更活泼、lcm 配 lcm 模型用。改完立刻写进文生图 / 图生图两个子图，"
      + "高清化和脸手眼那两步有自己的一套，不受这里影响。",
      { combo: "sampler", media: "image" }],
    ["__scheduler_image", "调度器", 0,
      "噪声调度（KSampler 的 scheduler）。karras 是通用甜点；"
      + "sgm_uniform 平滑、exponential 偏锐、simple 最朴素。",
      { combo: "scheduler", media: "image" }],
    ["seed", "种子", 1,
      "随机种子。上面「🎲 随机」勾着时每张都换新种子，关掉才按这个数字反复微调"],
    ["denoise", "重绘强度", 0.05,
      "图生图重绘幅度：0.3 只微调、0.5 半重绘、0.7 以上基本重新画。改脸/改手用 0.4~0.55",
      { pipes: ["i2i"] }],
  ] },
  { id: "pose", title: "姿势参数", module: "pose", params: [
    ["pose_strength", "姿势强度", 0.05,
      "ControlNet 姿势引导强度 0~1：0.6 松（构图自由）、0.8 稳、1.0 死锁（容易僵硬或糊）"],
  ] },
  { id: "detailer", title: "脸手眼矫正参数", module: "detailer", params: [
    // --- 三级独立开关（v6.5）：关掉的那一级走旁路，图直接穿过去
    ["__sw_face", "🧑 脸", 0,
      "脸那级（子图里的 FaceDetailer 11）。关掉 = 图直接穿过去，不检测、不重绘。"
      + "脸的检测器最准，一般留着；画面里出现「贴上去的一张脸」时先关它对比。",
      { chk: "face" }],
    ["__sw_hand", "✋ 手", 0,
      "手那级（FaceDetailer 12）。手用的 hand_yolov8s 在肢体交叠 / 背景杂物上容易误检，"
      + "误检一小块再按 0.25 重画就会长出多余的手指 —— 出这种怪图先关它。",
      { chk: "hand" }],
    ["__sw_eye", "👁 眼", 0,
      "眼那级（FaceDetailer 13）。眼睛最容易在头发 / 花纹上冒出假眼，"
      + "画面上出现「一片小眼睛」就是这一级干的，直接关掉。",
      { chk: "eye" }],
    ["__sw_sam", "⬟ SAM 轮廓遮罩", 0,
      "用 SAM 把检测框细化成贴合人物轮廓的遮罩（默认开，读 models/sams/"
      + "sam_vit_b_01ec64.pth，只在这三级里用得上）。"
      + "关掉 = 回到 Impact 默认的「检测框矩形 + 羽化」遮罩：快一点，边界糙一点。",
      { chk: "sam" }],
    // --- 三级共用的大小 / 强度
    ["detailer_guide", "检测框放大尺寸", 16,
      "三级共用。检测框送去采样前要放大到的尺寸（按短边算）。"
      + "Impact 的算法是「放大倍数 = 这个值 ÷ 检测框短边」：填 1024 时一张 400px 的脸"
      + "会被放大 2.5 倍再采样，模型就在裁剪区里画出一张完整的脸 + 头发 + 肩膀，"
      + "缩回去贴到原处 —— 看起来就是「脸被贴上去」。512（Impact 自己的默认）最稳。"],
    ["detailer_max_size", "放大上限", 64,
      "三级共用。放大后的长边上限，防止极端比例的检测框把这一块撑爆显存。"
      + "默认 1024；只有很窄很长的检测框会碰到它，碰不到就不用管。"],
    ["detailer_crop", "裁剪倍率", 0.1,
      "三级共用。裁剪范围 = 检测框 × 这个倍数，决定这一级能看到多少上下文。"
      + "默认 2.5；调大到 3.5 = 半个头都重画一遍（容易改背景、改头发），"
      + "调小到 2.0 = 太紧，模型没有周围信息容易糊边。"],
    ["detailer_threshold", "检测阈值", 0.05,
      "脸 / 手 两级的检测置信度阈值。调低=更容易认出来（也会误检），调高=更严格。"
      + "默认 0.55；漏检手就降到 0.45 左右"],
    ["detailer_threshold_eye", "眼检测阈值", 0.05,
      "眼那级自己的阈值。眼睛最容易在头发 / 花纹上误检，一误检就是一片假眼，"
      + "默认比脸严格（0.70）。漏修真眼就降到 0.55；假眼多就加到 0.85"],
    ["detailer_feather", "羽化", 1,
      "遮罩边缘柔化像素（三级共用）。0 = 硬边，容易出现方块拼接痕；"
      + "默认 24，块痕还在就加到 32~40；挂上 SAM 以后遮罩跟轮廓走，羽化可以小一点"],
    ["detailer_denoise_face", "脸重绘", 0.05,
      "脸部修复力度。默认 0.25（只修不重画）；太高会改变长相（角色跑偏），"
      + "0.35 以上就开始「重画一张脸」了"],
    ["detailer_denoise_hand", "手重绘", 0.05,
      "手部修复力度。默认 0.25；手指崩得厉害再往上加，0.50 以上很容易多指 / 畸形"],
    ["detailer_denoise_eye", "眼重绘", 0.05,
      "眼部修复力度。眼睛小，默认 0.20；太高会糊成一块"],
  ] },
  { id: "upscale", title: "高清参数", module: "upscale", params: [
    ["upscale_factor", "高清倍数", 0.25,
      "最终尺寸 ÷ 原图尺寸：填 2 就是 1216×832 → 2432×1664，1.5 就是 1824×1248。"
      + "链子里只有一次放大（「先放大」那步按这个倍数走），所以「填几就是几倍」。"
      + "整个高清链的性能大头；以前填 2 出来是 4 倍（多绕了一圈 4x），v6.4 起就是 2 倍"],
    ["upscale_tile", "分块大小", 32,
      "分块精修的块大小（像素）。勾「自动」= 按精修分辨率（原图 × 倍数）的长边切 2 块，"
      + "对齐 64 并限制在 1024~1536：1216×832、倍数 2 → 精修 2432×1664 → 分块 1216。"
      + "块越少越整体，但单块更吃显存；块感重就把自动取消、手动往上加"],
    ["__ro_size", "输出尺寸", 0,
      "高清化后的实际像素 = 原图 × 倍数。和「高清倍数」联动，随时能看到最终多大"],
    ["__ro_tile", "实际分块", 0,
      "这一步真正使用的分块大小（自动算出来的或你手填的）"],
    ["upscale_whole_denoise", "整体细化强度", 0.01,
      "整张图一次过采样时的加细节力度。这是「像很多张拼起来」的第一嫌疑人："
      + "默认 0.12（只加细节），出拼图感就往 0.08~0.10 降；0.20 以上会改内容"],
    ["upscale_denoise", "分块精修强度", 0.01,
      "分块重绘的加细节力度。默认 0.12；块感明显就降到 0.08~0.10，"
      + "0.20 以上每块会各自改内容、块与块越长越不像"],
    ["upscale_seam_fix", "接缝修复强度", 0.05,
      "块与块之间那条缝再糊一遍的力度（Half Tile + Intersections 模式）。"
      + "默认 0.30；缝还在就加到 0.35~0.40，太高会把缝附近画糊"],
  ] },
];
const VID_PARAMS = [
  ["__resolution_video", "分辨率", 0,
    "视频分辨率预设（下拉）。★ 那项是 Wan2.2 起手最常用的一档；"
    + "832×480 是官方 480p 推荐、1280×720 是 720p 但很吃显存。"
    + "选了会同时写宽和高，⇄ 一键横竖互换（宽高都要 16 的倍数）。",
    { combo: "resolution", media: "video" }],
  ["video_width", "宽", 16, "视频宽度（像素，16 的倍数）。Wan 2.2 建议 832×480 或 640×640"],
  ["video_height", "高", 16, "视频高度（像素，16 的倍数）"],
  ["video_length", "帧数", 4,
    "总帧数。Wan 2.2 用 4n+1（81 = 约 5 秒 @16fps）；越长越吃显存"],
  ["video_fps", "帧率", 1, "播放帧率。16 是 Wan 的常用值，调高只是播得快、不会多出细节"],
  ["video_steps", "步数", 1, "视频采样步数。挂了 lightx2v 4 步加速 LoRA 就保持 4"],
  ["video_cfg", "CFG", 0.1, "视频 CFG。4 步加速配方用 1.0，调高容易过曝"],
  ["__sampler_video", "采样器", 0,
    "视频采样算法（KSamplerAdvanced 的 sampler_name），一次改 I2V / 首尾帧 / 文生视频三条。"
    + "4 步加速 LoRA 配方用 euler 最稳；不挂加速 LoRA 再考虑 dpmpp_2m 之类。",
    { combo: "sampler", media: "video" }],
  ["__scheduler_video", "调度器", 0,
    "视频噪声调度。4 步加速配方配 simple；步数拉高（20 步以上）时可换 karras 试试。",
    { combo: "scheduler", media: "video" }],
  ["video_seed", "种子", 1, "视频种子，跟图像那套一样由「🎲 随机」开关控制"],
];
const VID_PARAM_SECTIONS = [{ id: "video", title: "视频参数", params: VID_PARAMS }];
// 参数页里这几个旋钮一旦超出「安全区」，怪图基本都是它们造成的：
// 值 ≥ 阈值时在那一行下面挂一句醒目提示（键 = 参数 key，值 = [阈值, 提示]）。
const PARAM_WARN = {
  detailer_denoise_face: [0.35,
    "≥0.35 就不是「修」而是「重画一张脸」了：角色容易跑偏、脸像被贴上去"],
  detailer_denoise_hand: [0.35,
    "≥0.35 手那级会重画内容：肢体交叠处容易凭空长出多余的手指 / 手臂"],
  detailer_denoise_eye: [0.30,
    "≥0.30 眼那级会重画内容：头发、花纹上容易冒出一片假眼"],
  detailer_guide: [768,
    "≥768 检测框被放大太多：模型会在裁剪区里画「整张脸 + 头发 + 肩膀」，"
    + "缩回去贴回原处 —— 看起来就是脸被贴上去。512 最稳"],
  detailer_crop: [3.2,
    "≥3.2 裁剪范围太大：会连带改掉背景和头发，建议 2.5 上下"],
};
const LORA_GROUPS = [
  ["image", "图像 LoRA（文生图 + 图生图共用）"],
  ["video_high", "视频 LoRA · high（I2V / FLF2V）"],
  ["video_low", "视频 LoRA · low（I2V / FLF2V）"],
];
const WIDGET_OF = {
  model_slot: "ckpt_name",
  prompt: "value",
  param: "value",
  family: "Input",
  source_image: "image",
  pose_image: "image",
};
// 模型族预设
const PRESET = {
  sdxl: { steps: 28, cfg: 5.5, clipLayer: 0 },
  anima: { steps: 30, cfg: 4.5, clipLayer: 4 },
};

// 「重置默认值」写回画布的数字；步数 / CFG 不在这里，按当前模型族取 PRESET
const PARAM_DEFAULTS = {
  width: 1216, height: 832, seed: 123456789, denoise: 0.5,
  pose_strength: 0.8, upscale_factor: 2.0, upscale_tile: 1216,
  upscale_whole_denoise: 0.12, upscale_denoise: 0.12, upscale_seam_fix: 0.30,
  detailer_threshold: 0.55, detailer_threshold_eye: 0.70,
  detailer_feather: 24,
  detailer_denoise_face: 0.25, detailer_denoise_hand: 0.25,
  detailer_denoise_eye: 0.20,
  detailer_guide: 512, detailer_max_size: 1024, detailer_crop: 2.5,
  video_width: 640, video_height: 640, video_length: 81, video_fps: 16,
  video_steps: 4, video_cfg: 1.0, video_seed: 246813579,
};

// 高清分块：跟着分辨率自动算（会话内开关，默认开；取消就用手填的「分块大小」）
const TILE_AUTO = { on: true };
const TILE_MIN = 1024, TILE_MAX = 1536, TILE_STEP = 64;

/** 分块 = 精修分辨率（原图 × 倍数）的长边切 2 块，对齐 64，限制 1024~1536 */
function autoTileSize(w, h, f) {
  const longSide = Math.max((w || 0) * (f || 0), (h || 0) * (f || 0));
  if (!(longSide > 0)) return TILE_MIN;
  const t = Math.round((longSide / 2) / TILE_STEP) * TILE_STEP;
  return Math.max(TILE_MIN, Math.min(TILE_MAX, t));
}

const LS_DEFAULT = {
  folded: false, tab: "prompt", modules: {},
  pipe: "t2i",      // 当前管线（面板按它过滤提示词 / 参数 / LoRA / 模块）
  docked: false,   // true = 钉回窗口顶部（旧版通栏行为）
  pip: false,      // 上次是否停在独立窗口里
  focus: true,     // 跟随执行：默认开
  geom: null,      // 浮动窗 {x,y,w,h}
  batch: 1,        // 队列那一排的「数量」（跨刷新记住）
};

/**
 * 面板认领的 role:key 清单（与 blueprint/generator.py 写进节点的 properties.cc_dock_*
 * 一一对应，tools/check_dashboard.py、tools/t_plugin.py 会拿这份清单做一致性校验）。
 * null 表示该角色不带 key。
 */
const HANDLED = {
  model_slot: [null],
  preset_sdxl: [null],
  pose_image: [null],
  clip_encode: ["image_pos", "image_neg", "video_pos", "video_neg"],
  prompt: ["image_pos", "image_neg", "video_pos", "video_neg"],
  param: ["width", "height", "steps", "cfg", "seed", "denoise",
    "pose_strength", "upscale_factor", "upscale_denoise",
    "upscale_whole_denoise", "upscale_seam_fix", "upscale_tile",
    "detailer_threshold", "detailer_threshold_eye", "detailer_feather",
    "detailer_denoise_face",
    "detailer_denoise_hand", "detailer_denoise_eye",
    "detailer_guide", "detailer_max_size", "detailer_crop",
    "video_width", "video_height", "video_length", "video_fps",
    "video_steps", "video_cfg", "video_seed"],
  family: ["clip", "vae"],
  lora_group: ["image", "video_high", "video_low"],
  source_image: ["i2i", "i2v", "flf_start", "flf_end"],
  pipeline: ["t2i", "i2i", "i2v", "flf2v", "t2v"],
  module: ["pose_sdxl", "pose_anima", "detailer", "upscale"],
  save: ["t2i", "i2i", "i2v", "flf2v", "t2v"],
  // v6.5：子图内部的三级矫正 / SAM 开关（写的是子图定义里那几个节点的 mode）
  detailer_stage: ["face", "hand", "eye"],
  detailer_sam: ["sam"],
};

function log(...a) {
  try {
    console.warn("[cc_dock]", ...a);
  } catch (e) { /* ignore */ }
}

function loadState() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    const st = raw ? Object.assign({}, LS_DEFAULT, JSON.parse(raw)) : { ...LS_DEFAULT };
    if (!st.modules || typeof st.modules !== "object") st.modules = {};
    return st;
  } catch (e) {
    return { ...LS_DEFAULT };
  }
}

function saveState(st) {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(st));
  } catch (e) { /* ignore */ }
}

// ------------------------------------------------------------ 节点查找
function eachGraph(fn, graph) {
  const g = graph || (app.graph || (app.canvas && app.canvas.graph));
  if (!g) return;
  const seen = new Set();
  const walk = (gg, depth) => {
    if (!gg || seen.has(gg) || depth > 4) return;
    seen.add(gg);
    for (const n of gg.nodes || []) {
      fn(n);
    }
    for (const n of gg.nodes || []) {
      if (n.subgraph) walk(n.subgraph, depth + 1);
    }
  };
  walk(g, 0);
}

function role(n) {
  return (n && n.properties && n.properties.cc_dock_role) || null;
}

function keyOf(n) {
  return (n && n.properties && n.properties.cc_dock_key) || null;
}

function findNodes(r, k) {
  const out = [];
  eachGraph((n) => {
    if (role(n) !== r) return;
    if (k !== undefined && k !== null && keyOf(n) !== k) return;
    out.push(n);
  });
  return out;
}

function findNode(r, k) {
  return findNodes(r, k)[0] || null;
}

function hasMarkers() {
  let found = false;
  eachGraph((n) => {
    if (role(n)) found = true;
  });
  return found;
}

// ------------------------------------------------------------ 读写
function widgetOf(node, name) {
  if (!node || !node.widgets) return null;
  if (!name) return node.widgets[0] || null;
  return node.widgets.find((w) => w.name === name) || null;
}

function readValue(node, roleName) {
  const w = widgetOf(node, WIDGET_OF[roleName]);
  return w ? w.value : null;
}

function writeValue(node, roleName, value) {
  const w = widgetOf(node, WIDGET_OF[roleName]);
  if (!w) return false;
  w.value = value;
  try {
    if (typeof w.callback === "function") {
      w.callback(value, app.canvas, node, [0, 0], null);
    }
  } catch (e) { /* 忽略回调里的问题 */ }
  try {
    node.setDirtyCanvas(true, true);
  } catch (e) { /* ignore */ }
  return true;
}

/** 按 widget 名字读写（提示词分段 / 分隔符 / 种子控制项都用这个） */
function readWidget(node, name) {
  const w = widgetOf(node, name);
  return w ? w.value : null;
}

function writeWidget(node, name, value) {
  const w = widgetOf(node, name);
  if (!w) return false;
  w.value = value;
  try {
    if (typeof w.callback === "function") {
      w.callback(value, app.canvas, node, [0, 0], null);
    }
  } catch (e) { /* 忽略回调里的问题 */ }
  try {
    node.setDirtyCanvas(true, true);
  } catch (e) { /* ignore */ }
  markChanged();
  return true;
}

/**
 * 种子控制项（PrimitiveInt 的 control_after_generate 那一格）。
 * 它不参与 prompt 序列化，由前端在入队前后按值改种子；节点上的值 widget
 * 一旦被连线，前端也会自动跳过它，所以两边不会打架。
 */
const SEED_MODES = ["fixed", "increment", "decrement", "randomize"];
// 「🎲 随机」按会话记：刷新页面回到默认开（与计划一致，不写进 localStorage）
const SEED_RANDOM = { image: true, video: true };

function seedKindOf(key) {
  return key === "video_seed" ? "video" : "image";
}

function seedCtrlWidget(node) {
  if (!node || !node.widgets) return null;
  return node.widgets.find((w) => SEED_MODES.indexOf(w && w.value) >= 0) ||
    node.widgets.find((w) => w && w.name === "control_after_generate") || null;
}

function readSeedRandom(key) {
  const n = findNode("param", key);
  const w = seedCtrlWidget(n);
  return w ? w.value === "randomize" : true;
}

function writeSeedRandom(key, on) {
  const n = findNode("param", key);
  const w = seedCtrlWidget(n);
  if (!w) return false;
  if (w.value !== (on ? "randomize" : "fixed")) {
    w.value = on ? "randomize" : "fixed";
    try {
      if (typeof w.callback === "function") {
        w.callback(w.value, app.canvas, n, [0, 0], null);
      }
    } catch (e) { /* ignore */ }
    try {
      n.setDirtyCanvas(true, true);
    } catch (e) { /* ignore */ }
    markChanged();
  }
  return true;
}

function markChanged() {
  try {
    const g = app.graph;
    if (g && typeof g.change === "function") g.change();
    if (app.canvas && app.canvas.setDirty) app.canvas.setDirty(true, true);
  } catch (e) { /* ignore */ }
}

function setMode(node, mode) {
  if (!node || node.mode === mode) return;
  node.mode = mode;
  try {
    node.setDirtyCanvas(true, true);
  } catch (e) { /* ignore */ }
  markChanged();
}

// LoRA（rgthree Power Lora Loader）
function loraRows(node) {
  if (!node || !node.widgets) return [];
  return node.widgets.filter((w) => w.value && typeof w.value === "object" &&
    Object.prototype.hasOwnProperty.call(w.value, "lora"));
}

function readLora(node) {
  return loraRows(node).map((w) => ({ ...w.value }));
}

/** 重开工作流 / 换图时画布节点会被换成新对象：面板的行绑定要跟着重建（见 syncLoras / rebindIfGraphChanged） */
function dropLoraBinding(group) {
  if (ui.lastLoraCount) ui.lastLoraCount[group] = -1;
  if (ui.loraViews) delete ui.loraViews[group];
  if (ui.loraNode) delete ui.loraNode[group];
}

/**
 * 写一行的某个字段。
 *
 * 以前是「建 DOM 时抓住那个节点，写完算数」：工作流一重载，节点被换成新对象而
 * 行数没变时，面板读数走的是新节点、写入却还写向已经脱离画布的旧节点 ——
 * 于是选好的 LoRA 下一秒被新节点的旧值刷回去，看起来就是「一开开关 LoRA 就没了」。
 * 现在每次写入都按 role/key 重新找一次节点，写完读回核对；对不上就断掉行绑定重试一次。
 */
function writeLoraRow(group, index, patch) {
  for (let attempt = 0; attempt < 2; attempt++) {
    const node = findNode("lora_group", group);
    const w = node && loraRows(node)[index];
    if (!w) return false;
    try {
      if (Object.prototype.hasOwnProperty.call(patch, "lora")) {
        const v = patch.lora || "";
        // 走 rgthree 自己的入口，顺带刷新它的 LoRA 信息缓存；就地改，不换对象引用
        if (typeof w.setLora === "function") w.setLora(v);
        else w.value.lora = v;
      }
      if (Object.prototype.hasOwnProperty.call(patch, "on")) w.value.on = !!patch.on;
      if (Object.prototype.hasOwnProperty.call(patch, "strength")) w.value.strength = patch.strength;
    } catch (e) { log("writeLoraRow", e); }
    try {
      node.setDirtyCanvas(true, true);
    } catch (e) { /* ignore */ }
    markChanged();
    let ok = true;
    for (const k of Object.keys(patch)) {
      const cur = k === "on" ? !!w.value.on : w.value[k];
      const want = k === "on" ? !!patch.on : patch[k];
      if (String(cur) !== String(want)) ok = false;
    }
    if (ok) return true;
    dropLoraBinding(group);
    try { sync(true); } catch (e) { /* ignore */ }
  }
  return false;
}

// 下拉数据
function comboValues(def, name) {
  if (!def || !def.input) return [];
  const spec = (def.input.required && def.input.required[name]) ||
    (def.input.optional && def.input.optional[name]);
  if (!spec) return [];
  const t = spec[0];
  if (Array.isArray(t)) return t;
  if (t && Array.isArray(t.options)) return t.options;
  return [];
}

function nodeDef(type) {
  const types = window.LiteGraph && window.LiteGraph.registered_node_types;
  const entry = types && types[type];
  return (entry && (entry.nodeData || entry.nodeType)) || null;
}

function modelList() {
  const node = findNode("model_slot");
  const w = widgetOf(node, "ckpt_name");
  const fromNode = w && w.options && Array.isArray(w.options.values)
    ? w.options.values : null;
  if (fromNode && fromNode.length) return fromNode.slice();
  const fromDef = comboValues(nodeDef("CheckpointLoaderSimple"), "ckpt_name");
  return fromDef.slice();
}

let LORA_CACHE = null;

function loraList() {
  if (LORA_CACHE && LORA_CACHE.length) return LORA_CACHE;
  const local = comboValues(nodeDef("LoraLoader"), "lora_name");
  if (local.length) {
    LORA_CACHE = local.slice();
    return LORA_CACHE;
  }
  fetch("/object_info/LoraLoader").then((r) => r.json()).then((j) => {
    const v = comboValues(j && j.LoraLoader, "lora_name");
    if (v.length) {
      LORA_CACHE = v.slice();
      render();
    }
  }).catch(() => { /* 服务没响应就算了 */ });
  return LORA_CACHE || [];
}

function isAnimaModel(name) {
  return typeof name === "string" && name.toLowerCase().indexOf("anima") >= 0;
}

// ------------------------------------------------------------ 提示词分段
/** 按名字找输入槽（兼容 inputs[].link 数字与 linkIds 数组两种前端表示） */
function inputOf(node, name) {
  const ins = (node && node.inputs) || [];
  if (!ins.length) return null;
  return ins.find((x) => x && x.name === name) || null;
}

function linkIdsOf(node, name) {
  const inp = inputOf(node, name);
  if (!inp) return [];
  const out = [];
  if (Array.isArray(inp.linkIds)) {
    for (const id of inp.linkIds) out.push(id);
  }
  if (inp.link !== undefined && inp.link !== null) out.push(inp.link);
  return out.filter((v) => v !== null && v !== undefined);
}

function graphOf(node) {
  return (node && node.graph) || app.graph || (app.canvas && app.canvas.graph) || null;
}

/** 链接 id → 上游节点，兼容 graph.links 的数组 / 字典 / Map 三种形态 */
function linkOrigin(node, ids) {
  const g = graphOf(node);
  const links = g && g.links;
  if (!links) return null;
  const one = (id) => {
    if (Array.isArray(links)) {
      const l = links.find((x) => x && (x[0] === id || x.id === id));
      return l ? { origin: l[1] } : null;
    }
    const l = typeof links.get === "function" ? links.get(id) : links[id];
    if (!l) return null;
    return { origin: l.origin_id !== undefined ? l.origin_id : l.origin };
  };
  for (const id of [].concat(ids)) {
    const hit = one(id);
    if (!hit || hit.origin === undefined || hit.origin === null) continue;
    const src = g.getNodeById ? g.getNodeById(hit.origin) : null;
    if (src) return src;
  }
  return null;
}

/** 第 i 段的手填 / 插件开关节点（拼接器的 text<i> 是从它接过来的） */
function segSwitch(node, i) {
  return linkOrigin(node, linkIdsOf(node, "text" + (i + 1)));
}

/** 这一段接的插件来源（开关节点 text_true 上的上游） */
function segPlugin(node, i) {
  const sw = segSwitch(node, i);
  return sw ? linkOrigin(sw, linkIdsOf(sw, "text_true")) : null;
}

const segPluginLinked = (node, i) => {
  const sw = segSwitch(node, i);
  return !!sw && linkIdsOf(sw, "text_true").length > 0;
};

const segPluginOn = (node, i) => {
  const sw = segSwitch(node, i);
  return !!sw && readWidget(sw, "boolean_value") === true;
};

function writeSegPlugin(node, i, on) {
  const sw = segSwitch(node, i);
  return sw ? writeWidget(sw, "boolean_value", !!on) : false;
}

/** 手填文字住在开关的 text_false；拼接器那一格只是镜像 */
const segText = (node, i) => {
  const sw = segSwitch(node, i);
  const v = sw ? readWidget(sw, "text_false") : null;
  return typeof v === "string" ? v : "";
};

function writeSegText(node, i, v) {
  const sw = segSwitch(node, i);
  if (!sw) return false;
  writeWidget(sw, "text_false", v);
  writeWidget(sw, "text_true", v);   // 勾了「插件输入」还没连线时的兜底
  return true;
}

/** 把某段实际用的文本镜像到拼接器那一格（画布上看得见，改那格不生效） */
function mirrorSegText(node, i, text) {
  const w = widgetOf(node, "text" + (i + 1));
  if (!w || w.value === text) return;
  w.value = text;
  try {
    node.setDirtyCanvas(true, true);
  } catch (e) { /* ignore */ }
}

const segEnable = (node, i) => readWidget(node, "enable" + (i + 1)) !== false;
const writeSegEnable = (node, i, on) => writeWidget(node, "enable" + (i + 1), !!on);

/** 这段算不算「用到了」：接了插件 / 开着插件输入 / 手填非空 */
function segUsed(node, i) {
  return segPluginLinked(node, i) || segPluginOn(node, i) ||
    segText(node, i).trim() !== "";
}

/** 自动扩展：露出的段数 = clamp(max(3, 最后使用段 + 2), 3, 8) */
function segVisibleCount(node) {
  let last = 0;
  for (let i = 0; i < SEG_MAX; i++) {
    if (segUsed(node, i)) last = i + 1;
  }
  return Math.max(SEG_SHOWN_MIN, Math.min(SEG_MAX, last + 2));
}

// LoRA 触发词：rgthree 的本地缓存（light=1 只读已有 info，不联网、不哈希文件）
let LORA_TRIGGERS = null;      // { 文件名: [词, ...] }
let LORA_TRIGGER_TRYING = {};  // 拉过一次就别反复拉

function triggerWordsOf(name) {
  if (!LORA_TRIGGERS || !name) return [];
  return LORA_TRIGGERS[name] || [];
}

function absorbTriggerData(data) {
  if (!Array.isArray(data)) return false;
  let got = false;
  for (const item of data) {
    if (!item || !item.file) continue;
    const words = [];
    const list = Array.isArray(item.trainedWords) ? item.trainedWords : [];
    for (const w of list) {
      const s = (w && typeof w === "object") ? (w.word || w.text) : w;
      if (s && words.indexOf(String(s)) < 0) words.push(String(s));
    }
    LORA_TRIGGERS[item.file] = words;
    if (words.length) got = true;
  }
  return got;
}

function fetchLoraTriggers() {
  if (LORA_TRIGGERS) return;
  LORA_TRIGGERS = {};
  try {
    fetch("./rgthree/api/loras/info?light=1").then((r) => r.json()).then((j) => {
      if (j && j.data) absorbTriggerData(j.data);
      sync(true);
    }).catch(() => { /* rgthree 不在就算了，触发词只是提示 */ });
  } catch (e) { /* ignore */ }
}

/** 某一行确实选中的 LoRA 没有触发词缓存时，单独问一次（每个文件只试一次） */
function fetchTriggerFor(name) {
  if (!name || !LORA_TRIGGERS || LORA_TRIGGER_TRYING[name]) return;
  if (Object.prototype.hasOwnProperty.call(LORA_TRIGGERS, name)) return;
  LORA_TRIGGER_TRYING[name] = true;
  try {
    const url = "./rgthree/api/loras/info?files=" + encodeURIComponent(name);
    fetch(url).then((r) => r.json()).then((j) => {
      if (j && absorbTriggerData(j.data)) sync(true);
    }).catch(() => { /* ignore */ });
  } catch (e) { /* ignore */ }
}

// ---------------------------------------------------------------- 面板
const CSS = `
#${ROOT_ID}{position:fixed;left:0;top:0;z-index:99990;display:flex;flex-direction:column;
 font:12px/1.45 "Segoe UI","Microsoft YaHei",system-ui,sans-serif;
 color:#e8e8ee;background:rgba(22,23,28,.98);border:1px solid #3b3f4a;border-radius:8px;
 box-shadow:0 10px 30px rgba(0,0,0,.55);overflow:hidden;
 min-width:${GEOM_MIN_W}px;min-height:${GEOM_MIN_H}px}
#${ROOT_ID}.ccd-folded{height:auto!important;min-height:0}
#${ROOT_ID}.ccd-docked{left:0!important;right:0!important;top:0;width:auto!important;
 height:auto!important;border-radius:0;border-left:0;border-right:0;border-top:0;
 box-shadow:0 3px 14px rgba(0,0,0,.5);min-width:0;min-height:0}
#${ROOT_ID} *{box-sizing:border-box}
#${ROOT_ID} .ccd-bar{display:flex;align-items:center;gap:6px;padding:4px 8px;
 flex-wrap:wrap;min-height:32px;flex:0 0 auto;cursor:move;touch-action:none;
 user-select:none;-webkit-user-select:none}
#${ROOT_ID}.ccd-docked .ccd-bar{cursor:default}
#${ROOT_ID}.ccd-pip .ccd-bar{cursor:default}
#${ROOT_ID}.ccd-drag{opacity:.94;box-shadow:0 16px 40px rgba(0,0,0,.65)}
#${ROOT_ID} .ccd-brand{font-weight:600;color:#7fd3ff;padding-right:4px;
 white-space:nowrap}
#${ROOT_ID} .ccd-group{display:flex;align-items:center;gap:4px;
 padding:1px 6px;border:1px solid #3b3f4a;border-radius:6px;background:#1b1c22}
#${ROOT_ID} .ccd-group>label{color:#9aa0ad;font-size:11px;margin-right:2px}
#${ROOT_ID} button{font:inherit;color:#e8e8ee;background:#282a32;
 border:1px solid #454a57;border-radius:5px;padding:2px 8px;cursor:pointer}
#${ROOT_ID} button:hover{background:#33363f}
#${ROOT_ID} button.ccd-on{background:#2f6f8f;border-color:#58b6e0;color:#fff;
 font-weight:600}
#${ROOT_ID} button.ccd-tab.ccd-on{background:#4a4460;border-color:#8b7fd0}
#${ROOT_ID} select,#${ROOT_ID} input[type=text],#${ROOT_ID} input[type=number]{
 font:inherit;color:#e8e8ee;background:#15161b;border:1px solid #454a57;
 border-radius:4px;padding:1px 4px;max-width:100%}
#${ROOT_ID} select{max-width:280px}
#${ROOT_ID} .ccd-spacer{flex:1 1 auto}
#${ROOT_ID} .ccd-body{border-top:1px solid #33363f;flex:1 1 auto;min-height:0;
 overflow:auto;padding:6px 8px 8px}
#${ROOT_ID}.ccd-folded .ccd-body{display:none}
/* 把手贴在框内侧（根元素 overflow:hidden，放外面会被裁掉） */
#${ROOT_ID} .ccd-rs{position:absolute;z-index:6;touch-action:none}
#${ROOT_ID} .ccd-rs[data-dir=n]{top:0;left:14px;right:14px;height:5px;cursor:ns-resize}
#${ROOT_ID} .ccd-rs[data-dir=s]{bottom:0;left:14px;right:14px;height:6px;cursor:ns-resize}
#${ROOT_ID} .ccd-rs[data-dir=w]{left:0;top:14px;bottom:14px;width:6px;cursor:ew-resize}
#${ROOT_ID} .ccd-rs[data-dir=e]{right:0;top:14px;bottom:14px;width:6px;cursor:ew-resize}
#${ROOT_ID} .ccd-rs[data-dir=nw]{left:0;top:0;width:14px;height:14px;cursor:nwse-resize}
#${ROOT_ID} .ccd-rs[data-dir=ne]{right:0;top:0;width:14px;height:14px;cursor:nesw-resize}
#${ROOT_ID} .ccd-rs[data-dir=sw]{left:0;bottom:0;width:14px;height:14px;cursor:nesw-resize}
#${ROOT_ID} .ccd-rs[data-dir=se]{right:0;bottom:0;width:18px;height:18px;cursor:nwse-resize}
#${ROOT_ID} .ccd-rs[data-dir=se]::after{content:"";position:absolute;right:5px;bottom:5px;
 width:8px;height:8px;border-right:2px solid #6b7280;border-bottom:2px solid #6b7280}
#${ROOT_ID}.ccd-docked .ccd-rs,#${ROOT_ID}.ccd-pip .ccd-rs{display:none}
#${ROOT_ID} .ccd-tab-body{display:none}
#${ROOT_ID} .ccd-tab-body.ccd-on{display:block}
#${ROOT_ID} .ccd-prompts{display:grid;grid-template-columns:1fr 1fr;gap:6px}
#${ROOT_ID} .ccd-field{display:flex;flex-direction:column;gap:2px}
#${ROOT_ID} .ccd-field>span{color:#9aa0ad;font-size:11px}
#${ROOT_ID} textarea{font:11px/1.4 Consolas,monospace;color:#dfe3ea;
 background:#15161b;border:1px solid #454a57;border-radius:4px;padding:3px 5px;
 resize:vertical;min-height:56px}
#${ROOT_ID} .ccd-loras{display:grid;gap:8px;
 grid-template-columns:repeat(auto-fit,minmax(232px,1fr))}
#${ROOT_ID} .ccd-lora-col{border:1px solid #33363f;border-radius:6px;
 padding:4px 6px;background:#1a1b20}
#${ROOT_ID} .ccd-lora-col>h4{margin:0 0 4px;font-size:11px;color:#9aa0ad;
 font-weight:600}
#${ROOT_ID} .ccd-lora-rows{max-height:210px;overflow:auto}
#${ROOT_ID} .ccd-lora-row{display:grid;grid-template-columns:16px 1fr 54px;
 gap:4px;align-items:center;margin-bottom:2px}
#${ROOT_ID} .ccd-lora-row select{width:100%;max-width:none}
#${ROOT_ID} .ccd-params{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-start}
#${ROOT_ID} .ccd-par-set{display:flex;flex-direction:column;gap:6px;min-width:0}
#${ROOT_ID} .ccd-par-set>h4{margin:0;font-size:11px;color:#7d838f;font-weight:600}
#${ROOT_ID} .ccd-par-bar{display:flex;align-items:center;gap:8px;margin-bottom:6px}
#${ROOT_ID} .ccd-par-status{color:#7fd3ff;font-size:11px}
#${ROOT_ID} .ccd-params fieldset{border:1px solid #33363f;border-radius:6px;
 padding:4px 8px 6px;margin:0}
#${ROOT_ID} .ccd-params legend{color:#9aa0ad;font-size:11px;padding:0 4px}
#${ROOT_ID} .ccd-param{display:inline-flex;align-items:center;gap:3px;
 margin-right:8px}
#${ROOT_ID} .ccd-param>span{color:#9aa0ad;font-size:11px}
#${ROOT_ID} .ccd-param input{width:72px}
/* 下拉参数（分辨率 / 采样器 / 调度器）：选项文字长，给宽一点 */
#${ROOT_ID} .ccd-param select.ccd-combo{max-width:330px;min-width:150px}
#${ROOT_ID} .ccd-param-combo{margin-right:12px}
#${ROOT_ID} .ccd-param.ccd-ro-row{background:#1d2027;border:1px solid #2c3038;
 border-radius:5px;padding:1px 6px}
#${ROOT_ID} .ccd-param .ccd-ro{color:#d8cfa6;font-size:11px;
 font-variant-numeric:tabular-nums}
/* 开关类参数行（脸 / 手 / 眼 / SAM）：勾选框别被 input 的固定宽度撑开 */
#${ROOT_ID} .ccd-param.ccd-chk{gap:5px;margin-right:12px}
#${ROOT_ID} .ccd-param.ccd-chk input{width:auto;margin:0;accent-color:#7fd3ff}
/* 超安全区提示：整行折到参数名下面一行 */
#${ROOT_ID} .ccd-param.ccd-warn-row{flex-wrap:wrap;max-width:420px}
#${ROOT_ID} .ccd-param .ccd-warn-txt{flex:1 0 100%;color:#e0b341;font-size:11px;
 line-height:1.35;white-space:normal}
#${ROOT_ID} .ccd-param.ccd-hot input{border-color:#e0b341}
#${ROOT_ID} .ccd-hint{color:#7d838f;font-size:11px;margin:4px 0 0}
#${ROOT_ID} .ccd-ver{color:#5f6672;font-size:10px;padding-right:4px}
#${ROOT_ID} .ccd-missing{flex:0 0 auto;background:#4a3c14;border-bottom:1px solid #7a6420;
 color:#f0d79a;font-size:11px;padding:3px 8px;cursor:pointer}
#${ROOT_ID} .ccd-missing:hover{background:#584718}
#${ROOT_ID} .ccd-drift{flex:0 0 auto;display:flex;align-items:center;gap:8px;
 background:#4d2a1c;border-bottom:1px solid #8a4a2c;color:#ffcda8;
 font-size:11px;padding:3px 8px}
#${ROOT_ID} .ccd-drift .ccd-drift-txt{flex:1 1 auto;min-width:0;
 overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#${ROOT_ID} .ccd-drift .ccd-drift-fix{flex:0 0 auto;background:#8a4a2c;
 color:#fff2e6;border:1px solid #b06a44;border-radius:5px;
 padding:1px 8px;font-size:11px;cursor:pointer}
#${ROOT_ID} .ccd-drift .ccd-drift-fix:hover{background:#a2593a}
#${ROOT_ID} .ccd-tools{display:flex;align-items:center;gap:8px;flex-wrap:wrap;
 margin:0 0 4px}
#${ROOT_ID} .ccd-fold{width:30px;text-align:center}
#${ROOT_ID} .ccd-ctl{min-width:28px;text-align:center;padding:2px 6px;font-size:13px}
/* 队列一排：数量 / 运行 / 插队 / 停止 / 活动任务（对齐 ComfyUI 自己那排） */
#${ROOT_ID} .ccd-qbar{display:flex;align-items:center;gap:6px;flex-wrap:wrap;
 flex:0 0 auto;padding:4px 8px;background:#191b21;border-bottom:1px solid #2c3038}
#${ROOT_ID} .ccd-qbar>label{color:#9aa0ad;font-size:11px}
#${ROOT_ID} .ccd-q-num{width:58px;text-align:center;font-variant-numeric:tabular-nums}
#${ROOT_ID} .ccd-q-step{padding:0 5px;line-height:1.15;font-size:10px}
#${ROOT_ID} .ccd-q-run{background:#2f6fd0;border-color:#4f92ee;color:#fff;
 font-weight:600;padding:3px 12px}
#${ROOT_ID} .ccd-q-run:hover{background:#3b80e2}
#${ROOT_ID} .ccd-q-front{background:#26313d;border-color:#3d4c5e;color:#cfe3ff}
#${ROOT_ID} .ccd-q-stop{background:#552c2c;border-color:#7f3d3d;color:#ffdcdc}
#${ROOT_ID} .ccd-q-stop:hover{background:#683434}
#${ROOT_ID} .ccd-q-count{color:#9aa0ad;font-size:11px;padding:2px 9px;
 border:1px solid #2c3038;border-radius:11px;background:#22242b;cursor:pointer;
 white-space:nowrap;font-variant-numeric:tabular-nums}
#${ROOT_ID} .ccd-q-count:hover{background:#2a2d36}
#${ROOT_ID} .ccd-q-count.ccd-busy{color:#ffd98a;border-color:#6b5a24;background:#39301a}
#${ROOT_ID} .ccd-q-msg{color:#7fd3ff;font-size:11px}
#${ROOT_ID} .ccd-q-msg.ccd-bad{color:#ff9f9f}
/* 提示词分段 */
#${ROOT_ID} .ccd-hide{display:none!important}
#${ROOT_ID} .ccd-pg{border:1px solid #33363f;border-radius:6px;background:#1a1b20;
 padding:4px 6px;margin-bottom:6px}
#${ROOT_ID} .ccd-pg-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
 margin-bottom:4px}
#${ROOT_ID} .ccd-pg-head>h4{margin:0;font-size:11px;color:#9aa0ad;font-weight:600}
#${ROOT_ID} .ccd-pg-head .ccd-sep{display:inline-flex;align-items:center;gap:3px;
 color:#7d838f;font-size:11px}
#${ROOT_ID} .ccd-pg-head .ccd-sep input{width:46px}
#${ROOT_ID} .ccd-pg-head .ccd-limit{color:#e0b341;font-size:11px}
#${ROOT_ID} .ccd-pg-rows{max-height:330px;overflow:auto}
/* 负面提示词：整块单框，给高一点方便一次看完整条 */
#${ROOT_ID} .ccd-pg-plain{width:100%;min-height:92px;box-sizing:border-box}
#${ROOT_ID} .ccd-seg{display:grid;grid-template-columns:26px 1fr auto auto 26px 128px;
 gap:4px;align-items:center;margin-bottom:3px}
#${ROOT_ID} .ccd-seg-no{color:#7d838f;font-size:11px;text-align:right}
#${ROOT_ID} .ccd-seg textarea{min-height:34px;height:34px}
#${ROOT_ID} .ccd-seg textarea.ccd-static{opacity:.45}
#${ROOT_ID} .ccd-seg-chk{display:inline-flex;align-items:center;gap:2px;
 color:#9aa0ad;font-size:11px;white-space:nowrap}
#${ROOT_ID} .ccd-seg-go{padding:1px 5px}
#${ROOT_ID} .ccd-seg-state{color:#7d838f;font-size:11px;overflow:hidden;
 text-overflow:ellipsis;white-space:nowrap}
#${ROOT_ID} .ccd-seg.ccd-off{opacity:.5}
#${ROOT_ID} .ccd-seg.ccd-hit .ccd-seg-state{color:#7fd3ff}
/* LoRA 行状态 */
#${ROOT_ID} .ccd-lora-status{grid-column:1/-1;font-size:11px;color:#7d838f;
 margin:-1px 0 3px 20px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#${ROOT_ID} .ccd-lora-status.ccd-warn{color:#e0b341}
`;

function el(tag, props, kids) {
  const n = document.createElement(tag);
  if (props) {
    for (const k of Object.keys(props)) {
      const v = props[k];
      if (v === undefined || v === null) continue;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k === "html") n.innerHTML = v;
      else if (k === "style") n.setAttribute("style", v);
      else if (k.startsWith("on") && typeof v === "function") {
        n.addEventListener(k.slice(2).toLowerCase(), v);
      } else n.setAttribute(k, v);
    }
  }
  for (const c of [].concat(kids || [])) {
    if (c === null || c === undefined) continue;
    n.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return n;
}

function sel(values, cur, onChange, className) {
  const s = el("select", { class: className || "" });
  for (const v of values) {
    s.appendChild(el("option", { value: v, text: v === "" ? "— 无 —" : v }));
  }
  if (cur !== undefined && cur !== null && values.indexOf(cur) < 0) {
    s.appendChild(el("option", { value: cur, text: cur + "（不在列表）" }));
  }
  s.value = cur === undefined || cur === null ? "" : cur;
  s.addEventListener("change", () => onChange(s.value));
  return s;
}

function num(value, step, onInput, width) {
  const i = el("input", {
    type: "number", step: step || 1,
    value: value === undefined || value === null ? "" : value,
  });
  if (width) i.style.width = width;
  i.addEventListener("change", () => onInput(parseFloat(i.value)));
  return i;
}

/** 一行提示词分段：文本框 + 插件输入 + 启用 + ⌖ 跳转 + 状态 */
function buildSegRow(key, i, ph) {
  const ta = el("textarea", { placeholder: ph || "" });
  ta.title = "第 " + (i + 1) + " 段手填文字（勾上「插件输入」时被忽略）";
  ta.addEventListener("change", () => {
    const n = findNode("prompt", key);
    if (n) writeSegText(n, i, ta.value);
    sync(true);
  });
  const plugin = el("input", { type: "checkbox" });
  plugin.addEventListener("change", () => {
    const n = findNode("prompt", key);
    if (n) writeSegPlugin(n, i, plugin.checked);
    sync(true);
  });
  const enable = el("input", { type: "checkbox" });
  enable.checked = true;
  enable.addEventListener("change", () => {
    const n = findNode("prompt", key);
    if (n) writeSegEnable(n, i, enable.checked);
    sync(true);
  });
  const go = el("button", {
    class: "ccd-seg-go", text: "⌖",
    title: "跳到这一段的手填/插件开关节点（在那儿把插件的 STRING 输出连到「插件文本」口）",
  });
  go.addEventListener("click", () => {
    const n = findNode("prompt", key);
    const sw = n && segSwitch(n, i);
    if (sw) focusNode(sw);
    else log("第 " + (i + 1) + " 段找不到开关节点");
  });
  const state = el("span", { class: "ccd-seg-state" });
  const box = el("div", { class: "ccd-seg" }, [
    el("span", { class: "ccd-seg-no", text: "#" + (i + 1) }),
    ta,
    el("label", {
      class: "ccd-seg-chk",
      title: "这一段的文字来自插件（勾上就忽略手填；需先把插件输出连到该段的「插件文本」口）",
    }, [plugin, "插件输入"]),
    el("label", { class: "ccd-seg-chk", title: "这一段是否参与拼接" },
      [enable, "启用"]),
    go,
    state,
  ]);
  return { box, ta, plugin, enable, go, state, key, idx: i };
}

// ------------------------------------------------------------ 队列一排
/**
 * 和 ComfyUI 顶部那排等价：数量 / 运行 / 插队 / 停止 / 活动任务。
 * 只用公开接口，逐级兜底（任何一步失败就走下一步，全失败只 log，不动画布）：
 *   排队 app.queuePrompt(number, batchCount) → 命令总线 Comfy.QueuePrompt[Front] → 失败提示
 *   停止 命令总线 Comfy.Interrupt → api.interrupt() → app.interrupt() → POST /interrupt
 *   状态 GET /queue（便宜） → api.getQueue()（新前端）
 * 数量只影响这一排的「运行」；ComfyUI 原生运行按钮仍用它自己那个框。
 */
const QB_MIN = 1, QB_MAX = 100;

function apiUrlOf(path) {
  try {
    if (ui.api && typeof ui.api.apiURL === "function") return ui.api.apiURL(path);
  } catch (e) { /* ignore */ }
  return path;
}

function batchCount() {
  const raw = parseInt((ui.qNum && ui.qNum.value) || "", 10);
  const n = Math.max(QB_MIN, Math.min(QB_MAX, isNaN(raw) ? 1 : raw));
  if (ui.qNum && ui.qNum.value !== String(n)) ui.qNum.value = String(n);
  return n;
}

function setBatchCount(n, remember) {
  const v = Math.max(QB_MIN, Math.min(QB_MAX, Math.round(Number(n) || 1)));
  if (ui.qNum) ui.qNum.value = String(v);
  if (remember !== false && ui.st) {
    ui.st.batch = v;
    saveState(ui.st);
  }
  paintQueue();
  return v;
}

/** 一排上的短提示，4 秒后自己消失 */
function qFlash(text, bad) {
  try {
    if (!ui.qMsg) return;
    ui.qMsg.textContent = text || "";
    ui.qMsg.classList.toggle("ccd-bad", !!bad);
    if (ui.qMsgTimer) clearTimeout(ui.qMsgTimer);
    ui.qMsgTimer = setTimeout(() => {
      try {
        if (ui.qMsg) ui.qMsg.textContent = "";
      } catch (e) { /* ignore */ }
    }, 4000);
  } catch (e) { /* ignore */ }
}

/** 把「数量」画到运行按钮上、把活动任务数画到药丸上 */
function paintQueue() {
  try {
    if (ui.qRun) {
      const b = batchCount();
      ui.qRun.textContent = b > 1 ? ("▶ 运行 ×" + b) : "▶ 运行";
      ui.qRun.title = "按当前工作流排队运行 " + b + " 次（用面板这个数量，"
        + "ComfyUI 原生那个框不受影响）；按住 Shift 点 = 插队";
    }
    if (ui.qCount) {
      const run = ui.qRunning || 0, wait = ui.qPending || 0, total = run + wait;
      ui.qCount.textContent = total + " 个活动任务";
      ui.qCount.title = "队列里正在跑 " + run + " 个、等待 " + wait + " 个（点一下打开任务历史）";
      ui.qCount.classList.toggle("ccd-busy", total > 0);
    }
  } catch (e) { /* ignore */ }
}

/** 排一次队：front=true 排到队首（Run Front / 插队） */
function queueRun(front) {
  const n = batchCount();
  // ① 首选：app.queuePrompt(number, batchCount) —— 数量由面板决定
  try {
    if (app && typeof app.queuePrompt === "function") {
      const p = app.queuePrompt(front ? -1 : 0, n, {
        intent: { trigger_source: "cc_dashboard" },
      });
      if (p && typeof p.then === "function") {
        p.catch((e) => { log("queuePrompt", e); qFlash("排队失败：看控制台（cc_dock）", true); });
      }
      qFlash((front ? "已插队 ×" : "已排队 ×") + n);
      refreshQueue(true);
      return true;
    }
  } catch (e) { log("app.queuePrompt", e); }
  // ② 兜底：命令总线（数量用 ComfyUI 自己那个框）
  try {
    const p = commandRun(front ? "Comfy.QueuePromptFront" : "Comfy.QueuePrompt",
      { metadata: { subscribe_to_run: false, trigger_source: "cc_dashboard" } });
    if (p !== null) {
      if (p && typeof p.then === "function") {
        p.catch((e) => { log("命令排队", e); qFlash("排队失败：看控制台（cc_dock）", true); });
      }
      qFlash("已排队（数量用 ComfyUI 原生那个框）");
      refreshQueue(true);
      return true;
    }
  } catch (e) { log("命令排队", e); }
  qFlash("排队失败：看控制台（cc_dock）", true);
  return false;
}

/** 中断当前这一轮（已经在队里的还留着） */
async function queueStop() {
  // ① 官方命令：顺带把前端自己的运行态一起复位
  try {
    const p = commandRun("Comfy.Interrupt");
    if (p !== null) {
      await p;
      qFlash("已中断当前这轮");
      refreshQueue(true);
      return true;
    }
  } catch (e) { log("Comfy.Interrupt", e); }
  // ② api.interrupt()
  try {
    if (ui.api && typeof ui.api.interrupt === "function") {
      await ui.api.interrupt();
      qFlash("已中断当前这轮");
      refreshQueue(true);
      return true;
    }
  } catch (e) { log("api.interrupt", e); }
  // ③ app.interrupt()
  try {
    if (app && typeof app.interrupt === "function") {
      await app.interrupt();
      qFlash("已中断当前这轮");
      refreshQueue(true);
      return true;
    }
  } catch (e) { log("app.interrupt", e); }
  // ④ 直接打接口
  try {
    await fetch(apiUrlOf("/interrupt"), { method: "POST" });
    qFlash("已中断当前这轮");
    refreshQueue(true);
    return true;
  } catch (e) { log("/interrupt", e); }
  qFlash("中断失败：看控制台（cc_dock）", true);
  return false;
}

/** 点活动任务数 → 打开任务历史浮层（没有这个命令就算了） */
function openQueuePanel() {
  try {
    const p = commandRun("Comfy.Queue.ToggleOverlay");
    if (p !== null) {
      if (p && typeof p.then === "function") p.catch(() => { /* ignore */ });
      return true;
    }
  } catch (e) { log("任务历史", e); }
  qFlash("这个前端版本没有任务历史浮层", true);
  return false;
}

const lenOf = (v) => (Array.isArray(v) ? v.length : 0);

/**
 * 跑一条前端命令（Comfy.QueuePrompt / Comfy.Interrupt / Comfy.Queue.ToggleOverlay …）。
 * 命令总线的入口在各版本里叫法不一样（实测 1.34 是 command.execute，
 * 老一点的写法是 executeCommand），两种都认；没有就返回 null 让调用方兜底。
 */
function commandRun(id, args) {
  let cs = null;
  try {
    cs = (app && app.extensionManager && app.extensionManager.command) || null;
  } catch (e) { cs = null; }
  if (!cs) return null;
  const fn = (typeof cs.executeCommand === "function" && cs.executeCommand)
    || (typeof cs.execute === "function" && cs.execute)
    || null;
  if (!fn) return null;
  return fn.call(cs, id, args);
}

/** 刷新活动任务数：先问便宜的 /queue，再退到新前端的 api.getQueue() */
async function refreshQueue(force) {
  const now = Date.now();
  if (!force && now - (ui.qAt || 0) < 900) return;
  ui.qAt = now;
  let running = null, pending = null;
  try {
    const r = await fetch(apiUrlOf("/queue"), { cache: "no-store" });
    if (r && r.ok) {
      const d = await r.json();
      running = lenOf(d.queue_running !== undefined ? d.queue_running : d.Running);
      pending = lenOf(d.queue_pending !== undefined ? d.queue_pending : d.Pending);
    }
  } catch (e) { /* 服务没起来 / 接口不在：走下面那条 */ }
  if (running === null) {
    try {
      if (ui.api && typeof ui.api.getQueue === "function") {
        const q = await ui.api.getQueue();
        running = lenOf(q && (q.Running || q.queue_running));
        pending = lenOf(q && (q.Pending || q.queue_pending));
      }
    } catch (e) { log("getQueue", e); }
  }
  if (running === null) return;   // 两条都拿不到：保持原样，不显示假数字
  ui.qRunning = running;
  ui.qPending = pending || 0;
  paintQueue();
}

const ui = {};

function build() {
  if (document.getElementById(ROOT_ID)) return;
  if (!document.head.querySelector("style[data-cc-dock]")) {
    document.head.appendChild(el("style", { "data-cc-dock": "1", text: CSS }));
  }
  const st = loadState();

  // ---- 顶栏
  const pipeBtns = {};
  const pipes = el("div", { class: "ccd-group" });
  for (const [k, label] of PIPES) {
    const b = el("button", {
      class: "ccd-pipe", text: label,
      title: "切到该管线（其余 Save 节点静音）",
      onclick: () => pickPipeline(k),
    });
    pipeBtns[k] = b;
    pipes.appendChild(b);
  }
  const modelSel = el("select", { title: "模型槽：Illustrious / ANIMA / 任意 ckpt" });
  modelSel.addEventListener("change", () => onModelChange(modelSel.value));

  const modBtns = {};
  const mods = el("div", { class: "ccd-group" });
  mods.appendChild(el("label", { text: "模块" }));
  for (const [k, label] of MODULES) {
    const b = el("button", {
      class: "ccd-mod", text: label,
      title: "开关该模块（内部子图旁路，不断链）",
      onclick: () => toggleModule(k, !b.classList.contains("ccd-on")),
    });
    modBtns[k] = b;
    mods.appendChild(b);
  }

  const tabBtns = {};
  const tabs = el("div", { class: "ccd-group" });
  for (const [k, label] of [["prompt", "提示词"], ["lora", "LoRA"],
    ["param", "参数"], ["help", "说明"]]) {
    const b = el("button", {
      class: "ccd-tab", text: label,
      onclick: () => setTab(k),
    });
    tabBtns[k] = b;
    tabs.appendChild(b);
  }
  const foldBtn = el("button", {
    class: "ccd-fold", text: "▾", title: "折叠 / 展开",
    onclick: () => setFolded(!ui.root.classList.contains("ccd-folded")),
  });

  // 窗口控制：跟随执行 / 独立窗口 / 钉回顶部
  const focusBtn = el("button", {
    class: "ccd-ctl", text: "◎", title: "跟随执行：运行时自动聚焦正在执行的节点（默认开）",
    onclick: () => toggleFocus(),
  });
  const pipBtn = el("button", {
    class: "ccd-ctl", text: "⧉",
    title: pipAvailable()
      ? "弹出为独立窗口（可拖到别的屏幕，随时收回）"
      : "当前浏览器不支持独立窗口，请用 Chrome / Edge 打开",
    onclick: () => togglePiP(),
  });
  if (!pipAvailable()) pipBtn.style.opacity = ".45";
  const dockBtn = el("button", {
    class: "ccd-ctl", text: "📌", title: "钉回窗口顶部通栏 / 恢复浮动窗",
    onclick: () => toggleDocked(),
  });

  const bar = el("div", { class: "ccd-bar" }, [
    el("span", { class: "ccd-brand", text: "🎛 总控台" }),
    el("span", {
      class: "ccd-ver", text: "v" + CC_DASHBOARD_VERSION,
      title: "cc_dashboard 插件版本（蓝图 + 面板）",
    }),
    pipes,
    el("div", { class: "ccd-group" }, [el("label", { text: "模型" }), modelSel]),
    mods,
    el("button", {
      text: "⟳ 取图",
      title: "刷新 output/ 里的图片下拉（LoadImageOutput），"
        + "把最新那张填进当前栏的取图节点、并传给下游取图节点；"
        + "别的栏你自己选的图不会被冲掉",
      onclick: () => refreshImageCombos({ own: true }),
    }),
    el("button", {
      text: "↻ 同步",
      title: "把最后产出的图传给下游取图节点："
        + "文生图 → 图生图 / 图生视频 / 首尾帧；图生图 → 图生视频 / 首尾帧。"
        + "刚跑完的图立刻生效（用 Save 报回来的文件名），不用等下拉刷新",
      onclick: () => { refreshImageCombos(); syncOutputImageSoon(); sync(true); },
    }),
    el("span", { class: "ccd-spacer" }),
    tabs,
    el("div", { class: "ccd-group" }, [focusBtn, pipBtn, dockBtn]),
    foldBtn,
  ]);

  // ---- 队列一排：数量 / 运行 / 插队 / 停止 / 活动任务（对齐全局那排，省得来回找）
  const qNum = el("input", {
    type: "text", inputmode: "numeric", class: "ccd-q-num",
    value: String(Math.max(QB_MIN, Math.min(QB_MAX, parseInt(st.batch, 10) || 1))),
    title: "一次排队跑几张（" + QB_MIN + "~" + QB_MAX + "）：▲ 翻倍 / ▼ 减半，"
      + "也可直接输数字。只影响面板上的「运行」，ComfyUI 原生那个框不受影响",
  });
  qNum.addEventListener("input", () => {
    qNum.value = String(qNum.value).replace(/[^0-9]/g, "");
  });
  qNum.addEventListener("change", () => setBatchCount(parseInt(qNum.value, 10) || 1));
  qNum.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { try { qNum.blur(); } catch (err) { /* ignore */ } }
  });
  const qUp = el("button", {
    class: "ccd-q-step", text: "▲", title: "翻倍（和 ComfyUI 那个框一样）",
    onclick: () => setBatchCount(batchCount() * 2),
  });
  const qDown = el("button", {
    class: "ccd-q-step", text: "▼", title: "减半（最少 " + QB_MIN + "）",
    onclick: () => setBatchCount(Math.floor(batchCount() / 2)),
  });
  const qRun = el("button", { class: "ccd-q-run", text: "▶ 运行" });
  qRun.addEventListener("click", (e) => queueRun(!!(e && e.shiftKey)));
  const qFront = el("button", {
    class: "ccd-q-front", text: "⇥ 插队",
    title: "排到队首，先跑这一轮（等于 ComfyUI 的 Run Front / Ctrl+Shift+Enter）",
    onclick: () => queueRun(true),
  });
  const qStop = el("button", {
    class: "ccd-q-stop", text: "✕ 停止",
    title: "中断正在跑的这一轮（等于 Ctrl+Alt+Enter）；已经在队里等着的不会被清掉",
    onclick: () => queueStop(),
  });
  const qCount = el("span", {
    class: "ccd-q-count", text: "— 个活动任务",
    title: "队列里正在跑 + 等待的任务数；点一下打开任务历史",
    onclick: () => openQueuePanel(),
  });
  const qMsg = el("span", { class: "ccd-q-msg" });
  const qbar = el("div", { class: "ccd-qbar" }, [
    el("label", { text: "队列" }), qNum, qUp, qDown,
    qRun, qFront, qStop, qCount, qMsg,
  ]);

  // ---- 提示词页（正向 8 段拼接、负向一个单框；显示哪两组由顶栏管线决定）
  const promptBoxes = {};   // key -> 第 1 段文本框
  const segGroups = {};     // key -> { box, rows, sep, all, limit, kind, plain }
  const promptList = el("div", { class: "ccd-pg-list" });
  for (const [k, label, hint, kind, seg] of PROMPTS) {
    if (!seg) {
      // 负面提示词：一个整体文本框，不分段、不拼接、没有插件开关
      const ta = el("textarea", { class: "ccd-pg-plain", placeholder: hint });
      ta.title = "整条负面提示词（单框，不分段）";
      ta.addEventListener("change", () => {
        const n = findNode("prompt", k);
        if (n) writeWidget(n, "value", ta.value);
        sync(true);
      });
      const box = el("div", { class: "ccd-pg" }, [
        el("div", { class: "ccd-pg-head" }, [el("h4", { text: label })]),
        ta,
      ]);
      promptBoxes[k] = ta;
      segGroups[k] = { key: k, kind, box, plain: true, ta };
      promptList.appendChild(box);
      continue;
    }
    const rowsBox = el("div", { class: "ccd-pg-rows" });
    const rows = [];
    for (let i = 0; i < SEG_MAX; i++) {
      const row = buildSegRow(k, i, i === 0 ? hint : "");
      rows.push(row);
      rowsBox.appendChild(row.box);
      if (i === 0) promptBoxes[k] = row.ta;
    }
    const sep = el("input", {
      type: "text", value: ", ", title: "段与段之间的连接符",
    });
    sep.addEventListener("change", () => {
      const n = findNode("prompt", k);
      if (n) writeWidget(n, "separator", sep.value);
      sync(true);
    });
    const all = el("input", { type: "checkbox", title: "一次把 8 段都露出来" });
    all.addEventListener("change", () => {
      if (!ui.segAll) ui.segAll = {};
      ui.segAll[k] = all.checked;
      syncSegs(true);
    });
    const limit = el("span", { class: "ccd-limit" });
    const box = el("div", { class: "ccd-pg" }, [
      el("div", { class: "ccd-pg-head" }, [
        el("h4", { text: label }),
        el("span", { class: "ccd-sep" }, [el("span", { text: "分隔符" }), sep]),
        el("label", { class: "ccd-seg-chk" }, [all, "全部 8 段"]),
        limit,
      ]),
      rowsBox,
    ]);
    segGroups[k] = { key: k, kind, box, rows, sep, all, limit, plain: false };
    promptList.appendChild(box);
  }
  const promptTab = el("div", {}, [promptList, el("p", {
    class: "ccd-hint",
    text: "正向 8 段按顺序拼接（空段自动跳过），每段一个「手填 / 插件」开关：不勾插件用"
      + "手填文字，勾上就吃那一段节点接进来的插件（没连线时回落到手填）。"
      + "点 ⌖ 跳到那一段节点去连线；写了一段后面会自动多出一行。"
      + "负面提示词不用分段，就是一个整框，写完直接进编码。",
  })]);

  // ---- LoRA 页
  const loraCols = {};
  const loraGrid = el("div", { class: "ccd-loras" });
  for (const [k, label] of LORA_GROUPS) {
    const rows = el("div", { class: "ccd-lora-rows" });
    loraCols[k] = rows;
    loraGrid.appendChild(el("div", { class: "ccd-lora-col" },
      [el("h4", { text: label }), rows]));
  }
  const loraTab = el("div", {}, [loraGrid, el("p", {
    class: "ccd-hint",
    text: "行数跟画布节点一致：在画布上双击节点用 “➕ Add Lora” 加行，这里会自动跟上。"
      + "每行下面会提示触发词、有没有真的启用、跟当前模型族配不配——锁不住角色时先看这三条。",
  })]);

  // ---- 参数页
  const paramInputs = {};
  const paramCombos = {};
  const seedChks = {};
  const tileChks = {};
  const roFields = {};
  const stageChks = {};        // 脸 / 手 / 眼 / SAM 四个勾（v6.5）
  const warnSpans = {};        // 超安全区提示（PARAM_WARN）
  const paramSections = {};
  const buildParamField = (k, label, step, tip, opts) => {
    // 开关类字段（脸 / 手 / 眼 / SAM）：值不在参数节点上，而是写子图内部节点的 mode
    if (opts && opts.chk) {
      const box = el("input", { type: "checkbox" });
      box.checked = detailerToggleOn(opts.chk);
      if (tip) box.title = tip;
      box.addEventListener("change", () => {
        applyDetailerToggle(opts.chk, box.checked);
        sync(true);
      });
      stageChks[opts.chk] = box;
      const name = el("span", { text: label, title: tip || "" });
      return {
        box: el("span", { class: "ccd-param ccd-chk" }, [name, box]),
        pipes: (opts && opts.pipes) || null,
      };
    }
    // 只读提示行（输出尺寸 / 实际分块）：不绑定画布节点，只显示算出来的值
    if (k.indexOf("__ro_") === 0) {
      const val = el("span", { class: "ccd-ro", text: "—" });
      const name = el("span", { text: label });
      if (tip) { val.title = tip; name.title = tip; }
      roFields[k] = val;
      return {
        box: el("span", { class: "ccd-param ccd-ro-row" }, [name, val]),
        pipes: (opts && opts.pipes) || null,
      };
    }
    // 下拉参数（分辨率预设 / 采样器 / 调度器）：值不是画布上的参数节点，
    // 而是写进「宽高参数节点」或「子图里的 KSampler widget」，见 applyComboValue()
    if (opts && opts.combo) {
      const s = el("select", { class: "ccd-combo" });
      if (tip) s.title = tip;
      s.addEventListener("change", () => onComboPick(k, s.value));
      const name = el("span", { text: label });
      if (tip) name.title = tip;
      const wrap = el("span", { class: "ccd-param ccd-param-combo" }, [name, s]);
      if (opts.combo === "resolution") {
        wrap.appendChild(el("button", {
          text: "⇄", title: "交换长宽（和下面「高」右边那个按钮一样）",
          onclick: () => swapWH(opts.media === "video" ? "video" : "image"),
        }));
      }
      paramCombos[k] = {
        key: k, kind: opts.combo, media: opts.media || "image",
        sel: s, tip: tip || "", sig: "",
      };
      return { box: wrap, pipes: (opts && opts.pipes) || null };
    }
    {
      const inp = num("", step, (v) => {
        const n = findNode("param", k);
        if (n && !isNaN(v)) {
          writeValue(n, "param", v);
          storeParam(k, v);        // 记在浏览器里：刷新 / 重开工作流都还在
          applyTileAuto();
          syncParamWarns();        // 超安全区的话立刻在行下面提示
          markChanged();
        }
      });
      inp.style.width = "92px";
      if (tip) inp.title = tip;
      paramInputs[k] = inp;
      const name = el("span", { text: label });
      if (tip) name.title = tip;
      const wrap = el("span", { class: "ccd-param" }, [name, inp]);
      // 超安全区的值：在行下面挂一句提醒（脸手眼那几个旋钮最常把画面搞烂）
      if (PARAM_WARN[k]) {
        const w = el("span", { class: "ccd-warn-txt" });
        warnSpans[k] = w;
        wrap.classList.add("ccd-warn-row");
        wrap.appendChild(w);
      }
      if (k === "seed" || k === "video_seed") {
        wrap.appendChild(el("button", {
          text: "🎲", title: "只随机这一次，不改上面的开关",
          onclick: () => {
            inp.value = Math.floor(Math.random() * 1e15);
            inp.dispatchEvent(new Event("change"));
          },
        }));
        const rnd = el("input", { type: "checkbox" });
        rnd.checked = !!SEED_RANDOM[seedKindOf(k)];
        rnd.addEventListener("change", () => {
          SEED_RANDOM[seedKindOf(k)] = rnd.checked;
          writeSeedRandom(k, rnd.checked);
          sync(true);
        });
        seedChks[k] = rnd;
        wrap.appendChild(el("label", {
          class: "ccd-seg-chk",
          title: "开着每次出图都换新种子；关掉就按这个数字细调",
        }, [rnd, "随机"]));
      }
      // 长宽互换：竖图 / 横图一键对调
      if (k === "height" || k === "video_height") {
        wrap.appendChild(el("button", {
          text: "⇄",
          title: "交换长宽（1216×832 ↔ 832×1216）。想要竖图点一下就行",
          onclick: () => swapWH(k === "video_height" ? "video" : "image"),
        }));
      }
      // 分块大小：自动跟着分辨率走
      if (k === "upscale_tile") {
        const auto = el("input", { type: "checkbox" });
        auto.checked = !!TILE_AUTO.on;
        auto.addEventListener("change", () => {
          TILE_AUTO.on = !!auto.checked;
          applyTileAuto();
          sync(true);
        });
        tileChks.auto = auto;
        wrap.appendChild(el("label", {
          class: "ccd-seg-chk",
          title: "跟着分辨率自动算分块（精修尺寸的长边切 2 块）；取消就用手填的数值",
        }, [auto, "自动"]));
      }
      return { box: wrap, pipes: (opts && opts.pipes) || null };
    }
  };
  const mkParamSet = (kind, title, sections) => {
    const set = el("div", { class: "ccd-par-set" }, [el("h4", { text: title })]);
    for (const sec of sections) {
      const fields = sec.params.map(
        ([k, label, step, tip, opts]) => buildParamField(k, label, step, tip, opts));
      const box = el("fieldset", {}, [
        el("legend", { text: sec.title }),
        el("div", { class: "ccd-par-body" }, fields.map((f) => f.box)),
      ]);
      paramSections[sec.id] = {
        id: sec.id, box, fields, kind, module: sec.module || null,
        pipes: sec.pipes || null,
      };
      set.appendChild(box);
    }
    return set;
  };
  const imgParamSet = mkParamSet("image", "图像（文生图 / 图生图）",
    IMG_PARAM_SECTIONS);
  const vidParamSet = mkParamSet("video", "视频（I2V / 首尾帧 / T2V）",
    VID_PARAM_SECTIONS);
  const modHint = el("p", {
    class: "ccd-hint ccd-hide",
    text: "该管线没有图像模块：姿势 / 脸手眼矫正 / 高清化都在图像管线上，切回文生图或图生图就能看到。",
  });
  const parStatus = el("span", { class: "ccd-par-status" });
  const parBar = el("div", { class: "ccd-par-bar" }, [
    el("button", {
      class: "ccd-ctl", text: "↺ 重置默认值",
      title: "把参数页里的数字全部恢复默认：分辨率回「当前模型推荐」"
        + "（SDXL / ANIMA 1024×1024，SD1.5 512×512）；步数 / CFG 按当前模型族"
        + "（SDXL 28 / 5.5，ANIMA 30 / 4.5）；采样器 / 调度器回各自那套默认"
        + "（图像 dpmpp_2m + karras，视频 euler + simple）；重绘 0.5、姿势 0.8、"
        + "脸手眼 阈值 0.55 / 眼阈值 0.70 / 羽化 24 / 脸 0.25 / 手 0.25 / 眼 0.20 / "
        + "检测框放大 512 / 放大上限 1024 / 裁剪倍率 2.5，三级开关和 SAM 也恢复成全开；"
        + "高清 倍数 2 / 整体细化 0.12 / 分块精修 0.12 / 接缝修复 0.30；"
        + "视频 640×640 / 81 帧 / 16fps / 4 步 / CFG 1。随机种子开关也恢复为开。"
        + "不动模型槽、提示词、LoRA 和管线 / 模块开关。",
      onclick: () => {
        const anima = isAnimaModel(currentModel());
        const n = resetParams();
        flashParamStatus("已重置 " + n + " 项为默认值（"
          + (anima ? "ANIMA 30 步 / CFG 4.5" : "SDXL 28 步 / CFG 5.5") + "）");
      },
    }),
    parStatus,
  ]);
  const paramTab = el("div", {}, [
    parBar,
    el("div", { class: "ccd-params" }, [imgParamSet, vidParamSet, modHint]),
  ]);

  // ---- 说明页
  const toolStatus = el("span", { class: "ccd-par-status ccd-tool-status" });
  const toolRow = el("div", { class: "ccd-tools" }, [
    el("button", {
      class: "ccd-ctl", text: "🏗 生成 / 更新蓝图",
      title: "把画布上现在用的模型 / 提示词 / LoRA / 参数结转过去，"
        + "重新生成一份 00_总控台.json（写之前自动备份旧版，备份放在 "
        + "user/default/cc_dashboard_backups/）。生成完会自动载入新的那份。",
      onclick: () => makeBlueprint("update"),
    }),
    el("button", {
      class: "ccd-ctl", text: "🧱 以默认值重建",
      title: "忽略画布上的改动，按插件默认值重建 00_总控台.json"
        + "（同样先备份旧版）。想彻底重来、或者接手别人的画布时用这个。",
      onclick: () => makeBlueprint("fresh"),
    }),
    toolStatus,
  ]);
  const helpTab = el("div", {}, [
    toolRow,
    el("p", { class: "ccd-hint", text:
      "· 蓝图（00_总控台.json）就是这个插件生成的：要改结构跑生成器，"
      + "要改数值用上面的面板。生成器命令行是 python tools/gen_dashboard.py。" }),
    el("p", { class: "ccd-hint", text:
      "· 面板是浮动窗：拖标题栏移动，拖边/角改大小，位置尺寸自动记住；⧉ 弹出独立窗口（可拉到别的屏幕），📌 钉回顶部通栏。" }),
    el("p", { class: "ccd-hint", text:
      "· ◎ 跟随执行（默认开）：跑图时自动切进正在执行的子图并聚焦该节点；你自己拖动画布后 1 秒内不抢镜头，不需要就点掉。" }),
    el("p", { class: "ccd-hint", text:
      "· 队列一排（标题栏下面那条）：数量（▲ 翻倍 / ▼ 减半，也可直接输数字）、▶ 运行、"
      + "⇥ 插队（排到队首，等于 Ctrl+Shift+Enter）、✕ 停止（中断当前这轮，等于 Ctrl+Alt+Enter）；"
      + "右边药丸是「正在跑 + 等待」的任务数，点一下打开任务历史。按住 Shift 点「运行」也等于插队。" }),
    el("p", { class: "ccd-hint", text:
      "· 数量只影响面板上的「运行」；ComfyUI 顶上那个原生运行按钮仍然用它自己那个框，两边互不干扰。" }),
    el("p", { class: "ccd-hint", text:
      "· 管线按钮：只让选中的那条 Save 节点出图/出视频，其它 Save 静音，不会白跑；"
      + "选完之后面板只显示这条管线要用的提示词 / 参数 / LoRA / 模块。" }),
    el("p", { class: "ccd-hint", text:
      "· 参数 → 分辨率：★ 那一项是当前模型的训练分辨率（SDXL / Illustrious / ANIMA 1024×1024、"
      + "SD1.5 512×512），下面收的是 SDXL 官方训练桶和主流 16:9 / 9:16；⇄ 换长宽，"
      + "选「自定义」就手填宽 / 高。切模型时只有「宽高还停在上一个模型的推荐值」才会自动跟着换，"
      + "你挑过的比例不会被冲掉。" }),
    el("p", { class: "ccd-hint", text:
      "· 参数 → 采样器 / 调度器：清单直接从 KSampler 节点定义拉，装了什么插件就有什么。"
      + "图像那套写文生图 + 图生图两个子图，视频那套写 I2V / 首尾帧 / T2V；"
      + "高清化与脸手眼矫正有各自的稳定配方，不跟着这里改。" }),
    el("p", { class: "ccd-hint", text:
      "· ⟳ 取图 / ↻ 同步：把最后产出的那张图传给下游取图节点 —— "
      + "文生图 → 图生图 / 图生视频 / 首尾帧，图生图 → 图生视频 / 首尾帧（视频管线没有下游，不会被改）。"
      + "刚跑完的图由 Save 节点报回文件名，点一下立刻写入、不用等下拉刷新（以前那点延迟就在这）；"
      + "这次会话还没跑过图，就用 output 里最新的一张。" }),
    el("p", { class: "ccd-hint", text:
      "· 刷新下拉不会改你手动选的图：首尾帧那一对、图生图正在用的源图都会保留；"
      + "只有同步目标、以及点 ⟳ 时当前栏自己那格才换成新图。想换图就在画布上那格下拉里选。" }),
    el("p", { class: "ccd-hint", text:
      "· 模型切到 anima 会自动套 30 步 / CFG 4.5 / 不取层 / 姿势换成 LLLite。" }),
    el("p", { class: "ccd-hint", text:
      "· 提示词：图像两列（正/负）给文生图和图生图共用，视频两列同理；"
      + "正向 8 段按顺序拼（空段跳过），负向就是一个整框，不分段。" }),
    el("p", { class: "ccd-hint", text:
      "· 一段一个来源：不勾「插件输入」用手填文字；勾上就用接在「第 N 段」节点上的插件文本。" }),
    el("p", { class: "ccd-hint", text:
      "· ⌖ 跳到那一段的开关节点：把插件的文本输出（如 scene-composer 的 environment / action）连到它的「插件文本」口，回来勾上即可。" }),
    el("p", { class: "ccd-hint", text:
      "· 每段文字实际存在「第 N 段」开关节点上；拼接器节点里那 8 格是只读镜像，只为在画布上看一眼拼好的样子。" }),
    el("p", { class: "ccd-hint", text:
      "· 段数按需长：写过的下一行会自动出现，最多 8 段；再多就在画布上往后串一个拼接节点。" }),
    el("p", { class: "ccd-hint", text:
      "· 种子 🎲 随机默认开（每次出图换新种子），不勾就按输入框里的数字细调；旁边那个 🎲 按钮只随机一次。" }),
    el("p", { class: "ccd-hint", text:
      "· 参数按模块分区：生成参数 / 姿势参数 / 脸手眼矫正参数 / 高清参数 / 视频参数，"
      + "每一块只在对应模块开着时才显示，关掉模块那块自动收起来；重绘强度只在图生图显示。" }),
    el("p", { class: "ccd-hint", text:
      "· 脸手眼矫正最上面那四个勾是分级的：脸那级检测器最准；手（hand_yolov8s）和眼（Eyes.pt）"
      + "在多人交叠 / 复杂花纹上容易误检，误检一小块再重画就是「凭空长出多余的肢体 / 一片假眼」，"
      + "遇到这种怪图先关手和眼。关掉的那级走旁路：不检测、不重绘，链子也不会断。" }),
    el("p", { class: "ccd-hint", text:
      "· 「SAM 轮廓遮罩」默认开：用 models/sams/sam_vit_b_01ec64.pth 把检测框细化成贴合"
      + "人物轮廓的遮罩，再用这个轮廓去重绘；取消就回到 Impact 默认的矩形遮罩（快一点、边界糙一点）。" }),
    el("p", { class: "ccd-hint", text:
      "· 脸被「贴上去」、身体拼成两截：查「检测框放大尺寸」——填 1024 时一张 400px 的脸"
      + "会被放大 2.5 倍再采样，模型就在裁剪区里画一整张脸 + 头发 + 肩膀，缩回去贴回原处。"
      + "回到 512（默认）就正常了。" }),
    el("p", { class: "ccd-hint", text:
      "· 出图「像很多张拼起来」（分块痕迹）：先降「整体细化强度」到 0.08~0.10，"
      + "再降「分块精修强度」到 0.08~0.10，把「接缝修复强度」加到 0.35~0.40；"
      + "还重就把高清倍数降到 1.5，或直接关掉高清化模块。" }),
    el("p", { class: "ccd-hint", text:
      "· LoRA 行下面的状态：触发词（要写进提示词才锁得稳）、⚠ 已选但未启用、⚠ 与当前模型族可能不匹配。" }),
    el("p", { class: "ccd-hint", text:
      "· 面板只是遥控器，改的还是画布上的节点；双击子图进去能看到内部连线。" }),
    el("p", { class: "ccd-hint", text:
      "· 面板没出现？确认 custom_nodes/cc_dashboard/web/dock.js 在、刷新页面；"
      + "缺的插件节点会显示成顶上那条黄条。也可直接框选节点 Ctrl+B 旁路。" }),
    el("p", { class: "ccd-hint", text:
      "· 顶上出现橙色条 = 画布里那份还是旧蓝图（比如高清链多绕一趟 4x，"
      + "面板写 2 倍实际出 4 倍）。点「载入最新蓝图」就会带着你现在的提示词 / "
      + "LoRA / 参数重建并载进画布；顺便说一句，打开工作流时浏览器有时会恢复"
      + "上次内存里那份，而不是磁盘上最新那份，这条橙条就是用来戳穿它的。" }),
  ]);

  const bodies = {
    prompt: el("div", { class: "ccd-tab-body" }, [promptTab]),
    lora: el("div", { class: "ccd-tab-body" }, [loraTab]),
    param: el("div", { class: "ccd-tab-body" }, [paramTab]),
    help: el("div", { class: "ccd-tab-body" }, [helpTab]),
  };
  const body = el("div", { class: "ccd-body" },
    [bodies.prompt, bodies.lora, bodies.param, bodies.help]);
  const warn = el("div", {
    class: "ccd-missing ccd-hide",
    title: "这里列出的节点类型在当前 ComfyUI 里没注册，多半是缺插件包；"
      + "在 ComfyUI Manager 里点 Install Missing Custom Nodes 就能装。",
    onclick: () => {
      try {
        const txt = (warn.textContent || "").replace(/^⚠\s*/, "").trim();
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(txt);
        }
      } catch (e) { /* ignore */ }
    },
  });
  // 橙色条：画布上还是旧蓝图时提醒 + 一键按画布现况重建
  const drift = el("div", { class: "ccd-drift ccd-hide" }, [
    el("span", { class: "ccd-drift-txt" }),
    el("button", {
      class: "ccd-drift-fix", text: "载入最新蓝图",
      onclick: () => { fixStaleBlueprint(); },
    }),
  ]);
  const root = el("div", { id: ROOT_ID }, [bar, qbar, warn, drift, body]);
  // 八向缩放把手
  for (const dir of ["n", "s", "w", "e", "nw", "ne", "sw", "se"]) {
    const h = el("div", { class: "ccd-rs", "data-dir": dir });
    h.addEventListener("pointerdown", (ev) => beginResize(ev, dir));
    root.appendChild(h);
  }
  // 标题栏拖动（按钮/下拉上不触发）
  bar.addEventListener("pointerdown", beginBarDrag);
  // 记住最后编辑的输入框：收回 / 关独立窗口时要把「还没失焦」的改动提交掉
  root.addEventListener("focusin", (e) => {
    ui.lastEdit = (e && e.target) || null;
  });
  document.body.appendChild(root);

  Object.assign(ui, {
    root, pipeBtns, modelSel, modBtns, tabBtns, foldBtn, bodies,
    focusBtn, pipBtn, dockBtn,
    qNum, qRun, qFront, qStop, qCount, qMsg, qbar,
    promptBoxes, loraCols, paramInputs, paramSections, segGroups, seedChks,
    tileChks, roFields, paramCombos, stageChks, warnSpans,
    imgParamSet, vidParamSet, modHint, parStatus, warn, drift, toolStatus,
    st, lastModelList: "", lastLoraCount: {}, loraViews: {}, loraNode: {},
    loraWarn: {}, probeNode: null, segAll: {}, lastPipe: "",
    lastImage: null, runPending: false, paramApplied: false,
    qAt: 0, qRunning: 0, qPending: 0, qMsgTimer: 0,
    lastEdit: null,
  });
  refreshCombos();
  applyGeom();
  setTab(st.tab || "prompt", true);
  setFolded(!!st.folded, true);
  paintQueue();
  fetchLoraTriggers();
}

// ------------------------------------------------- 浮动窗：位置 / 拖动 / 缩放
let pipWin = null;   // Document Picture-in-Picture 的独立窗口
let dragging = false;   // 正在拖动 / 缩放时，sync 不要重新套几何

function rootWin() {
  try {
    const d = ui.root && ui.root.ownerDocument;
    return (d && d.defaultView) || window;
  } catch (e) {
    return window;
  }
}

function inPiP() {
  return !!pipWin;
}

/** 位置尺寸兜底：完全跑到视口外（换屏、改分辨率）时拉回来 */
function clampGeom(g) {
  const w0 = rootWin();
  const vw = Math.max(360, w0.innerWidth || 1280);
  const vh = Math.max(260, w0.innerHeight || 800);
  const src = g && typeof g === "object" ? g : {};
  let w = Math.round(Number(src.w) || Math.min(900, Math.max(GEOM_MIN_W, vw - 80)));
  let h = Math.round(Number(src.h) || Math.min(560, Math.max(GEOM_MIN_H, vh - 160)));
  w = Math.max(GEOM_MIN_W, Math.min(w, 6000));
  h = Math.max(GEOM_MIN_H, Math.min(h, 4000));
  const defX = Math.round(vw - w - 24);
  const defY = 64;
  let x = Number.isFinite(Number(src.x)) ? Math.round(Number(src.x)) : defX;
  let y = Number.isFinite(Number(src.y)) ? Math.round(Number(src.y)) : defY;
  if (x > vw - GEOM_EDGE) x = Math.max(0, defX);
  if (y > vh - GEOM_EDGE) y = Math.max(0, Math.min(defY, vh - h));
  if (x + w < GEOM_EDGE) x = Math.max(0, defX);
  if (y + h < GEOM_EDGE) y = 0;
  return { x: x, y: y, w: w, h: h };
}

function writeGeomNow() {
  const root = ui.root;
  const g = ui.st.geom || {};
  if (Number.isFinite(g.x)) root.style.left = Math.round(g.x) + "px";
  if (Number.isFinite(g.y)) root.style.top = Math.round(g.y) + "px";
  if (Number.isFinite(g.w)) root.style.width = Math.round(g.w) + "px";
  if (Number.isFinite(g.h)) root.style.height = Math.round(g.h) + "px";
}

/** 把状态里的模式/几何写进 DOM（浮动 / 停靠 / 独立窗口） */
function applyGeom() {
  const root = ui.root;
  if (!root || dragging) return;
  const docked = !!ui.st.docked && !inPiP();
  root.classList.toggle("ccd-docked", docked);
  root.classList.toggle("ccd-pip", inPiP());
  if (docked) {
    root.style.position = "fixed";
    root.style.left = "0";
    root.style.right = "0";
    root.style.top = computeTop() + "px";
    root.style.width = "";
    root.style.height = "";
    return;
  }
  root.style.right = "auto";
  if (inPiP()) {
    // 独立窗口里铺满自己的窗口
    root.style.position = "relative";
    root.style.left = "0";
    root.style.top = "0";
    root.style.width = "100%";
    root.style.height = "100vh";
    return;
  }
  root.style.position = "fixed";
  const g = clampGeom(ui.st.geom || {});
  ui.st.geom = g;
  writeGeomNow();
}

function beginBarDrag(e) {
  if (e.button !== 0 || inPiP() || ui.st.docked) return;
  const t = e.target;
  if (t && t.closest &&
    t.closest("button,select,input,textarea,option,label,a,[data-nodrag]")) return;
  startDrag(e, "move", "");
}

function beginResize(e, dir) {
  if (e.button !== 0 || inPiP() || ui.st.docked) return;
  startDrag(e, "size", dir);
}

function startDrag(e, mode, dir) {
  const root = ui.root;
  const win = rootWin();
  const r = root.getBoundingClientRect();
  const sx = e.clientX, sy = e.clientY;
  const base = { x: r.left, y: r.top, w: r.width, h: r.height };
  try { e.preventDefault(); e.stopPropagation(); } catch (err) { /* ignore */ }
  dragging = true;
  root.classList.add("ccd-drag");
  let pending = null;
  let raf = 0;
  const flush = () => {
    raf = 0;
    if (pending) {
      ui.st.geom = pending;
      writeGeomNow();
      pending = null;
    }
  };
  const move = (ev) => {
    const dx = ev.clientX - sx, dy = ev.clientY - sy;
    if (mode === "move") {
      pending = { x: base.x + dx, y: base.y + dy, w: base.w, h: base.h };
    } else {
      let x = base.x, y = base.y, w = base.w, h = base.h;
      if (dir.indexOf("e") >= 0) w = base.w + dx;
      if (dir.indexOf("s") >= 0) h = base.h + dy;
      if (dir.indexOf("w") >= 0) { w = base.w - dx; x = base.x + dx; }
      if (dir.indexOf("n") >= 0) { h = base.h - dy; y = base.y + dy; }
      if (w < GEOM_MIN_W) {
        if (dir.indexOf("w") >= 0) x -= GEOM_MIN_W - w;
        w = GEOM_MIN_W;
      }
      if (h < GEOM_MIN_H) {
        if (dir.indexOf("n") >= 0) y -= GEOM_MIN_H - h;
        h = GEOM_MIN_H;
      }
      pending = { x: x, y: y, w: w, h: h };
    }
    if (!raf) raf = win.requestAnimationFrame(flush);
  };
  const up = () => {
    win.removeEventListener("pointermove", move);
    win.removeEventListener("pointerup", up);
    win.removeEventListener("pointercancel", up);
    if (raf) { try { win.cancelAnimationFrame(raf); } catch (err) { /* ignore */ } }
    if (pending) { ui.st.geom = pending; pending = null; }
    dragging = false;
    root.classList.remove("ccd-drag");
    ui.st.docked = false;
    saveState(ui.st);
    applyGeom();
    sync(true);
  };
  win.addEventListener("pointermove", move);
  win.addEventListener("pointerup", up);
  win.addEventListener("pointercancel", up);
}

// ------------------------------------------------- 独立窗口（Document PiP）
function pipAvailable() {
  try {
    return !!(window.documentPictureInPicture &&
      typeof window.documentPictureInPicture.requestWindow === "function");
  } catch (e) {
    return false;
  }
}

function injectPiPStyles(doc) {
  try {
    if (!doc || doc.querySelector("style[data-cc-dock]")) return;
    const s = doc.createElement("style");
    s.setAttribute("data-cc-dock", "1");
    s.textContent = CSS;
    (doc.head || doc.documentElement).appendChild(s);
  } catch (e) {
    log("pip 样式注入失败", e);
  }
}

async function popOut() {
  if (inPiP()) return true;
  if (!pipAvailable()) {
    log("当前浏览器不支持 Document PiP，改用页面内浮动窗");
    return false;
  }
  const g = clampGeom(ui.st.geom || {});
  let win = null;
  try {
    win = await window.documentPictureInPicture.requestWindow({
      width: Math.round(g.w), height: Math.round(g.h),
    });
  } catch (e) {
    log("独立窗口被拒绝（需要用户点击触发）", e);
    return false;
  }
  pipWin = win;
  try {
    injectPiPStyles(win.document);
    win.document.title = "ComfyUI 总控台";
    win.document.body.style.margin = "0";
    win.document.body.style.overflow = "hidden";
    win.document.body.style.background = "#16171c";
    win.document.body.appendChild(ui.root);
    win.addEventListener("pagehide", () => popIn(true));
    // 切到别的窗口（比如回主窗口按 Ctrl+Enter 跑图）时，把还在输入框里没失焦的改动先落盘
    win.addEventListener("blur", () => {
      try { commitPendingEdit(); } catch (e) { /* ignore */ }
    });
    win.addEventListener("resize", () => {
      try { sync(true); } catch (e) { /* ignore */ }
    });
  } catch (e) {
    log("独立窗口挂载失败", e);
  }
  ui.st.pip = true;
  saveState(ui.st);
  applyGeom();
  sync(true);
  return true;
}

/**
 * 「改了但还没失焦」的值先提交一次（等价于用户点了别处）。
 * 关独立窗口时用：不然最后那段没失焦的文字会跟着窗口一起没了。
 */
function commitPendingEdit() {
  try {
    const host = ui.root;
    if (!host) return false;
    const doc = host.ownerDocument || document;
    let el = null;
    try {
      el = ui.lastEdit || doc.activeElement || null;
    } catch (e) { el = ui.lastEdit || null; }
    if (!el || (el.closest && !el.closest("#" + ROOT_ID))) return false;
    const tag = String(el.tagName || "").toUpperCase();
    if (tag !== "INPUT" && tag !== "TEXTAREA" && tag !== "SELECT") return false;
    if (typeof el.dispatchEvent === "function" && typeof Event === "function") {
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    }
    if (typeof el.dispatch === "function") {   // 测试桩
      el.dispatch("change", {});
      return true;
    }
  } catch (e) { log("提交未失焦的编辑", e); }
  return false;
}

function popIn(fromClosed) {
  if (!pipWin) return;
  const win = pipWin;
  pipWin = null;
  commitPendingEdit();   // 收回 / 关窗之前，先把没失焦的输入落盘
  try {
    if (ui.root && ui.root.ownerDocument !== document) {
      document.body.appendChild(ui.root);
    }
  } catch (e) {
    log("收回面板失败", e);
  }
  ui.st.pip = false;
  saveState(ui.st);
  if (!fromClosed) {
    try { win.close(); } catch (e) { /* ignore */ }
  }
  applyGeom();
  sync(true);
}

async function togglePiP(force) {
  const want = force === undefined ? !inPiP() : !!force;
  try {
    if (want) await popOut();
    else popIn(false);
  } catch (e) {
    log("切换独立窗口失败", e);
  }
  sync(true);
}

function toggleDocked() {
  if (inPiP()) popIn(false);
  ui.st.docked = !ui.st.docked;
  if (!ui.st.geom) ui.st.geom = clampGeom({});
  saveState(ui.st);
  applyGeom();
  sync(true);
}

function toggleFocus(on) {
  ui.st.focus = on === undefined ? !ui.st.focus : !!on;
  saveState(ui.st);
  sync(true);
}

// ------------------------------------------------- 跟随执行（默认开）
const FOCUS = { last: null, at: 0, guard: 0 };

/** "13:5" 这类执行 id → 真实节点（先按路径钻进子图） */
function nodeByExecId(execId) {
  const rootG = app.graph && (app.graph.rootGraph || app.graph);
  if (!rootG || execId === undefined || execId === null) return null;
  const parts = String(execId).split(":").filter((s) => s.length > 0);
  if (!parts.length) return null;
  let g = rootG;
  for (let i = 0; i < parts.length - 1; i++) {
    const mid = g.getNodeById ? g.getNodeById(parts[i]) : null;
    if (!mid || !mid.subgraph) return null;
    g = mid.subgraph;
  }
  const id = parts[parts.length - 1];
  return (g && g.getNodeById ? g.getNodeById(id) : null) || null;
}

/** 用户正在操作画布时先别抢镜头 */
function markCanvasTouch() {
  FOCUS.guard = Date.now() + 1200;
}

/** 切到节点所在的（子）图并居中放大 —— ⌖ 跳转与跟随执行共用 */
async function focusNode(node) {
  const canvas = app.canvas;
  if (!node || !canvas) return false;
  const target = node.graph || (app.graph && (app.graph.rootGraph || app.graph));
  try {
    if (target && canvas.graph !== target) {
      canvas.subgraph = target.isRootGraph ? undefined : target;
      if (typeof canvas.setGraph === "function") canvas.setGraph(target);
      else canvas.graph = target;
      await new Promise((r) => {
        try { requestAnimationFrame(() => requestAnimationFrame(r)); } catch (e) { r(); }
      });
    }
    const b = node.boundingRect;
    if (b && typeof canvas.animateToBounds === "function") {
      canvas.animateToBounds(b, { zoom: 0.8, duration: 320 });
    } else if (typeof canvas.centerOnNode === "function") {
      canvas.centerOnNode(node);
      if (canvas.setDirty) canvas.setDirty(true, true);
    }
    return true;
  } catch (e) {
    log("聚焦节点失败", e);
    return false;
  }
}

async function focusExec(execId) {
  if (!ui.st || !ui.st.focus) return;
  if (!hasMarkers()) return;
  if (execId === undefined || execId === null || execId === "") return;
  const id = String(execId);
  const now = Date.now();
  if (id === FOCUS.last && now - FOCUS.at < 400) return;
  if (now < FOCUS.guard || now - FOCUS.at < 130) return;
  const node = nodeByExecId(id);
  if (!node) return;
  FOCUS.last = id;
  FOCUS.at = now;
  await focusNode(node);
}

// ---------------------------------------------------------------- 动作
function setTab(k, silent) {
  ui.st.tab = k;
  for (const key of Object.keys(ui.tabBtns)) {
    ui.tabBtns[key].classList.toggle("ccd-on", key === k);
    ui.bodies[key].classList.toggle("ccd-on", key === k);
  }
  if (!silent) saveState(ui.st);
}

function setFolded(v, silent) {
  ui.st.folded = !!v;
  ui.root.classList.toggle("ccd-folded", !!v);
  ui.foldBtn.textContent = v ? "▸" : "▾";
  if (!silent) saveState(ui.st);
}

function pickPipeline(k) {
  for (const n of findNodes("save")) {
    setMode(n, keyOf(n) === k ? 0 : 2);
  }
  ui.st.pipe = k;
  saveState(ui.st);
  markChanged();
  // 这里不自动改取图节点：跑完图时已经自动传下来了，切栏不该动你手上选好的那张。
  // 想手动带一下就用顶栏的 ⟳ 取图 / ↻ 同步。
  sync(true);
}

/** 当前管线：以画布上唯一没静音的 Save 为准（面板没加载时手改画布也认得） */
function activePipe() {
  const keys = findNodes("save")
    .filter((n) => n.mode === 0).map(keyOf).filter(Boolean);
  return keys[0] || ui.st.pipe || "t2i";
}

const pipeKind = (k) => PIPE_KIND[k] || "image";

/** 这个模块现在是不是真的在跑（画布上至少一个实例没被旁路） */
function moduleRunning(key) {
  if (key === "pose") return poseOn();
  return findNodes("module", key).some((n) => n.mode === 0);
}

/** 参数分区跟模块联动：模块关着就把那一块收起来，开着才显示 */
function applyParamSections() {
  const pipe = activePipe();
  const kind = pipeKind(pipe);
  for (const sec of Object.values(ui.paramSections || {})) {
    let on = sec.kind === kind;
    // 和模块按钮一个口径：这条管线上用不到该模块（比如图生图没有姿势），那块也不显示
    if (on && sec.module) {
      on = (PIPE_MODULES[pipe] || []).indexOf(sec.module) >= 0 &&
        moduleRunning(sec.module);
    }
    if (on && sec.pipes) on = sec.pipes.indexOf(pipe) >= 0;
    sec.box.classList.toggle("ccd-hide", !on);
    if (!on) continue;
    for (const f of sec.fields || []) {
      const show = !f.pipes || f.pipes.indexOf(pipe) >= 0;
      f.box.classList.toggle("ccd-hide", !show);
    }
  }
}

/** 面板随顶栏管线过滤：提示词两组 / 参数一组 / LoRA 组 / 模块按钮 */
function applyPipeFilter() {
  const k = activePipe();
  ui.lastPipe = k;
  const kind = pipeKind(k);
  for (const g of Object.values(ui.segGroups || {})) {
    g.box.classList.toggle("ccd-hide", g.kind !== kind);
  }
  if (ui.imgParamSet) ui.imgParamSet.classList.toggle("ccd-hide", kind !== "image");
  if (ui.vidParamSet) ui.vidParamSet.classList.toggle("ccd-hide", kind !== "video");
  if (ui.modHint) ui.modHint.classList.toggle("ccd-hide", kind === "image");
  const want = kind === "video" ? ["video_high", "video_low"] : ["image"];
  for (const [gk, rows] of Object.entries(ui.loraCols || {})) {
    const box = rows && rows.parentNode ? rows.parentNode : rows;
    if (box) box.classList.toggle("ccd-hide", want.indexOf(gk) < 0);
  }
  const mods = PIPE_MODULES[k] || [];
  for (const [mk, b] of Object.entries(ui.modBtns || {})) {
    b.classList.toggle("ccd-hide", mods.indexOf(mk) < 0);
  }
  applyParamSections();
}

function currentModel() {
  const n = findNode("model_slot");
  return n ? readValue(n, "model_slot") : "";
}

function poseOn() {
  return findNodes("module", "pose_sdxl")
    .concat(findNodes("module", "pose_anima"))
    .some((n) => n.mode === 0);
}

function applyPoseFamily(on) {
  on = on === undefined ? poseOn() : !!on;
  const anima = isAnimaModel(currentModel());
  for (const n of findNodes("module", "pose_sdxl")) {
    setMode(n, on && !anima ? 0 : 4);
  }
  for (const n of findNodes("module", "pose_anima")) {
    setMode(n, on && anima ? 0 : 4);
  }
  ui.st.modules.pose = on;
}

// ------------------------------------------------ 脸手眼矫正：三级 / SAM 开关
// 这几个开关写的是「脸手眼矫正」子图内部节点的 mode（子图定义在两条图像管线间
// 是共享的，所以调一次文生图和图生图一起变）：
//   三级 FaceDetailer  → 0 正常 / 4 旁路（图从 image 口穿过去，链子不断）
//   SAMLoader          → 0 加载 / 2 静音（静音后 sam_model_opt 这个可选输入不解析）
const DETAILER_STAGES = ["face", "hand", "eye"];

function detailerStageOn(k) {
  return findNodes("detailer_stage", k).some((n) => n.mode === 0);
}

function setDetailerStage(k, on) {
  for (const n of findNodes("detailer_stage", k)) setMode(n, on ? 0 : 4);
}

function detailerSamOn() {
  return findNodes("detailer_sam", "sam").some((n) => n.mode === 0);
}

function setDetailerSam(on) {
  for (const n of findNodes("detailer_sam", "sam")) setMode(n, on ? 0 : 2);
}

/** 面板上的「脸 / 手 / 眼 / SAM」四个勾 → 子图内部节点的 mode */
function applyDetailerToggle(k, on) {
  if (k === "sam") setDetailerSam(on);
  else setDetailerStage(k, on);
}

function detailerToggleOn(k) {
  return k === "sam" ? detailerSamOn() : detailerStageOn(k);
}

function toggleModule(k, on) {
  ui.st.modules[k] = !!on;
  if (k === "pose") {
    applyPoseFamily(on);
  } else {
    for (const n of findNodes("module", k)) setMode(n, on ? 0 : 4);
  }
  saveState(ui.st);
  sync(true);
}

/** 参数页「↺ 重置默认值」：只写参数节点 + 种子随机开关。

    不动模型槽、提示词、LoRA、管线 / 模块开关和取图节点。
 */
// ------------------------------------------------- 参数持久化（浏览器本地）
// 面板上调过的参数记在 localStorage 里：刷新页面、重开工作流都还在，
// 不会「每次都被重置回默认值」。只有「参数」这一组会记；
// 模型槽 / LoRA / 提示词 / 管线与模块开关本来就跟着工作流存，不在这里管。
const PARAM_LS_PREFIX = "cc_dock_params_v1:";

function paramStoreKey() {
  let name = "";
  try {
    const wf = app.extensionManager && app.extensionManager.workflow
      && app.extensionManager.workflow.activeWorkflow;
    name = (wf && (wf.path || wf.name)) || "";
  } catch (e) { /* 老版本前端没有 extensionManager */ }
  if (!name) {
    try {
      name = (app.graph && (app.graph.name || app.graph.id)) || "";
    } catch (e) { /* ignore */ }
  }
  return PARAM_LS_PREFIX + (String(name).replace(/\\/g, "/") || "default");
}

function loadStoredParams() {
  try {
    const raw = localStorage.getItem(paramStoreKey());
    const o = raw ? JSON.parse(raw) : null;
    return (o && typeof o === "object") ? o : {};
  } catch (e) { return {}; }
}

/** 面板上改了哪个参数就记一个（存不进去也不影响出图） */
function storeParam(k, v) {
  if (!k) return;
  let val;
  if (typeof v === "number") {
    if (!isFinite(v)) return;
    val = v;
  } else if (typeof v === "string") {
    if (!v) return;
    val = v;                 // 采样器 / 调度器这类字符串参数
  } else {
    val = Number(v);
    if (isNaN(val)) return;
  }
  try {
    const st = loadStoredParams();
    if (String(st[k]) === String(val)) return;
    st[k] = val;
    localStorage.setItem(paramStoreKey(), JSON.stringify(st));
  } catch (e) { /* ignore */ }
}

/** 打开工作流时把上次调好的参数写回画布；每次载入只做一次，之后以画布为准 */
function applyStoredParams() {
  if (ui.paramApplied) return 0;
  ui.paramApplied = true;
  const st = loadStoredParams();
  let n = 0;
  for (const k of Object.keys(st)) {
    const node = findNode("param", k);
    if (!node) {
      // 字符串类参数（采样器 / 调度器）：交给对应下拉写回画布
      const c = ui.paramCombos && ui.paramCombos[k];
      if (c && typeof st[k] === "string") {
        try {
          if (applyComboValue(c, st[k])) n++;
        } catch (e) { log("applyStoredParams", e); }
      }
      continue;
    }
    const want = Number(st[k]);
    const cur = Number(readValue(node, "param"));
    if (isNaN(want) || cur === want) continue;
    writeValue(node, "param", want);
    const inp = ui.paramInputs && ui.paramInputs[k];
    if (inp && !focused(inp)) inp.value = want;
    n++;
  }
  return n;
}

/** 读参数节点的数字（PrimitiveInt / PrimitiveFloat 的 value 格） */
function paramNum(k) {
  const n = findNode("param", k);
  if (!n) return null;
  const v = Number(readValue(n, "param"));
  return isNaN(v) ? null : v;
}

/** 高清子图里的分块精修节点（定义被文生图 / 图生图共用，所以通常就一个） */
function usduNodes() {
  const out = [];
  eachGraph((n) => {
    if (n && n.type === "UltimateSDUpscaleNoUpscale") out.push(n);
  });
  return out;
}

/** 高清参数里那两行只读提示：输出尺寸 / 实际分块 */
function updateRoFields() {
  const f = ui.roFields || {};
  const w = paramNum("width"), h = paramNum("height");
  const k = paramNum("upscale_factor"), tile = paramNum("upscale_tile");
  if (f.__ro_size) {
    let txt = (w && h && k)
      ? Math.round(w * k) + "×" + Math.round(h * k)
        + "（" + w + "×" + h + " × " + k + "）"
      : "—";
    // 画布上是旧高清链（多绕一趟 4x→缩回）时，这里报的必须是真会出来的尺寸
    const d = ui.driftInfo;
    if (d && d.legacy && w && h && k) {
      txt = Math.round(w * k * 2) + "×" + Math.round(h * k * 2)
        + "（旧链实际 = " + w + "×" + h + " × " + k + " × 2）";
    }
    f.__ro_size.textContent = txt;
  }
  if (f.__ro_tile) {
    f.__ro_tile.textContent = tile
      ? tile + "×" + tile + (TILE_AUTO.on ? "（自动）" : "（手动）")
      : "—";
  }
}

/** 分块大小落地：自动按「原图 × 倍数」算，手填就照参数写进分块精修节点。

    分块参数在画布上是真输入（喂给两条图像管线的分块精修），所以写参数节点
    才是真正改动出图结果的那一步；顺手也把子图里的 widget 同步一下，看画布不别扭。
 */
function applyTileAuto(quiet) {
  const w = paramNum("width"), h = paramNum("height"), f = paramNum("upscale_factor");
  if (w === null || h === null || f === null) return 0;
  let changed = 0;
  let tile = paramNum("upscale_tile");
  if (TILE_AUTO.on) {
    const want = autoTileSize(w, h, f);
    if (tile !== want) {
      const p = findNode("param", "upscale_tile");
      if (p) { writeValue(p, "param", want); changed++; }
      storeParam("upscale_tile", want);
      const inp = ui.paramInputs && ui.paramInputs.upscale_tile;
      if (inp) inp.value = want;
      tile = want;
    }
  }
  if (tile !== null) {
    for (const n of usduNodes()) {
      for (const name of ["tile_width", "tile_height"]) {
        const wd = widgetOf(n, name);
        if (wd && wd.value !== tile) { wd.value = tile; changed++; }
      }
    }
  }
  if (changed && !quiet) markChanged();
  updateRoFields();
  return changed;
}

// ------------------------------- 下拉参数：分辨率预设 / 采样器 / 调度器
/** 采样器 / 调度器的可选值：先读节点定义，读不到再退回内置清单 */
let SAMPLER_JSON = null;
let SAMPLER_PULLED = false;

function samplerEnum(media, name) {
  const types = media === "video" ? ["KSamplerAdvanced", "KSampler"]
    : ["KSampler"];
  for (const t of types) {
    const v = comboValues(nodeDef(t), name);
    if (v.length) return v;
  }
  if (SAMPLER_JSON) {
    for (const t of types) {
      const v = comboValues(SAMPLER_JSON[t], name);
      if (v.length) return v;
    }
  }
  return null;
}

const samplerValues = (media) =>
  samplerEnum(media, "sampler_name") || SAMPLER_FALLBACK.slice();
const schedulerValues = (media) =>
  samplerEnum(media, "scheduler") || SCHEDULER_FALLBACK.slice();

/** 节点定义还没注册好（插件加载顺序）时，拉一次 /object_info/KSampler 兜底 */
function ensureSamplerEnums() {
  if (SAMPLER_PULLED || samplerEnum("image", "sampler_name")) return;
  SAMPLER_PULLED = true;
  try {
    fetch("/object_info/KSampler").then((r) => r.json()).then((j) => {
      if (j && j.KSampler) {
        SAMPLER_JSON = j;
        refreshCombos(true);
      }
    }).catch(() => { /* 服务没响应就用内置清单 */ });
  } catch (e) { /* ignore */ }
}

/** 图像 / 视频各自的采样节点：对应管线的子图里所有 KSampler / KSamplerAdvanced */
function samplerNodesOf(media) {
  const want = SAMPLER_PIPES[media] || [];
  const out = [];
  const take = (x) => {
    if (x && (x.type === "KSampler" || x.type === "KSamplerAdvanced")) out.push(x);
  };
  for (const p of findNodes("pipeline")) {
    if (want.indexOf(keyOf(p)) < 0) continue;
    eachGraph(take, p.subgraph);
  }
  if (!out.length) {
    // 兜底：按子图名字认（老前端上 pipeline 标记没读出来时）
    const re = media === "video" ? /视频/ : /(^文生图$|图生图)/;
    eachGraph((x) => {
      if (!x || !x.subgraph || typeof x.isSubgraphNode !== "function") return;
      if (!x.isSubgraphNode()) return;
      const nm = String((x.subgraph && x.subgraph.name) || x.title || "");
      if (re.test(nm)) eachGraph(take, x.subgraph);
    });
  }
  return out;
}

function canvasSampler(media, name) {
  for (const n of samplerNodesOf(media)) {
    const w = widgetOf(n, name);
    if (w && typeof w.value === "string" && w.value) return w.value;
  }
  return null;
}

function writeSamplerToCanvas(media, name, val) {
  let n = 0;
  for (const x of samplerNodesOf(media)) {
    if (writeWidget(x, name, val)) n++;
  }
  return n;
}

/** 当前宽高落在哪个选项上：__rec（模型推荐） / "1216x832" / __custom */
function resValueOf(media, w, h) {
  const rec = media === "video" ? VIDEO_RES_FALLBACK : recommendedRes(currentModel());
  if (rec.w === w && rec.h === h) return "__rec";
  for (const p of RES_PRESETS[media] || []) {
    if (p.w === w && p.h === h) return p.w + "x" + p.h;
  }
  return "__custom";
}

function ensureOption(s, val, text) {
  if (!val) return;
  for (const o of (s.options || s.children || [])) {
    if (o.value === val) return;
  }
  s.appendChild(optionEl(val, text || (val + "（不在列表）")));
}

/** <option>：value 既写属性也写值（老前端 / 测试桩上属性不一定反射成值） */
function optionEl(value, text) {
  const o = el("option", { value: value, text: text });
  try { o.value = value; } catch (e) { /* ignore */ }
  return o;
}

/** 重建下拉选项（模型换了 / 节点定义刚加载完才需要重建） */
function refreshCombos(force) {
  ensureSamplerEnums();
  for (const c of Object.values(ui.paramCombos || {})) {
    if (!c || !c.sel) continue;
    if (c.kind === "resolution") {
      const rec = c.media === "video" ? VIDEO_RES_FALLBACK
        : recommendedRes(currentModel());
      const sig = c.media + "|" + rec.w + "x" + rec.h;
      if (!force && sig === c.sig && c.sel.children.length) continue;
      c.sig = sig;
      c.sel.textContent = "";
      c.sel.appendChild(optionEl("__rec",
        "★ 推荐 " + rec.w + " × " + rec.h + " · " + rec.why));
      for (const p of RES_PRESETS[c.media] || []) {
        if (p.w === rec.w && p.h === rec.h) continue;
        c.sel.appendChild(optionEl(p.w + "x" + p.h,
          p.w + " × " + p.h + "　" + p.tag));
      }
      c.customOpt = optionEl("__custom", "自定义（直接改下面的宽 / 高）");
      c.sel.appendChild(c.customOpt);
    } else {
      const list = c.kind === "sampler" ? samplerValues(c.media)
        : schedulerValues(c.media);
      const sig = c.kind + "|" + c.media + "|" + list.join(",");
      if (!force && sig === c.sig && c.sel.children.length) continue;
      c.sig = sig;
      const cur = c.sel.value;
      c.sel.textContent = "";
      for (const v of list) c.sel.appendChild(optionEl(v, v));
      ensureOption(c.sel, cur);
    }
  }
  syncCombos();
}

/** 把画布上的真实值回填到下拉（每秒跟着 sync 跑，不抢焦点） */
function syncCombos() {
  for (const c of Object.values(ui.paramCombos || {})) {
    if (!c || !c.sel || focused(c.sel)) continue;
    if (c.kind === "resolution") {
      const wk = c.media === "video" ? "video_width" : "width";
      const hk = c.media === "video" ? "video_height" : "height";
      const w = paramNum(wk), h = paramNum(hk);
      if (w === null || h === null) continue;
      if (c.customOpt) {
        const t = "自定义（当前 " + w + "×" + h + "，改下面的宽 / 高）";
        if (c.customOpt.textContent !== t) c.customOpt.textContent = t;
      }
      const want = resValueOf(c.media, w, h);
      if (c.sel.value !== want) c.sel.value = want;
    } else {
      const name = c.kind === "sampler" ? "sampler_name" : "scheduler";
      const cur = canvasSampler(c.media, name) || SAMPLER_DEFAULTS[c.key] || "";
      if (!cur) continue;
      ensureOption(c.sel, cur);
      if (c.sel.value !== cur) c.sel.value = cur;
    }
  }
}

/** 写宽高（分辨率预设落地）：参数节点 + 浏览器记忆 + 分块自动跟随 */
function writeResolution(media, w, h) {
  const wk = media === "video" ? "video_width" : "width";
  const hk = media === "video" ? "video_height" : "height";
  const wn = findNode("param", wk), hn = findNode("param", hk);
  if (wn) writeValue(wn, "param", w);
  if (hn) writeValue(hn, "param", h);
  storeParam(wk, w);
  storeParam(hk, h);
  const wi = ui.paramInputs && ui.paramInputs[wk];
  const hi = ui.paramInputs && ui.paramInputs[hk];
  if (wi && !focused(wi)) wi.value = w;
  if (hi && !focused(hi)) hi.value = h;
  applyTileAuto();
  return true;
}

function applyComboValue(c, val) {
  if (!c || !val) return false;
  if (c.kind === "resolution") {
    let w, h;
    if (val === "__rec") {
      const rec = c.media === "video" ? VIDEO_RES_FALLBACK
        : recommendedRes(currentModel());
      w = rec.w; h = rec.h;
    } else {
      const m = /^(\d+)x(\d+)$/.exec(val);
      if (!m) return false;
      w = parseInt(m[1], 10); h = parseInt(m[2], 10);
    }
    return writeResolution(c.media, w, h);
  }
  const name = c.kind === "sampler" ? "sampler_name" : "scheduler";
  const n = writeSamplerToCanvas(c.media, name, val);
  storeParam(c.key, val);
  return n > 0;
}

function onComboPick(key, val) {
  const c = (ui.paramCombos || {})[key];
  if (!c) return;
  if (val === "__custom") {
    flashParamStatus("已切到自定义分辨率：直接改下面的宽 / 高");
    return;
  }
  applyComboValue(c, val);
  markChanged();
  sync(true);
}

/** ⇄ 交换长宽（图像 / 视频两套各一个按钮） */
function swapWH(kind) {
  const wk = kind === "video" ? "video_width" : "width";
  const hk = kind === "video" ? "video_height" : "height";
  const w = paramNum(wk), h = paramNum(hk);
  if (w === null || h === null) return;
  const nw = findNode("param", wk), nh = findNode("param", hk);
  if (nw) writeValue(nw, "param", h);
  if (nh) writeValue(nh, "param", w);
  storeParam(wk, h);
  storeParam(hk, w);
  if (ui.paramInputs && ui.paramInputs[wk]) ui.paramInputs[wk].value = h;
  if (ui.paramInputs && ui.paramInputs[hk]) ui.paramInputs[hk].value = w;
  applyTileAuto();
  markChanged();
  sync(true);
}

function resetParams() {
  const preset = isAnimaModel(currentModel()) ? PRESET.anima : PRESET.sdxl;
  const values = Object.assign({}, PARAM_DEFAULTS,
    { steps: preset.steps, cfg: preset.cfg,
      width: recommendedRes(currentModel()).w,
      height: recommendedRes(currentModel()).h });
  let n = 0;
  for (const k of Object.keys(values)) {
    const node = findNode("param", k);
    if (!node) continue;
    writeValue(node, "param", values[k]);
    storeParam(k, values[k]);        // 记住「已重置」，刷新后不会再弹回你改过的值
    n++;
  }
  // 下拉参数：采样器 / 调度器回到各自那套默认
  for (const [k, v] of Object.entries(SAMPLER_DEFAULTS)) {
    const c = ui.paramCombos && ui.paramCombos[k];
    if (!c) continue;
    applyComboValue(c, v);
    storeParam(k, v);
    n++;
  }
  SEED_RANDOM.image = true;
  SEED_RANDOM.video = true;
  for (const k of ["seed", "video_seed"]) writeSeedRandom(k, true);
  // 脸手眼矫正：三级 + SAM 回到「全开」（最完整的配方 = 模板默认）
  for (const k of DETAILER_STAGES) {
    applyDetailerToggle(k, true);
    if (ui.stageChks && ui.stageChks[k]) ui.stageChks[k].checked = true;
  }
  applyDetailerToggle("sam", true);
  if (ui.stageChks && ui.stageChks.sam) ui.stageChks.sam.checked = true;
  TILE_AUTO.on = true;              // 分块也回到「自动跟随分辨率」
  if (ui.tileChks && ui.tileChks.auto) ui.tileChks.auto.checked = true;
  applyTileAuto();
  refreshCombos(true);
  markChanged();
  sync(true);
  return n;
}

let paramStatusTimer = 0;

/** 重置后在那行显示一句话，几秒后自动消失 */
function flashParamStatus(text) {
  if (!ui.parStatus) return;
  ui.parStatus.textContent = text;
  if (paramStatusTimer) clearTimeout(paramStatusTimer);
  paramStatusTimer = setTimeout(() => {
    if (ui.parStatus) ui.parStatus.textContent = "";
  }, 4000);
}

/** CLIP / VAE 来源开关：1 = ckpt 自带，2 = ANIMA 专用 loader（110 / 111）。 */
function applyFamilySwitch(anima) {
  const idx = anima ? 2 : 1;
  for (const k of ["clip", "vae"]) {
    for (const n of findNodes("family", k)) writeValue(n, "family", idx);
  }
}

function onModelChange(name) {
  const before = currentModel();
  const n = findNode("model_slot");
  if (n) writeValue(n, "model_slot", name);
  const anima = isAnimaModel(name);
  const preset = anima ? PRESET.anima : PRESET.sdxl;
  const clip = findNode("preset_sdxl");
  if (clip) setMode(clip, preset.clipLayer);
  for (const [key, value] of [["steps", preset.steps], ["cfg", preset.cfg]]) {
    const p = findNode("param", key);
    if (p) writeValue(p, "param", value);
  }
  // 分辨率跟着模型走：只在「宽高还是上一个模型的推荐值」时才动它，
  // 免得把你特意选好的比例（比如 832×1216 竖图）在换模型时冲掉。
  try {
    const oldRec = recommendedRes(before);
    const w = paramNum("width"), h = paramNum("height");
    const rec = recommendedRes(name);
    if (w === oldRec.w && h === oldRec.h && (rec.w !== w || rec.h !== h)) {
      writeResolution("image", rec.w, rec.h);
      flashParamStatus("分辨率跟随模型：" + rec.w + "×" + rec.h + "（" + rec.why + "）");
    }
  } catch (e) { log("model resolution", e); }
  applyFamilySwitch(anima);   // CLIP / VAE 来源跟模型族走
  applyPoseFamily();   // 保持当前开关状态，只换族
  refreshCombos(true);
  markChanged();
  sync(true);
}

/** 刷新 output 下拉（LoadImageOutput）。

    前端刷完会顺手把每格改成「最新那张」（control_after_refresh: first），
    这会把你特意选的图冲掉（首尾帧那一对、图生图正在用的那张），所以刷完把
    「不该动的那几格」还原回去：只有同步目标、以及明确要取图的当前栏，才吃新图。
 */
function refreshImageCombos(opt) {
  const takeOwn = !!(opt && opt.own);
  const nodes = findNodes("source_image");
  const keep = [];
  for (const n of nodes) {
    const w = widgetOf(n, "image");
    if (w) keep.push([n, w, w.value]);
  }
  try {
    if (typeof app.refreshComboInNodes === "function") {
      app.refreshComboInNodes();
    }
  } catch (e) { log("refreshComboInNodes", e); }
  for (const n of nodes) {
    const w = (n.widgets || []).find((x) => x.name === "refresh") ||
      (n.widgets || []).find((x) => x.name === "upload");
    try {
      if (w && typeof w.callback === "function") {
        w.callback(w.value, app.canvas, n, [0, 0], null);
      }
    } catch (e) { log("refresh image", e); }
  }
  // 下拉是异步拉回来的：等它落地，再把不该改的格子还原成你原来选的
  const restore = () => {
    const pipe = activePipe();
    const dsts = IMG_TO_SOURCES[pipe] || [];
    const own = IMG_OWN_SOURCE[pipe];
    for (const [n, w, old] of keep) {
      if (typeof old !== "string" || !old || w.value === old) continue;
      const key = keyOf(n);
      if (dsts.indexOf(key) >= 0) continue;      // 同步目标：就该换成新图
      if (takeOwn && key === own) continue;      // 当前栏「取图」：也换成新图
      ensureWidgetValue(w, old);
      try {
        if (n.graph && typeof n.graph.setDirtyCanvas === "function") {
          n.graph.setDirtyCanvas(true, false);
        }
      } catch (e) { /* ignore */ }
    }
  };
  for (const ms of [80, 300, 900, 1800]) setTimeout(restore, ms);
  LORA_CACHE = null;
  LORA_TRIGGERS = null;
  LORA_TRIGGER_TRYING = {};
  ui.lastModelList = "";
  loraList();
  fetchLoraTriggers();
  // 刷新是异步的：连着再补几次，新图一进下拉就立刻传到下游，不用再点第二次
  syncOutputImageSoon();
  sync(true);
}

// ------------------------------------------------- 取图：输出图在管线之间传递
/** 每条管线的图往哪几个取图节点送（「输出图同步」的传递表）。

    文生图 -> 图生图 / 图生视频 / 首尾帧（首、尾都先接上，再自己改尾帧）
    图生图 -> 图生视频 / 首尾帧
    图生视频、首尾帧、文生视频 -> 没有下游，只作为来源
 */
const IMG_TO_SOURCES = {
  t2i: ["i2i", "i2v", "flf_start", "flf_end"],
  i2i: ["i2v", "flf_start", "flf_end"],
  i2v: [],
  flf2v: [],
  t2v: [],
};
// 取图节点的遍历顺序：上游管线在前
const IMG_SOURCE_ORDER = ["i2i", "i2v", "flf_start", "flf_end"];
// 反过来：这条管线自己用的是哪个取图节点（没有就退到 output 里最新那张）
const IMG_OWN_SOURCE = {
  t2i: null, i2i: "i2i", i2v: "i2v", flf2v: "flf_start", t2v: null,
};
// 每张图最多试几次、间隔多少毫秒（刷新下拉是异步的，多补几次就「不延迟」了）
const IMG_SYNC_TRIES = [0, 60, 200, 500, 900];
let imgSyncTimer = null;

/** output 里的值形如 "refined_00035_.png [output]"：只认图片，视频/占位符不要 */
const IMG_EXT = /\.(png|jpe?g|webp|gif|bmp|avif|tiff?)\s*(\[\w+\])?$/i;

function isImageValue(v) {
  return typeof v === "string" && v.length > 0 && IMG_EXT.test(v);
}

/** executed 事件里的 {filename, subfolder, type} → 取图节点认的带类型后缀的值 */
function outputImageValue(im) {
  if (!im || !im.filename) return null;
  const sub = im.subfolder ? String(im.subfolder).replace(/\\/g, "/") + "/" : "";
  return sub + im.filename + " [" + (im.type || "output") + "]";
}

/** Save 节点的 id → 管线 key（executed 里的 id 可能是子图内编号，如 "13:5"） */
function savePipeOf(id) {
  const s = (id === undefined || id === null) ? "" : String(id);
  if (!s) return null;
  const tail = s.indexOf(":") >= 0 ? s.slice(s.lastIndexOf(":") + 1) : "";
  for (const n of findNodes("save")) {
    const nid = String(n.id);
    if (nid !== s && !(tail && nid === tail)) continue;
    const k = (n.properties && n.properties.cc_dock_key) || null;
    if (k) return k;
  }
  return null;
}

/** 值在不在下拉里不重要：不在就先塞进去，画布/前端序列化读的是 widget.value */
function ensureWidgetValue(w, v) {
  if (!w) return;
  try {
    const opts = w.options;
    if (opts && Array.isArray(opts.values) && opts.values.indexOf(v) < 0) {
      opts.values.push(v);
    }
  } catch (e) { /* ignore */ }
  if (w.value === v) return;
  w.value = v;
}

function sourceNode(key) {
  return findNodes("source_image", key)[0] || null;
}

function sourceImageOf(key) {
  const n = sourceNode(key);
  return n ? readWidget(n, "image") : null;
}

/** output 列表按「最新在前」排，取任意一个 output 节点的第一张图就是最新那张 */
function newestOutputImage() {
  for (const key of IMG_SOURCE_ORDER) {
    const w = widgetOf(sourceNode(key), "image");
    const list = (w && w.options && w.options.values) || null;
    if (!list || !list.length) continue;
    for (const v of list) {
      if (isImageValue(v)) return v;
    }
  }
  return null;
}

/** 这一趟往下游传的图：本次会话里最后产出的那张（Save 报回来的文件名，不分哪一栏）；

    刚跑完时下拉还是旧的（刷新是异步的），用这个就不用等 —— 以前点了同步要等一会儿
    才生效，就是卡在下拉刷新上。没跑过任何图才退到 output 列表里最新那张。
 */
function syncSourceImage() {
  if (typeof ui.lastImage === "string" && ui.lastImage) return ui.lastImage;
  return newestOutputImage();
}

/** 当前管线这一趟该用的图：最新产出的那张，退而求其次才是它自己的取图节点 */
function activeOutputImage() {
  const pipe = activePipe();
  const fresh = syncSourceImage();
  if (fresh) return fresh;
  const own = IMG_OWN_SOURCE[pipe];
  const v = own ? sourceImageOf(own) : null;
  if (typeof v === "string" && v && v.indexOf("[input]") < 0) return v;
  return newestOutputImage();
}

/** 把当前管线的图同步到下游管线。返回真正改动的节点数。

    幂等：值一样就跳过，所以可以反复调用（刷新下拉是异步的，要试几次）。
 */
function applyOutputImage() {
  const pipe = activePipe();
  const dsts = IMG_TO_SOURCES[pipe] || [];
  if (!dsts.length) return 0;
  const img = activeOutputImage();
  if (!img) return 0;
  let n = 0;
  for (const key of dsts) {
    const node = sourceNode(key);
    if (!node) continue;
    const w = widgetOf(node, "image");
    if (!w) continue;
    if (w.value === img) continue;
    ensureWidgetValue(w, img);
    try {
      if (node.graph && typeof node.graph.setDirtyCanvas === "function") {
        node.graph.setDirtyCanvas(true, false);
      }
    } catch (e) { /* ignore */ }
    n++;
  }
  return n;
}

/** 连点几次（0 / 60 / 200 / 500 / 900ms），哪次刷新到了就哪次生效 */
function syncOutputImageSoon() {
  if (imgSyncTimer) clearTimeout(imgSyncTimer);
  let i = 0;
  const step = () => {
    let changed = 0;
    try {
      changed = applyOutputImage();
    } catch (e) { log("applyOutputImage", e); }
    i++;
    if (changed) markChanged();
    if (i < IMG_SYNC_TRIES.length) {
      imgSyncTimer = setTimeout(step, IMG_SYNC_TRIES[i]);
    } else {
      imgSyncTimer = null;
    }
  };
  step();
}

// ---------------------------------------------------------------- 同步
function computeTop() {
  const sels = [".comfyui-menu", ".comfy-menu", "#comfyui-menu",
    ".comfyui-top-menu", ".p-toolbar"];
  for (const s of sels) {
    try {
      const e = document.querySelector(s);
      if (!e) continue;
      const r = e.getBoundingClientRect();
      if (r.height > 0 && r.top <= 8) return Math.round(r.bottom);
    } catch (e) { /* ignore */ }
  }
  try {
    const v = getComputedStyle(document.documentElement)
      .getPropertyValue("--comfy-menu-bar-height");
    const n = parseFloat(v);
    if (!isNaN(n) && n > 0) return Math.round(n);
  } catch (e) { /* ignore */ }
  return 0;
}

/**
 * 这个输入框是不是正被用户编辑。
 * 必须看「它自己那份文档」的 activeElement：独立窗口（Document PiP）里
 * 面板元素住在另一份 document 里，写死主文档会永远返回 false，
 * 结果同步每 1.2s 把正在输入的内容用画布旧值盖回去，编辑就白改了。
 */
function focused(e) {
  try {
    const d = (e && e.ownerDocument) || document;
    return !!d && d.activeElement === e;
  } catch (err) {
    return false;
  }
}

function syncParams() {
  for (const k of Object.keys(ui.paramInputs || {})) {
    const inp = ui.paramInputs[k];
    if (!inp || focused(inp)) continue;
    const n = findNode("param", k);
    if (!n) continue;
    const v = readValue(n, "param");
    if (v !== null && String(inp.value) !== String(v)) inp.value = v;
  }
  syncCombos();
}

function nodeLabel(node) {
  if (!node) return "节点";
  return node.title || node.type || ("#" + node.id);
}

/** 提示词分段：文本框 / 启用 / 插件输入 / ⌖ 状态 / 自动展开 */
function syncSegs() {
  for (const [k, g] of Object.entries(ui.segGroups || {})) {
    const n = findNode("prompt", k);
    if (!n) continue;
    if (g.plain) {
      // 负面提示词：整框同步，就是一个值
      const txt = readWidget(n, "value");
      if (!focused(g.ta) && typeof txt === "string" && g.ta.value !== txt) {
        g.ta.value = txt;
      }
      continue;
    }
    const sep = readWidget(n, "separator");
    if (!focused(g.sep) && typeof sep === "string" && g.sep.value !== sep) {
      g.sep.value = sep;
    }
    const showAll = !!(ui.segAll && ui.segAll[k]);
    if (g.all && g.all.checked !== showAll) g.all.checked = showAll;
    let lastUsed = 0;
    for (let i = 0; i < SEG_MAX; i++) {
      if (segUsed(n, i)) lastUsed = i + 1;
    }
    const vis = showAll ? SEG_MAX
      : Math.max(SEG_SHOWN_MIN, Math.min(SEG_MAX, lastUsed + 2));
    for (let i = 0; i < g.rows.length; i++) {
      const row = g.rows[i];
      row.box.classList.toggle("ccd-hide", i >= vis);
      const txt = segText(n, i);
      if (!focused(row.ta) && row.ta.value !== txt) row.ta.value = txt;
      mirrorSegText(n, i, txt);
      const on = segEnable(n, i);
      if (row.enable.checked !== on) row.enable.checked = on;
      const linked = segPluginLinked(n, i);
      const plug = segPluginOn(n, i);
      if (row.plugin.checked !== plug) row.plugin.checked = plug;
      row.ta.classList.toggle("ccd-static", plug);
      row.box.classList.toggle("ccd-off", !on);
      row.box.classList.toggle("ccd-hit", plug && linked);
      const sw = segSwitch(n, i);
      let st;
      if (plug && linked) st = "插件 ← " + nodeLabel(segPlugin(n, i) || sw);
      else if (plug) st = "插件：未连线（点 ⌖ 去连）";
      else if (linked) st = "手填（插件已关）";
      else st = txt.trim() ? "手填" : "空";
      if (row.state.textContent !== st) row.state.textContent = st;
      if (sw) row.go.title = "跳到「" + nodeLabel(sw) + "」——把插件输出连到它的插件文本口";
      else row.go.title = "这一段还没接上开关节点";
    }
    let lt = "";
    if (vis >= SEG_MAX) {
      lt = lastUsed >= SEG_MAX
        ? "8 段都用上了——要更多就在画布上再接一个拼接节点"
        : "已展开到 8 段上限（再加段要在画布上串一个拼接节点）";
    } else if (vis > SEG_SHOWN_MIN) {
      lt = "已自动展开到 " + vis + " 段";
    }
    if (g.limit.textContent !== lt) g.limit.textContent = lt;
  }
}

/** 种子「🎲 随机」开关：默认开，不跨刷新记忆（apply=true 时写回画布） */
function syncSeedChks(apply) {
  for (const [k, box] of Object.entries(ui.seedChks || {})) {
    const want = !!SEED_RANDOM[seedKindOf(k)];
    if (box.checked !== want) box.checked = want;
    if (apply) writeSeedRandom(k, want);
  }
}

/** 脸 / 手 / 眼 / SAM 四个勾：状态以画布（子图内部节点的 mode）为准 */
function syncStageChks() {
  for (const [k, box] of Object.entries(ui.stageChks || {})) {
    const want = detailerToggleOn(k);
    if (box.checked !== want) box.checked = want;
  }
}

/** 参数值超出安全区时在那一行下面提示（脸手眼那五个旋钮） */
function syncParamWarns() {
  for (const [k, span] of Object.entries(ui.warnSpans || {})) {
    const rule = PARAM_WARN[k];
    if (!rule || !span) continue;
    const n = findNode("param", k);
    const v = n ? Number(readValue(n, "param")) : NaN;
    const txt = (isFinite(v) && v >= rule[0]) ? "⚠ " + rule[1] : "";
    if (span.textContent !== txt) span.textContent = txt;
    if (span.parentNode) span.parentNode.classList.toggle("ccd-hot", !!txt);
  }
}

/** 一行 LoRA 的状态文案：未启用 / 模型族不匹配 / 触发词 */
function loraStatusOf(row, model) {
  const name = row.lora || "";
  if (!name) return null;
  const warns = [];
  if (!row.on) {
    warns.push("⚠ 已选但未启用（后端会跳过它，勾上左边的框）");
  }
  const loraIsAnima = isAnimaModel(name);
  const modelIsAnima = isAnimaModel(model);
  const loraLooksSdxl = /illustrious|sdxl|(^|[^a-z])il([^a-z]|$)/i.test(name);
  if ((loraIsAnima && !modelIsAnima) ||
    (modelIsAnima && !loraIsAnima && loraLooksSdxl)) {
    warns.push("⚠ 与当前模型族可能不匹配（这条看着是 "
      + (loraIsAnima ? "ANIMA" : "SDXL") + " 系）");
  }
  const words = triggerWordsOf(name);
  let trig;
  if (words.length) {
    trig = "触发词: " + words.slice(0, 3).join(" / ") + (words.length > 3 ? " …" : "");
  } else if (LORA_TRIGGERS &&
    Object.prototype.hasOwnProperty.call(LORA_TRIGGERS, name)) {
    trig = "触发词: 没读到（这条 LoRA 没写训练词）";
  } else {
    trig = "触发词: 读取中…";
  }
  return {
    text: warns.concat([trig]).join("　·　"),
    warn: warns.length > 0,
    tip: words.length ? "触发词：" + words.join(", ") : "",
  };
}

/** 写失败时的提示：同步会顶掉状态行，所以按 组:行 记一下，写成功再清掉 */
function flagLoraWarn(group, idx, msg) {
  if (!ui.loraWarn) ui.loraWarn = {};
  ui.loraWarn[group + ":" + idx] = msg;
}
function clearLoraWarn(group, idx) {
  if (ui.loraWarn) delete ui.loraWarn[group + ":" + idx];
}
function loraWarnOf(group, idx) {
  return (ui.loraWarn && ui.loraWarn[group + ":" + idx]) || "";
}

function buildLoraRow(group, idx, row) {
  // 这里不再抓住某个节点对象（见 writeLoraRow 的注释）：每次写入都按 role/key 重查画布
  const put = (patch) => {
    const okNow = writeLoraRow(group, idx, patch);
    if (okNow) clearLoraWarn(group, idx);
    else flagLoraWarn(group, idx, "⚠ 没能写回画布：面板已重绑，请再点一次");
    sync(true);
    return okNow;
  };
  const on = el("input", { type: "checkbox" });
  on.checked = !!row.on;
  on.addEventListener("change", () => {
    put({ on: on.checked });
  });
  const names = [""].concat(loraList());
  const pick = sel(names, row.lora || "", (v) => {
    // 先算清楚「这次要写成什么」，再同步勾选框、一次性写回画布：
    // 之前是先写 on（读的是改之前的勾选状态）再改勾选框，所以新选的行会被写成 on:false，
    // 后端 if value['on'] 直接跳过 —— 这就是「选了 LoRA 却不生效」的根因。
    const nextOn = !!v && (on.checked || !row.lora);
    on.checked = nextOn;
    put({ lora: v, on: nextOn });
  });
  const s = num(typeof row.strength === "number" ? row.strength : 1, 0.05,
    (v) => {
      if (!isNaN(v)) put({ strength: v });
      else sync(true);
    });
  const status = el("div", { class: "ccd-lora-status" });
  const view = {
    box: el("div", { class: "ccd-lora-row" }, [on, pick, s, status]),
    on, pick, s, status,
  };
  view.sync = (next) => {
    const warn = loraWarnOf(group, idx);
    const info = warn ? null : loraStatusOf(next, currentModel());
    const text = warn || (info ? info.text : "");
    if (status.textContent !== text) status.textContent = text;
    status.classList.toggle("ccd-warn", !!(warn || (info && info.warn)));
    const tip = warn || (info ? (info.tip || info.text) : "");
    if (status.title !== tip) status.title = tip;
    if (next && next.lora && next.on && !triggerWordsOf(next.lora).length) {
      fetchTriggerFor(next.lora);
    }
  };
  return view;
}

function syncLoras() {
  for (const [gk] of LORA_GROUPS) {
    const node = findNode("lora_group", gk);
    const box = ui.loraCols[gk];
    if (!box) continue;
    if (!node) {
      if (ui.lastLoraCount[gk] !== 0) {
        box.textContent = "";
        box.appendChild(el("p", { class: "ccd-hint", text: "没找到该 LoRA 组节点" }));
        ui.lastLoraCount[gk] = 0;
      }
      continue;
    }
    const rows = readLora(node);
    // 重开工作流时节点会被换成新对象、行数却可能一样，所以连「绑的是哪个节点」一起比
    if (!ui.loraNode) ui.loraNode = {};
    if (ui.loraNode[gk] !== node ||
      ui.lastLoraCount[gk] !== rows.length ||
      box.childElementCount !== rows.length) {
      box.textContent = "";
      const views = rows.map((row, i) => {
        const v = buildLoraRow(gk, i, row);
        box.appendChild(v.box);
        return v;
      });
      if (!ui.loraViews) ui.loraViews = {};
      ui.loraViews[gk] = views;
      ui.loraNode[gk] = node;
      ui.lastLoraCount[gk] = rows.length;
    }
    const views = (ui.loraViews && ui.loraViews[gk]) || [];
    rows.forEach((row, i) => {
      const v = views[i];
      if (!v) return;
      if (!focused(v.on) && v.on.checked !== !!row.on) v.on.checked = !!row.on;
      if (!focused(v.pick) && v.pick.value !== (row.lora || "")) {
        v.pick.value = row.lora || "";
      }
      const sv = typeof row.strength === "number" ? row.strength : 1;
      if (!focused(v.s) && String(v.s.value) !== String(sv)) v.s.value = sv;
      if (v.sync) v.sync(row);
    });
  }
}

// ------------------------------------------------- 缺插件自检 + 蓝图生成
/** 画布上用到的、本机没注册的节点类型（分享给别人时最常踩的坑） */
function missingNodeTypes() {
  const reg = (typeof LiteGraph !== "undefined" && LiteGraph
    && LiteGraph.registered_node_types) || null;
  const types = new Set();
  eachGraph((n) => {
    if (!n || !n.type) return;
    const t = String(n.type);
    if (t === "MarkdownNote" || t === "Note") return;    // 前端虚拟节点
    if (/^[0-9a-f]{8}-[0-9a-f]{4}-/i.test(t)) return;    // 子图实例，不在注册表里
    types.add(t);
  });
  const missing = [];
  if (reg) {
    for (const t of types) {
      if (!reg[t]) missing.push(t);
    }
  }
  return missing.sort();
}

/** 顶部黄条：缺哪个插件包就写在这儿，点一下复制清单 */
function syncMissing() {
  if (!ui.warn) return;
  const missing = missingNodeTypes();
  if (!missing.length) {
    ui.warn.classList.add("ccd-hide");
    ui.warn.textContent = "";
    return;
  }
  ui.warn.classList.remove("ccd-hide");
  ui.warn.textContent = "⚠ 缺少 " + missing.length + " 种插件节点："
    + missing.join("、") + "　（点这条复制清单 → Manager 里 Install Missing Custom Nodes）";
  ui.warn.title = "这些节点类型当前 ComfyUI 没注册，多半是没装对应插件包：\n"
    + missing.join("\n") + "\n\n哪个节点属于哪个插件包，见 cc_dashboard/README.md。";
}

// ------------------------------------------------- 画布是不是还在跑旧蓝图
/** 画布上「高清化」子图的节点类型清单（按子图名字认；两个实例共用一个定义） */
function upscaleSubgraphTypes() {
  const out = [];
  eachGraph((n) => {
    const sg = n && n.subgraph;
    if (!sg || !sg.nodes) return;
    const nm = String(sg.name || n.title || "");
    if (!/高清/.test(nm)) return;
    for (const x of sg.nodes) {
      const t = String((x && x.type) || "");
      if (t && out.indexOf(t) < 0) out.push(t);
    }
  });
  return out;
}

/** 工作流 extra 里的蓝图版本戳（读不到就返回 null，不当成「旧」） */
function blueprintRev() {
  try {
    const e = app.graph && app.graph.extra;
    const b = e && e.cc_dashboard_blueprint;
    const v = b && Number(b.rev);
    return isFinite(v) ? v : null;
  } catch (e) {
    return null;
  }
}

/** 画布上这份蓝图和当前生成器差在哪（只报看得懂的差异，认不出来就当没事） */
function blueprintDrift() {
  const reasons = [];
  let legacy = false;
  const types = upscaleSubgraphTypes();
  if (types.length) {
    const extra = [];
    if (types.indexOf("ImageUpscaleWithModel") >= 0) {
      extra.push("收尾又跑了一趟 4x 放大");
      legacy = true;
    }
    if (types.indexOf("ImageScaleBy") >= 0) {
      extra.push("紧接着缩回 ×0.5");
      legacy = true;
    }
    if (legacy) {
      reasons.push("高清链多绕一段（" + extra.join(" + ")
        + "）：实际倍率 = 面板倍数 × 2，填 2 出来是 4 倍");
    }
    const missing = UPSCALE_CHAIN_NODES.filter((t) => types.indexOf(t) < 0);
    if (missing.length) reasons.push("高清链缺节点：" + missing.join("、"));
  }
  const rev = blueprintRev();
  if (rev !== null && rev < BLUEPRINT_REV) {
    reasons.push("蓝图版本 " + rev + "，当前是 " + BLUEPRINT_REV);
  }
  return { stale: reasons.length > 0, reasons, legacy, rev };
}

/** 橙色条：画布还是旧蓝图时提醒（右边按钮按画布现况重生成并载入） */
function syncDrift() {
  const info = blueprintDrift();
  const changed = !ui.driftInfo || ui.driftInfo.stale !== info.stale
    || ui.driftInfo.legacy !== info.legacy;
  ui.driftInfo = info;
  if (!ui.drift) return;
  if (!info.stale) {
    ui.drift.classList.add("ccd-hide");
  } else {
    ui.drift.classList.remove("ccd-hide");
    const txt = ui.drift.querySelector(".ccd-drift-txt");
    if (txt) {
      txt.textContent = "⚠ 画布上是旧版蓝图：" + info.reasons.join("；")
        + "　→ 点右边按画布现况重建（提示词 / LoRA / 参数都会结转）";
    }
    ui.drift.title = "面板只是遥控器，改的是画布上那份图，画布本身不会自己升级。\n"
      + info.reasons.join("\n")
      + "\n\n点「载入最新蓝图」= 用你现在画布上的提示词 / LoRA / 参数做结转，"
      + "节点结构换成当前版本，然后直接载进画布。";
  }
  // 只读的「输出尺寸」要跟着换口径
  if (changed) {
    try { updateRoFields(); } catch (e) { log("updateRoFields", e); }
  }
}

/** 旧蓝图一键修复：生成 + 载入（生成前先把画布现况发给插件做结转） */
async function fixStaleBlueprint() {
  const btn = ui.drift && ui.drift.querySelector(".ccd-drift-fix");
  const txt = ui.drift && ui.drift.querySelector(".ccd-drift-txt");
  if (btn) btn.disabled = true;
  if (txt) txt.textContent = "正在按画布现况重建蓝图…";
  try {
    await makeBlueprint("update");
  } finally {
    if (btn) btn.disabled = false;
    try { syncDrift(); } catch (e) { log("syncDrift", e); }
  }
}

/** 「说明」页：生成 / 更新蓝图（走插件的本地接口） */
/** 把画布现况序列化出来交给插件做参数结转（拿不到就算了，插件会退回读磁盘） */
function canvasPayload() {
  try {
    const g = app.graph;
    if (g && typeof g.serialize === "function") return g.serialize();
  } catch (e) {
    log("serialize", e);
  }
  return null;
}

async function makeBlueprint(mode) {
  const say = (t) => {
    if (ui.toolStatus) ui.toolStatus.textContent = t;
  };
  say("正在生成蓝图…");
  const body = { mode: mode === "fresh" ? "fresh" : "update" };
  if (body.mode === "update") body.canvas = canvasPayload();
  let payload;
  try {
    payload = JSON.stringify(body);
  } catch (e) {
    // 画布现况序列化失败（比如出现环）也不能挡住重建：退回让插件读磁盘那份
    log("blueprint payload", e);
    delete body.canvas;
    payload = JSON.stringify(body);
  }
  try {
    const res = await fetch(API_BASE + "/blueprint", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload,
    });
    const data = await res.json();
    if (!data || !data.ok) {
      throw new Error((data && data.error) || ("HTTP " + res.status));
    }
    const rep = data.report || {};
    const from = data.carried_from === "canvas" ? "按画布现况结转"
      : (data.carried_from === "file" ? "按磁盘那份结转" : "用默认值");
    say("✅ 已生成 " + (rep.nodes || 0) + " 节点 / " + (rep.links || 0) + " 连线"
      + "（" + from + " " + (rep.carried || 0) + " 项）"
      + (data.backup ? "；旧版已备份" : ""));
    loadBlueprint(data.workflow);
  } catch (e) {
    say("⚠ 生成失败：" + ((e && e.message) || e)
      + "。也可命令行跑 python tools/gen_dashboard.py");
  }
}

/** 生成完直接把新蓝图载进画布；老前端不认就地提示从列表打开 */
function loadBlueprint(wf) {
  if (!wf) return;
  const hint = () => {
    if (ui.toolStatus) {
      ui.toolStatus.textContent += "　→ 已写进工作流列表，打开 00_总控台 即可";
    }
  };
  try {
    const load = app.loadGraphData;
    if (typeof load !== "function") { hint(); return; }
    const p = load.call(app, wf);
    if (p && typeof p.catch === "function") p.catch(hint);
  } catch (e) {
    hint();
  }
}

/**
 * 画布节点被整体换成新对象时（从列表重开工作流 / 一键重建蓝图后载入），
 * 面板里所有「建 DOM 时抓住节点」的行都要重新绑一次 —— 面板按节点身份探针判断。
 */
function rebindIfGraphChanged() {
  let probe = null;
  try {
    probe = findNode("model_slot") || findNode("save") || findNodes("lora_group")[0] || null;
  } catch (e) { return false; }
  if (!probe) return false;
  const changed = !!ui.probeNode && ui.probeNode !== probe;
  ui.probeNode = probe;
  return changed;
}

function sync(force) {
  if (!ui.root) return;
  if (!hasMarkers()) {
    ui.root.style.display = "none";
    ui.bound = false;
    return;
  }
  ui.root.style.display = "";
  applyGeom();
  if (ui.focusBtn) ui.focusBtn.classList.toggle("ccd-on", !!ui.st.focus);
  if (ui.dockBtn) ui.dockBtn.classList.toggle("ccd-on", !!ui.st.docked);
  if (ui.pipBtn) ui.pipBtn.classList.toggle("ccd-on", inPiP());
  // 上次在面板上调好的参数写回画布（每次载入只做一次，之后以画布为准）
  try { applyStoredParams(); } catch (e) { log("applyStoredParams", e); }

  const ml = modelList();
  const sig = ml.join("\u0001");
  if (force || sig !== ui.lastModelList) {
    ui.lastModelList = sig;
    const cur = currentModel();
    ui.modelSel.textContent = "";
    for (const v of ml) {
      ui.modelSel.appendChild(el("option", { value: v, text: v }));
    }
    if (cur && ml.indexOf(cur) < 0) {
      ui.modelSel.appendChild(el("option", { value: cur, text: cur }));
    }
    if (cur) ui.modelSel.value = cur;
    // 模型列表换了 → 分辨率下拉的「★ 推荐」那一项跟着换
    try { refreshCombos(true); } catch (e) { log("refreshCombos", e); }
  } else {
    const cur = currentModel();
    if (cur && !focused(ui.modelSel) && ui.modelSel.value !== cur) {
      ui.modelSel.value = cur;
    }
  }

  const active = findNodes("save").filter((n) => n.mode === 0).map(keyOf);
  for (const [k, b] of Object.entries(ui.pipeBtns)) {
    b.classList.toggle("ccd-on", active.indexOf(k) >= 0);
  }
  // 顶栏管线 → 下面只留这条管线要用的东西
  const pipeNow = active[0] || ui.st.pipe || "t2i";
  if (force || pipeNow !== ui.lastPipe) {
    ui.st.pipe = pipeNow;
    applyPipeFilter();
  }
  for (const [k, b] of Object.entries(ui.modBtns)) {
    let on;
    if (k === "pose") {
      on = findNodes("module", "pose_sdxl").concat(
        findNodes("module", "pose_anima")).some((n) => n.mode === 0);
    } else {
      on = findNodes("module", k).some((n) => n.mode === 0);
    }
    b.classList.toggle("ccd-on", on);
    if (ui.st.modules[k] !== on && !force) ui.st.modules[k] = on;
  }
  syncSegs();
  syncLoras();
  syncParams();
  syncSeedChks(false);
  syncStageChks();
  syncParamWarns();
  // 分块大小跟分辨率走：画布上改了宽高 / 倍数，这里立刻把分块和只读提示刷成一致的
  applyTileAuto(true);
  if (ui.tileChks && ui.tileChks.auto && ui.tileChks.auto.checked !== !!TILE_AUTO.on) {
    ui.tileChks.auto.checked = !!TILE_AUTO.on;
  }
  applyParamSections();
  // 缺插件黄条：分享给别人后最常见的坑，缺什么直接写在顶上
  try {
    syncMissing();
  } catch (e) { log("syncMissing", e); }
  // 旧蓝图橙条：面板说的倍数和画布真跑的倍数对不上时，必须让人看见
  try {
    syncDrift();
  } catch (e) { log("syncDrift", e); }
}

function render() {
  ui.lastModelList = "";
  ui.lastLoraCount = {};
  ui.loraViews = {};
  ui.loraNode = {};
  ui.loraWarn = {};
  ui.probeNode = null;
  ui.lastPipe = "";
  auditOnce();
  // 打开工作流时先对齐一次 CLIP / VAE 来源，避免选了 ANIMA 还挂着 ckpt 那份
  try {
    applyFamilySwitch(isAnimaModel(currentModel()));
  } catch (e) { log("applyFamilySwitch", e); }
  // 种子「🎲 随机」默认开：每次打开页面把画布上的控制项也设成 randomize
  try {
    syncSeedChks(true);
  } catch (e) { log("syncSeedChks", e); }
  sync(true);
}

// 角色自检：工作流里少了某个标记只提示一次，不影响出图
let audited = false;

function auditOnce() {
  if (audited) return;
  audited = true;
  for (const [r, keys] of Object.entries(HANDLED)) {
    if (keys.indexOf(null) >= 0 && findNodes(r).length === 0) {
      log("工作流缺少 role=" + r + " 的节点");
    }
    for (const k of keys) {
      if (k !== null && findNodes(r, k).length === 0) {
        log("工作流缺少 role=" + r + " key=" + k + " 的节点");
      }
    }
  }
}

// ------------------------------------------------------------ 注册扩展
app.registerExtension({
  name: "cc_dock.panel",
  async setup() {
    try {
      build();
    } catch (e) {
      log("面板构建失败（不影响出图）", e);
      return;
    }
    const tick = () => {
      try {
        sync();
      } catch (e) {
        log("sync", e);
      }
    };
    // 首次 + 工作流切换后都会自动认领（按 properties 标记，不看文件名）
    let lastGraph = null;
    setInterval(() => {
      try {
        const g = app.graph;
        if (g !== lastGraph) {
          lastGraph = g;
          render();
          return;
        }
        // 图还是同一个对象、节点却被换掉了（重开工作流）：行绑定也得重建
        if (rebindIfGraphChanged()) {
          render();
          return;
        }
      } catch (e) { /* ignore */ }
      tick();
      // 队列那一排的数字：同一轮回调里顺手刷一次（内部有 0.9s 节流）
      try {
        refreshQueue();
      } catch (e) { /* ignore */ }
    }, 1200);
    window.addEventListener("resize", () => {
      try {
        sync(true);
      } catch (e) { /* ignore */ }
    });
    // 用户正在画布上操作时，跟随执行先让一让
    for (const ev of ["pointerdown", "wheel"]) {
      document.addEventListener(ev, (e) => {
        try {
          const t = e.target;
          if (t && t.closest && t.closest("#graph-canvas, .graph-canvas-container")) {
            markCanvasTouch();
          }
        } catch (err) { /* ignore */ }
      }, true);
    }
    try {
      const api = (await import("../../scripts/api.js")).api;
      ui.api = api;   // 队列那一排要用它取状态 / 中断
      // 队列一动就刷数字：不用等 1.2s 轮询
      api.addEventListener("status", () => {
        try {
          refreshQueue(true);
        } catch (e) { /* ignore */ }
      });
      api.addEventListener("graphConfigured", () => {
        ui.lastImage = null;
        ui.paramApplied = false;   // 换工作流 / 重载：下次同步把记住的参数再写一遍
        setTimeout(render, 80);
      });
      api.addEventListener("graphCleared", () => {
        ui.lastImage = null;
        ui.paramApplied = false;
        setTimeout(render, 80);
      });
      // Save 一跑完就记下这张图：不用等下拉开刷新，同步立刻生效（以前那点延迟就在这）
      api.addEventListener("executed", (e) => {
        try {
          const d = (e && e.detail) || {};
          const imgs = d.output && d.output.images;
          if (!Array.isArray(imgs) || !imgs.length) return;
          const key = savePipeOf(d.display_node || d.node);
          if (!key) return;
          const v = outputImageValue(imgs[imgs.length - 1]);
          // SaveVideo 报回来的也是 images，里面是 mp4 —— 只认图片
          if (!v || !isImageValue(v)) return;
          ui.lastImage = v;
          if (key === activePipe()) syncOutputImageSoon();
        } catch (err) { log("executed", err); }
      });
      // 队列从「有任务」变成「跑完」时，立刻刷一遍取图列表并把输出图传下去
      api.addEventListener("status", (e) => {
        try {
          const d = (e && e.detail) || {};
          const info = (d.status && d.status.exec_info) || null;
          if (!info) return;
          if ((info.queue_remaining || 0) > 0) {
            ui.runPending = true;
            return;
          }
          if (!ui.runPending) return;
          ui.runPending = false;
          refreshImageCombos();
        } catch (err) { log("status", err); }
      });
      // 跟随执行：detail 是执行 id（子图内节点形如 "13:5"）
      api.addEventListener("executing", (e) => {
        try {
          const p = focusExec(e && e.detail);
          if (p && typeof p.catch === "function") p.catch(() => { /* ignore */ });
        } catch (err) { log("executing", err); }
      });
    } catch (e) {
      log("api 事件不可用，使用轮询兜底", e);
    }
    render();
    try {
      refreshQueue(true);
    } catch (e) { /* ignore */ }
    // 打开工作流时先把输出图按管线关系对一遍（幂等，没变就不动）
    try {
      setTimeout(() => { try { applyOutputImage(); } catch (e) { /* ignore */ } },
        600);
    } catch (e) { /* ignore */ }
    // 上次停在独立窗口：弹出需要用户手势，这里只提示，点 ⧉ 即可恢复
    if (ui.st && ui.st.pip && pipAvailable()) {
      try {
        ui.pipBtn.title = "上次是独立窗口，点一下恢复（浏览器要求点击才能弹出）";
      } catch (e) { /* ignore */ }
    }
  },
});
