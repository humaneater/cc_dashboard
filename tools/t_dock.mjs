/**
 * t_dock.mjs —— cc_dashboard 浮动面板的离线冒烟测试
 *
 * 不起 ComfyUI 服务、不联网：用一套极简 DOM 桩把 dock.js 跑起来，
 * 覆盖「浮动窗拖动/缩放」「独立窗口弹出收回」「跟随执行聚焦」以及原有面板联动。
 *
 * 运行： node tools/t_dock.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DOCK_JS = path.join(HERE, "..", "web", "dock.js");
const TMP_DIR = path.join(HERE, "_t_dock");
const UNDER_TEST = path.join(TMP_DIR, "_under_test.mjs");
// 两个 import 桩随插件一起分发，测试时拷进临时目录
const FIXTURES = ["shim_app.mjs", "shim_api.mjs"];
function installFixtures() {
  fs.mkdirSync(TMP_DIR, { recursive: true });
  for (const f of FIXTURES) {
    fs.copyFileSync(path.join(HERE, "fixtures", f), path.join(TMP_DIR, f));
  }
}

// ----------------------------------------------------------------- DOM 桩
function matches(el, selector) {
  if (!el || el.tagName === "#TEXT") return false;
  return String(selector).split(",").some((part) => {
    const s = part.trim();
    if (!s) return false;
    let ok = true;
    const id = /#([\w-]+)/.exec(s);
    if (id) ok = ok && el.attrs.id === id[1];
    const cls = /\.([\w-]+)/.exec(s);
    if (cls) ok = ok && el._class.has(cls[1]);
    const attr = /\[([\w-]+)\]/.exec(s);
    if (attr) ok = ok && Object.prototype.hasOwnProperty.call(el.attrs, attr[1]);
    const tag = /^[a-zA-Z][\w-]*/.exec(s);
    if (tag && ok) ok = el.tagName === tag[0].toUpperCase();
    return ok;
  });
}

function walk(root, fn) {
  for (const c of root.children || []) {
    fn(c);
    walk(c, fn);
  }
}

class El {
  constructor(tag, doc) {
    this.tagName = String(tag).toUpperCase();
    this.ownerDocument = doc;
    this.children = [];
    this.parentNode = null;
    this.attrs = {};
    this.style = {};
    this.listeners = {};
    this._class = new Set();
    this._text = "";
    this.value = "";
    this.checked = false;
    const self = this;
    this.classList = {
      add: (...cs) => cs.forEach((c) => self._class.add(c)),
      remove: (...cs) => cs.forEach((c) => self._class.delete(c)),
      contains: (c) => self._class.has(c),
      toggle: (c, force) => {
        const on = force === undefined ? !self._class.has(c) : !!force;
        if (on) self._class.add(c); else self._class.delete(c);
        return on;
      },
    };
  }
  get className() { return [...this._class].join(" "); }
  set className(v) { this._class = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get textContent() { return this._text; }
  set textContent(v) { this._text = String(v); this.children = []; }
  set innerHTML(v) { this._text = String(v); this.children = []; }
  get childElementCount() { return this.children.length; }
  appendChild(c) {
    if (c.parentNode) c.parentNode.removeChild(c);
    c.parentNode = this;
    adopt(c, this.ownerDocument);
    this.children.push(c);
    return c;
  }
  removeChild(c) {
    this.children = this.children.filter((x) => x !== c);
    c.parentNode = null;
    return c;
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; }
  querySelector(sel) { let hit = null; walk(this, (n) => { if (!hit && matches(n, sel)) hit = n; }); return hit; }
  querySelectorAll(sel) { const out = []; walk(this, (n) => { if (matches(n, sel)) out.push(n); }); return out; }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  removeEventListener(t, f) {
    if (this.listeners[t]) this.listeners[t] = this.listeners[t].filter((x) => x !== f);
  }
  dispatch(type, ev) {
    const e = Object.assign({ type, target: this, preventDefault() {}, stopPropagation() {} }, ev || {});
    for (const f of (this.listeners[type] || []).slice()) f(e);
    return e;
  }
  getBoundingClientRect() {
    const num = (v, d) => { const x = parseFloat(v); return Number.isNaN(x) ? d : x; };
    const x = num(this.style.left, 0);
    const y = num(this.style.top, 0);
    const w = num(this.style.width, 768);
    const h = num(this.style.height, 576);
    return { left: x, top: y, width: w, height: h, right: x + w, bottom: y + h, x, y };
  }
  closest(sel) {
    let n = this;
    while (n) {
      if (matches(n, sel)) return n;
      n = n.parentNode;
    }
    return null;
  }
  focus() { this.ownerDocument.activeElement = this; }
  blur() {
    if (this.ownerDocument.activeElement === this) this.ownerDocument.activeElement = null;
  }
}

function adopt(node, doc) {
  node.ownerDocument = doc;
  for (const c of node.children || []) adopt(c, doc);
}

class Doc {
  constructor() {
    this.head = new El("head", this);
    this.body = new El("body", this);
    this.documentElement = new El("html", this);
    this.documentElement.appendChild(this.head);
    this.documentElement.appendChild(this.body);
    this.listeners = {};
    this.activeElement = null;
  }
  createElement(t) { return new El(t, this); }
  createTextNode(s) { const e = new El("#text", this); e.textContent = s; return e; }
  getElementById(id) {
    if (this.documentElement.attrs.id === id) return this.documentElement;
    let hit = null;
    walk(this.documentElement, (n) => { if (!hit && n.attrs.id === id) hit = n; });
    return hit;
  }
  querySelector(sel) {
    if (matches(this.documentElement, sel)) return this.documentElement;
    let hit = null;
    walk(this.documentElement, (n) => { if (!hit && matches(n, sel)) hit = n; });
    return hit;
  }
  querySelectorAll(sel) { return this.documentElement.querySelectorAll(sel); }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  removeEventListener(t, f) {
    if (this.listeners[t]) this.listeners[t] = this.listeners[t].filter((x) => x !== f);
  }
  dispatch(type, ev) {
    const e = Object.assign({ type, preventDefault() {}, stopPropagation() {} }, ev || {});
    for (const f of (this.listeners[type] || []).slice()) f(e);
    return e;
  }
}

function makeWindow(doc) {
  const win = {
    document: doc,
    innerWidth: 1600,
    innerHeight: 900,
    devicePixelRatio: 1,
    listeners: {},
    closed: false,
    addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); },
    removeEventListener(t, f) {
      if (this.listeners[t]) this.listeners[t] = this.listeners[t].filter((x) => x !== f);
    },
    dispatch(type, ev) {
      const e = Object.assign({ type }, ev || {});
      for (const f of (this.listeners[type] || []).slice()) f(e);
      return e;
    },
    requestAnimationFrame(fn) { return setTimeout(() => fn(Date.now()), 0); },
    cancelAnimationFrame(id) { clearTimeout(id); },
    close() { this.closed = true; },
  };
  doc.defaultView = win;
  return win;
}

const mainDoc = new Doc();
const mainWin = makeWindow(mainDoc);
const store = new Map();

globalThis.window = mainWin;
globalThis.document = mainDoc;
globalThis.getComputedStyle = () => ({ getPropertyValue: () => "" });
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
};
globalThis.requestAnimationFrame = mainWin.requestAnimationFrame.bind(mainWin);
globalThis.fetch = async () => ({ json: async () => ({}) });

let pipWindows = [];
mainWin.documentPictureInPicture = {
  requestWindow: async () => {
    const doc = new Doc();
    const win = makeWindow(doc);
    pipWindows.push(win);
    return win;
  },
};

// ------------------------------------------------------------ 假 ComfyUI 图
function widget(name, value, extra) {
  return Object.assign({ name, value }, extra || {});
}

function mkNode(id, type, opts) {
  const o = opts || {};
  const n = {
    id: String(id),
    type,
    mode: o.mode || 0,
    properties: o.properties || {},
    widgets: o.widgets || [],
    pos: o.pos || [0, 0],
    size: o.size || [200, 100],
    graph: o.graph || null,
    setDirtyCanvas() {},
  };
  n.boundingRect = [n.pos[0], n.pos[1], n.size[0], n.size[1]];
  return n;
}

function mark(role, key, node) {
  node.properties.cc_dock_role = role;
  if (key) node.properties.cc_dock_key = key;
  return node;
}

function paramNode(key, value) {
  const ws = [widget("value", value)];
  if (key === "seed" || key === "video_seed") {
    ws.push(widget("control_after_generate", "randomize"));
  }
  return mark("param", key, mkNode("p_" + key, "PrimitiveInt", { widgets: ws }));
}

/** YogurtStringConcat 风格的 8 段提示词节点（段文本只做镜像，真文本在开关节点上） */
function promptNode(key, value) {
  // 负面提示词在 v6.2 起是单框：PrimitiveStringMultiline，一个 value widget
  if (key === "image_neg" || key === "video_neg") {
    return mark("prompt", key, mkNode("t_" + key, "PrimitiveStringMultiline",
      { widgets: [widget("value", value)] }));
  }
  const ws = [widget("separator", ", ")];
  for (let i = 1; i <= 8; i++) {
    ws.push(widget("enable" + i, true));
    ws.push(widget("text" + i, ""));
  }
  const n = mark("prompt", key, mkNode("t_" + key, "YogurtStringConcat", { widgets: ws }));
  n.inputs = [];
  for (let i = 1; i <= 8; i++) n.inputs.push({ name: "text" + i, link: null });
  return n;
}

/** CR Text Input Switch JK：boolean_value / text_false（手填）/ text_true（插件口） */
function segSwitchNode(id, hand, pos) {
  const n = mkNode(id, "CR Text Input Switch JK", {
    widgets: [widget("boolean_value", false), widget("text_false", hand),
      widget("text_true", hand)],
    pos: pos || [0, 0], size: [340, 82],
  });
  n.inputs = [{ name: "text_true", link: null }];
  n.outputs = [{ name: "STRING", links: [] }, { name: "BOOLEAN", links: [] }];
  return n;
}

function loraNode(key, rows) {
  const ws = rows.map((r) => widget("lora_" + r.i, { on: !!r.on, lora: r.lora || "", strength: r.strength || 1 }));
  return mark("lora_group", key, mkNode("l_" + key, "Power Lora Loader (rgthree)", { widgets: ws }));
}

const MODELS = ["waiIllustriousSDXL_v170.safetensors", "oneObsession_anima29BV1.safetensors"];
const UNETS = [
  "openkolorsUnet_v13.safetensors",
  "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
  "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
  "wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors",
  "wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors",
];
// 外挂资源槽的文件清单（v1.9.0）
const TE_FILES = [
  "qwen_3_06b_base.safetensors",
  "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
];
const VAE_FILES = [
  "wan_2.1_vae.safetensors",
  "qwen_image_vae.safetensors",
  "sdxlVAE_sdxlVAE.safetensors",
];

function buildGraph() {
  const nodes = [];
  nodes.push(mark("model_slot", null, mkNode(101, "CheckpointLoaderSimple",
    { widgets: [widget("ckpt_name", MODELS[0], { options: { values: MODELS.slice() } })] })));
  // 视频模型（v1.5.0）：high / low 两个 UNETLoader，各自带下拉清单
  for (const [k, cur] of [["video_high", UNETS[1]], ["video_low", UNETS[2]]]) {
    nodes.push(mark("unet_slot", k, mkNode("u_" + k, "UNETLoader", {
      widgets: [
        widget("unet_name", cur, { options: { values: UNETS.slice() } }),
        widget("weight_dtype", "default"),
      ],
    })));
  }
  nodes.push(mark("preset_sdxl", null, mkNode(102, "CLIPSetLastLayer", { mode: 0 })));
  // 外挂资源槽（v1.9.0）：图像侧 110 / 111，视频侧 403 / 412
  nodes.push(mark("te_slot", "image", mkNode("te_img", "CLIPLoader", {
    widgets: [
      widget("clip_name", TE_FILES[0], { options: { values: TE_FILES.slice() } }),
      widget("type", "stable_diffusion"), widget("device", "default"),
    ],
  })));
  nodes.push(mark("vae_slot", "image", mkNode("vae_img", "VAELoader", {
    widgets: [
      widget("vae_name", VAE_FILES[0], { options: { values: VAE_FILES.slice() } }),
    ],
  })));
  nodes.push(mark("te_slot", "video", mkNode("te_vid", "CLIPLoader", {
    widgets: [
      widget("clip_name", TE_FILES[1], { options: { values: TE_FILES.slice() } }),
      widget("type", "wan"), widget("device", "default"),
    ],
  })));
  nodes.push(mark("vae_slot", "video", mkNode("vae_vid", "VAELoader", {
    widgets: [
      widget("vae_name", VAE_FILES[0], { options: { values: VAE_FILES.slice() } }),
    ],
  })));
  for (const [i, k] of ["image_pos", "image_neg", "video_pos", "video_neg"].entries()) {
    nodes.push(mark("clip_encode", k, mkNode(110 + i, "CLIPTextEncode")));
    nodes.push(promptNode(k, "hello " + k));
  }
  for (const [k, v] of [["width", 1216], ["height", 832], ["steps", 28], ["cfg", 5.5],
    ["seed", 1], ["denoise", 0.5], ["pose_strength", 0.8], ["upscale_factor", 2],
    ["upscale_denoise", 0.2], ["upscale_whole_denoise", 0.2],
    ["upscale_seam_fix", 0.3], ["video_width", 832], ["video_height", 480],
    ["video_length", 81], ["video_fps", 16], ["video_steps", 4], ["video_cfg", 1],
    ["video_seed", 2], ["detailer_threshold", 0.5],
    ["detailer_threshold_eye", 0.65], ["detailer_feather", 5],
    ["detailer_denoise_face", 0.4], ["detailer_denoise_hand", 0.5],
    ["detailer_denoise_eye", 0.5], ["upscale_tile", 1216],
    ["detailer_guide", 512], ["detailer_max_size", 1024],
    ["detailer_crop", 2.5],
    // 视频后处理（v1.4.0）：补帧倍数 / 视频高清目标倍数 / 放大模型倍率 / 分批 / 分块
    ["vfi_multiplier", 2], ["video_upscale_factor", 2],
    ["video_upscale_base", 4], ["video_upscale_batch", 4],
    ["video_upscale_tile", 0]]) {
    nodes.push(paramNode(k, v));
  }
  nodes.push(loraNode("image", [{ i: 0, lora: "" }, { i: 1, lora: "" }]));
  nodes.push(loraNode("video_high", [{ i: 0, lora: "lightx2v_4steps.safetensors", on: true }]));
  nodes.push(loraNode("video_low", [{ i: 0, lora: "", on: false }]));
  for (const k of ["t2i", "i2i", "i2i_fixed", "i2v", "flf2v", "t2v"]) {
    nodes.push(mark("save", k, mkNode("s_" + k, "SaveImage", { mode: k === "t2i" ? 0 : 2 })));
  }
  // 取图节点：LoadImageOutput 的下拉（options.values 按最新在前）
  for (const [k, cur, list] of [
    ["i2i", "old_i2i.png", ["old_i2i.png", "older.png"]],
    ["i2i_fixed", "old_i2if.png", ["old_i2if.png", "older.png"]],
    ["i2v", "old_i2v.png", ["old_i2v.png", "older.png"]],
    ["flf_start", "old_s.png", ["old_s.png", "older.png"]],
    ["flf_end", "old_e.png", ["old_e.png", "older.png"]],
  ]) {
    // 真前端：点 refresh 会重新拉列表，并按 control_after_refresh=first 把值改成第一项（最新）
    const imgW = widget("image", cur, { options: { values: list.slice() } });
    const refW = widget("refresh", "refresh", {
      callback: () => {
        const vs = imgW.options && imgW.options.values;
        if (vs && vs.length) imgW.value = vs[0];
      },
    });
    nodes.push(mark("source_image", k, mkNode("src_" + k, "LoadImageOutput", {
      widgets: [
        imgW,
        widget("control_after_refresh", "first"),
        refW,
        widget("upload", "image"),
      ],
    })));
  }
  nodes.push(mark("module", "pose_sdxl", mkNode("m_ps", "SubgraphNode", { mode: 4 })));
  nodes.push(mark("module", "pose_anima", mkNode("m_pa", "SubgraphNode", { mode: 4 })));
  const mD1 = mark("module", "detailer", mkNode("m_d1", "SubgraphNode", { mode: 4 }));
  const mD2 = mark("module", "detailer", mkNode("m_d2", "SubgraphNode", { mode: 4 }));
  nodes.push(mD1, mD2);
  nodes.push(mark("module", "upscale", mkNode("m_u1", "SubgraphNode", { mode: 4 })));
  nodes.push(mark("module", "upscale", mkNode("m_u2", "SubgraphNode", { mode: 4 })));
  // 视频后处理（v1.4.0）：三条视频管线各一份，同一个开关一起切
  for (const k of ["vfi", "vupscale"]) {
    for (let i = 0; i < 3; i++) {
      nodes.push(mark("module", k,
        mkNode("m_" + k + i, "SubgraphNode", { mode: 4 })));
    }
  }
  // 脸手眼矫正在真前端里是「两个实例共用同一份子图定义」，所以三级开关 / SAM
  // 写的是定义里那四个节点的 mode（这里照着搭：m_d1 / m_d2 指向同一个 subgraph）
  const dInner = [
    mark("detailer_stage", "face", mkNode(11, "FaceDetailer", { mode: 0 })),
    mark("detailer_stage", "hand", mkNode(12, "FaceDetailer", { mode: 0 })),
    mark("detailer_stage", "eye", mkNode(13, "FaceDetailer", { mode: 0 })),
    mark("detailer_sam", "sam", mkNode(15, "SAMLoader", { mode: 0 })),
  ];
  const dSub = {
    id: "sgd", name: "脸手眼矫正", isRootGraph: false, nodes: dInner,
    getNodeById: (id) => dInner.find((n) => String(n.id) === String(id)) || null,
  };
  for (const n of dInner) n.graph = dSub;
  for (const inst of [mD1, mD2]) {
    inst.subgraph = dSub;
    inst.isSubgraphNode = () => true;
  }
  // 高清子图里的分块精修节点：面板的「分块大小」会写进它的 tile_width / tile_height
  nodes.push(mkNode(205, "UltimateSDUpscaleNoUpscale", {
    pos: [1500, 4000], size: [340, 200],
    widgets: [widget("tile_width", 1216), widget("tile_height", 1216)],
  }));
  nodes.push(mark("family", "clip", mkNode("f_clip", "CR Clip Input Switch",
    { widgets: [widget("Input", 1)] })));
  nodes.push(mark("family", "vae", mkNode("f_vae", "CR VAE Input Switch",
    { widgets: [widget("Input", 1)] })));

  // 子图：内部节点 7，用来验证跟随执行会切图 + 采样器下拉写进子图里的 KSampler
  const inner = mkNode(7, "KSampler", {
    pos: [400, 220], size: [320, 200],
    widgets: [
      widget("seed", 1), widget("control_after_generate", "randomize"),
      widget("steps", 28), widget("cfg", 5.5),
      widget("sampler_name", "dpmpp_2m"), widget("scheduler", "karras"),
      widget("denoise", 1),
    ],
  });
  const sub = {
    id: "sg1",
    name: "文生图",
    isRootGraph: false,
    nodes: [inner],
    getNodeById: (id) => (String(id) === "7" ? inner : null),
  };
  inner.graph = sub;
  const subNode = mark("pipeline", "t2i",
    mkNode(113, "SubgraphNode", { pos: [0, 600], size: [300, 140] }));
  subNode.subgraph = sub;
  subNode.isSubgraphNode = () => true;
  nodes.push(subNode);

  // 图生图（固定分辨率）子图：内部 ImageScale → KSampler，
  // 用来验证分辨率写进缩放节点、采样器也写进它自己那个采样节点
  const fScale = mkNode(1, "ImageScale", {
    pos: [80, 80], size: [330, 150],
    widgets: [
      widget("upscale_method", "lanczos",
        { options: { values: ["nearest-exact", "bilinear", "area", "bicubic", "lanczos"] } }),
      widget("width", 1216), widget("height", 832),
      widget("crop", "center", { options: { values: ["disabled", "center"] } }),
    ],
  });
  const fKs = mkNode(3, "KSampler", {
    pos: [820, 80], size: [310, 300],
    widgets: [
      widget("seed", 1), widget("control_after_generate", "randomize"),
      widget("steps", 28), widget("cfg", 5.5),
      widget("sampler_name", "dpmpp_2m"), widget("scheduler", "karras"),
      widget("denoise", 0.5),
    ],
  });
  const fSub = {
    id: "sgf", name: "图生图（固定分辨率）", isRootGraph: false,
    nodes: [fScale, fKs],
    getNodeById: (id) => (String(id) === "1" ? fScale : (String(id) === "3" ? fKs : null)),
  };
  fScale.graph = fSub;
  fKs.graph = fSub;
  const fNode = mark("pipeline", "i2i_fixed",
    mkNode(312, "SubgraphNode", { pos: [0, 1400], size: [300, 140] }));
  fNode.subgraph = fSub;
  fNode.isSubgraphNode = () => true;
  nodes.push(fNode);

  // 视频管线子图：采样器下拉要写 KSamplerAdvanced 的 sampler_name / scheduler
  const vInner = mkNode(2, "KSamplerAdvanced", {
    pos: [400, 260], size: [320, 240],
    widgets: [
      widget("add_noise", "enable"), widget("noise_seed", 1),
      widget("control_after_generate", "randomize"), widget("steps", 4),
      widget("cfg", 1), widget("sampler_name", "euler"),
      widget("scheduler", "simple"), widget("start_at_step", 0),
      widget("end_at_step", 2), widget("return_with_leftover_noise", "enable"),
    ],
  });
  const vSub = {
    id: "sgv", name: "图生视频 I2V", isRootGraph: false, nodes: [vInner],
    getNodeById: () => null,
  };
  vInner.graph = vSub;
  const vNode = mark("pipeline", "i2v",
    mkNode(431, "SubgraphNode", { pos: [900, 600], size: [300, 140] }));
  vNode.subgraph = vSub;
  vNode.isSubgraphNode = () => true;
  nodes.push(vNode);

  // 提示词分段开关：4 组 × 8 段，和真实工作流同构（graph.links 走数组形态）
  const links = [];
  let linkId = 0;
  const wire = (src, sslot, dstNode, inputName) => {
    const slot = dstNode.inputs.findIndex((x) => x.name === inputName);
    const id = ++linkId;
    dstNode.inputs[slot].link = id;
    links.push([id, src, sslot, dstNode.id, slot, "STRING"]);
    return id;
  };
  // 视频模型槽的下游（LoRA 那半边）：换加载器类型时要能把线接回去
  for (const k of ["video_high", "video_low"]) {
    const src = nodes.find((n) => n.properties.cc_dock_role === "unet_slot"
      && n.properties.cc_dock_key === k);
    const dst = mkNode("lora_" + k + "_in", "LoraLoader", {
      widgets: [widget("lora_name", "")],
    });
    dst.inputs = [{ name: "model", link: null }];
    nodes.push(dst);
    const lid = wire(src.id, 0, dst, "model");
    src.outputs = [{ name: "MODEL", links: [lid] }];
  }
  // 只有正面两组有分段开关（负面是单框）
  for (const k of ["image_pos", "video_pos"]) {
    const host = nodes.find((n) => n.id === "t_" + k);
    for (let i = 1; i <= 8; i++) {
      const hand = (k === "image_pos" && i === 1) ? "hello image_pos" : "";
      const sw = segSwitchNode("sw_" + k + "_" + i, hand,
        [1200 + ((i - 1) % 2) * 380, 200 + Math.floor((i - 1) / 2) * 96]);
      sw.title = k + " · 第 " + i + " 段（手填 / 插件）";
      nodes.push(sw);
      wire(sw.id, 0, host, "text" + i);
    }
  }
  // 给 image_pos 的第 3 段挂一个插件来源，用来验证「插件输入 → 上游节点名」
  {
    const plug = mkNode("plug_env", "PrimitiveStringMultiline", {
      widgets: [widget("value", "sunset beach")], pos: [600, 900], size: [220, 60],
    });
    plug.title = "环境描述";
    nodes.push(plug);
    wire("plug_env", 0, nodes.find((n) => n.id === "sw_image_pos_3"), "text_true");
  }

  const byId = new Map(nodes.map((n) => [n.id, n]));
  const g = {
    isRootGraph: true,
    nodes,
    links,
    getNodeById(id) {
      // 桩里图省事用了重号的 id（110+i 撞上 113）：照 LiteGraph 的习惯取最后那个
      for (let i = g.nodes.length - 1; i >= 0; i--) {
        if (String(g.nodes[i].id) === String(id)) return g.nodes[i];
      }
      return byId.get(String(id)) || null;
    },
    add(n) {
      n.graph = g;
      g.nodes.push(n);
      byId.set(String(n.id), n);
      return n;
    },
    remove(n) {
      g.nodes = g.nodes.filter((x) => x !== n);
      byId.delete(String(n.id));
      return n;
    },
    change() {},
  };
  return g;
}

const rootGraph = buildGraph();
const STUB_GRAPH = { id: "sg1", isRootGraph: false, nodes: [], getNodeById: () => null };
const canvasCalls = { setGraph: [], animate: [], subgraph: [] };
const fakeCanvas = {
  graph: rootGraph,
  subgraph: undefined,
  setGraph(g) { canvasCalls.setGraph.push(g); this.graph = g; },
  set subgraphOf(g) { /* noop */ },
  animateToBounds(b, opts) { canvasCalls.animate.push([b, opts]); },
  setDirty() {},
};
Object.defineProperty(fakeCanvas, "subgraph", {
  get() { return this._sub; },
  set(v) { this._sub = v; canvasCalls.subgraph.push(v); },
});

const app = (globalThis.__ccApp = {
  graph: rootGraph,
  canvas: fakeCanvas,
  refreshComboInNodes() {},
  registerExtension(ext) { this._ext = ext; },
  // 队列那一排用到的公开接口（真实前端：app.queuePrompt(number, batchCount) + 命令总线）
  queueCalls: [],
  queuePrompt(number, batch, opts) {
    this.queueCalls.push({ number, batch, opts });
    return Promise.resolve(true);
  },
  extensionManager: {
    command: {
      calls: [],
      // 真前端（实测 1.34）命令入口叫 command.execute；老的写法是 executeCommand
      execute(id, args) {
        this.calls.push({ id, args });
        return Promise.resolve(true);
      },
    },
  },
});

// ------------------------------------------------------- 载入被测 dock.js
const src = fs.readFileSync(DOCK_JS, "utf8")
  .replace('"../../scripts/app.js"', '"./shim_app.mjs"')
  .replace('"../../scripts/api.js"', '"./shim_api.mjs"');
installFixtures();
fs.writeFileSync(UNDER_TEST, src, "utf8");

let results = { pass: 0, fail: 0 };
function ok(cond, label) {
  if (cond) { results.pass++; console.log("  ok   " + label); }
  else { results.fail++; console.log("  FAIL " + label); }
}
function brief(v) {
  try { return JSON.stringify(v); } catch (e) { return String(v); }
}
function eq(got, want, label) { ok(got === want, label + "（得到 " + brief(got) + "，期望 " + brief(want) + "）"); }
// 面板的渲染走 requestAnimationFrame（桩里落到 setTimeout 0）。单次 tick 只等一轮
// 在负载高时可能还没跑完，所以每回多等几轮，让挂起的渲染彻底落地，避免假失败。
const tick = async (n) => {
  const wait = n || 8;
  for (let i = 0; i < 3; i++) await new Promise((r) => setTimeout(r, wait));
};
const sleep = (n) => new Promise((r) => setTimeout(r, n));

let ROOT = null;   // 面板会被搬进独立窗口，这里缓存住同一个元素
const root = () => ROOT || (ROOT = mainDoc.getElementById("cc-dock-root"));
const byText = (text, tag) => {
  const r = root();
  let hit = null;
  walk(r, (n) => {
    if (hit) return;
    if (tag && n.tagName !== tag.toUpperCase()) return;
    if (n.textContent === text) hit = n;
  });
  return hit;
};
const geomOf = () => JSON.parse(localStorage.getItem("cc_dock_ui_v1") || "{}").geom;

try {
  console.log("=".repeat(60));
  console.log("cc_dock 浮动面板冒烟测试");
  console.log("=".repeat(60));

  console.log("\n[1] 载入 + 浮动窗默认形态");
  await import(pathToFileURL(UNDER_TEST).href + "?v=" + Date.now());
  await app._ext.setup();
  await tick(20);
  ok(!!root(), "面板挂到页面");
  eq(root().classList.contains("ccd-docked"), false, "默认不是顶部通栏（是浮动窗）");
  ok(/px$/.test(root().style.left) && /px$/.test(root().style.width), "浮动窗写了 left/width");
  eq(root().style.right, "auto", "浮动窗不受 right:0 拉扯");
  const handles = ["n", "s", "w", "e", "nw", "ne", "sw", "se"].filter((d) =>
    root().children.some((c) => c.attrs["data-dir"] === d));
  eq(handles.length, 8, "八向缩放把手齐全");
  if (process.argv.includes("--html")) {
    writePreview(src, root(), "preview.html");
    byText("LoRA").dispatch("click");
    writePreview(src, root(), "preview_lora.html");
    byText("参数").dispatch("click");
    writePreview(src, root(), "preview_param.html");
    byText("说明").dispatch("click");
    writePreview(src, root(), "preview_help.html");
    byText("提示词").dispatch("click");
    console.log("  （已导出 _t_dock/preview*.html）");
  }

  console.log("\n[2] 面板与画布联动（原有功能没被改坏）");
  const modelSel = root().querySelector("select");
  eq(modelSel.children.length, MODELS.length, "模型下拉列全部 ckpt");
  eq(modelSel.value, MODELS[0], "模型下拉选中当前模型");
  eq(app.graph.getNodeById("sw_image_pos_1").widgets[1].value, "hello image_pos", "第 1 段读到画布上的手填文字");
  eq(app.graph.getNodeById("t_image_pos").widgets[2].value, "hello image_pos", "拼接器那格写成镜像");
  const activeSaves = app.graph.nodes.filter((n) => n.properties.cc_dock_role === "save" && n.mode === 0);
  eq(activeSaves.map((n) => n.properties.cc_dock_key).join(","), "t2i", "默认只有文生图管线是活的");

  const pipeBtn = (label) => {
    let hit = null;
    walk(root(), (n) => { if (!hit && n.tagName === "BUTTON" && n.textContent === label) hit = n; });
    return hit;
  };
  pipeBtn("图生图精修").dispatch("click");
  await tick(10);
  eq(app.graph.nodes.filter((n) => n.properties.cc_dock_role === "save" && n.mode === 0)
    .map((n) => n.properties.cc_dock_key).join(","), "i2i", "切管线只留图生图 Save");

  eq([...root().querySelectorAll("BUTTON")].filter((b) => b.classList.contains("ccd-pipe")).length,
    6, "顶栏 6 个管线按钮（多了一条「图生图」）");
  pipeBtn("图生图").dispatch("click");
  await tick(10);
  eq(app.graph.nodes.filter((n) => n.properties.cc_dock_role === "save" && n.mode === 0)
    .map((n) => n.properties.cc_dock_key).join(","), "i2i_fixed",
  "「图生图」是独立管线（只留 i2ifixed_* 那个 Save）");

  pipeBtn("文生图").dispatch("click");
  await tick(10);
  const modBtn = (label) => {
    let hit = null;
    walk(root(), (n) => { if (!hit && n.tagName === "BUTTON" && n.textContent === label) hit = n; });
    return hit;
  };
  modBtn("姿势").dispatch("click");
  await tick(10);
  eq(app.graph.getNodeById("m_ps").mode, 0, "Illustrious 姿势模块用 SDXL ControlNet");
  eq(app.graph.getNodeById("m_pa").mode, 4, "ANIMA 姿势模块保持旁路");
  modBtn("脸手眼矫正").dispatch("click");
  await tick(10);
  eq(app.graph.getNodeById("m_d1").mode, 0, "脸手眼矫正两条管线一起开");
  eq(app.graph.getNodeById("m_d2").mode, 0, "脸手眼矫正第二实例也开");
  modBtn("脸手眼矫正").dispatch("click");
  await tick(10);

  console.log("\n[3] 拖动 / 缩放 / 位置记忆");
  const bar = root().children[0];
  const before = { x: parseFloat(root().style.left), y: parseFloat(root().style.top) };
  bar.dispatch("pointerdown", { button: 0, clientX: 400, clientY: 40 });
  mainWin.dispatch("pointermove", { clientX: 520, clientY: 160 });
  await tick(20);
  mainWin.dispatch("pointerup", {});
  await tick(20);
  eq(Math.round(parseFloat(root().style.left) - before.x), 120, "拖动横向位移正确");
  eq(Math.round(parseFloat(root().style.top) - before.y), 120, "拖动纵向位移正确");
  eq(Math.round(geomOf().x), Math.round(parseFloat(root().style.left)), "位置写进了 localStorage");

  const se = root().children.find((c) => c.attrs["data-dir"] === "se");
  const w0 = parseFloat(root().style.width);
  const h0 = parseFloat(root().style.height);
  se.dispatch("pointerdown", { button: 0, clientX: 10, clientY: 10 });
  mainWin.dispatch("pointermove", { clientX: 90, clientY: 70 });
  await tick(20);
  mainWin.dispatch("pointerup", {});
  await tick(20);
  eq(Math.round(parseFloat(root().style.width) - w0), 80, "右下角横向缩放正确");
  eq(Math.round(parseFloat(root().style.height) - h0), 60, "右下角纵向缩放正确");

  const nwHandle = root().children.find((c) => c.attrs["data-dir"] === "nw");
  const left0 = parseFloat(root().style.left);
  const w1 = parseFloat(root().style.width);
  nwHandle.dispatch("pointerdown", { button: 0, clientX: 0, clientY: 0 });
  mainWin.dispatch("pointermove", { clientX: -40, clientY: -30 });
  await tick(20);
  mainWin.dispatch("pointerup", {});
  await tick(20);
  eq(Math.round(parseFloat(root().style.left) - left0), -40, "左上角缩放会移动左边界");
  eq(Math.round(parseFloat(root().style.width) - w1), 40, "左上角缩放会加宽");

  const tinyW = 10;
  se.dispatch("pointerdown", { button: 0, clientX: 0, clientY: 0 });
  mainWin.dispatch("pointermove", { clientX: -5000, clientY: -5000 });
  await tick(20);
  mainWin.dispatch("pointerup", {});
  await tick(20);
  ok(parseFloat(root().style.width) >= tinyW && parseFloat(root().style.width) === 420,
    "缩到极限时保底 420×200");
  ok(parseFloat(root().style.height) === 200, "高度保底 200");

  console.log("\n[4] 独立窗口（Document Picture-in-Picture）");
  const pipBtn = byText("⧉");
  ok(!!pipBtn, "顶栏有独立窗口按钮");
  pipBtn.dispatch("click");
  await tick(40);
  eq(pipWindows.length, 1, "申请到了独立窗口");
  ok(pipWindows[0].document.body.children.includes(root()), "面板已搬进独立窗口");
  eq(root().style.width, "100%", "独立窗口里面板铺满");
  ok(root().classList.contains("ccd-pip"), "标记 ccd-pip，缩放把手自动隐藏");
  ok(pipWindows[0].document.querySelector("style[data-cc-dock]") !== null, "样式注入到独立窗口");
  pipBtn.dispatch("click");
  await tick(40);
  ok(mainDoc.body.children.includes(root()), "收回后回到主页面");
  ok(/px$/.test(root().style.width), "收回后恢复浮动尺寸");
  pipBtn.dispatch("click");
  await tick(40);
  pipWindows[pipWindows.length - 1].dispatch("pagehide", {});
  await tick(40);
  ok(mainDoc.body.children.includes(root()), "用户直接关掉独立窗口也能自动收回");

  console.log("\n[5] 跟随执行（默认开）");
  const focusBtn = byText("◎");
  ok(!!focusBtn, "顶栏有跟随执行按钮");
  ok(focusBtn.classList.contains("ccd-on"), "默认是开启状态");
  canvasCalls.animate.length = 0;
  canvasCalls.setGraph.length = 0;
  globalThis.__ccApi.emit("executing", "113:7");
  await sleep(220);
  eq(canvasCalls.setGraph.length, 1, "自动切进目标子图");
  eq(canvasCalls.setGraph[0], rootGraph.getNodeById("113").subgraph, "切的是节点所在的子图");
  eq(canvasCalls.animate.length, 1, "聚焦到执行中的节点");
  eq(canvasCalls.animate[0][0], rootGraph.getNodeById("113").subgraph.getNodeById("7").boundingRect, "聚焦框是那个节点");
  ok(canvasCalls.animate[0][1] && canvasCalls.animate[0][1].duration > 0, "带缩放动画参数");
  focusBtn.dispatch("click");
  await tick(10);
  eq(focusBtn.classList.contains("ccd-on"), false, "点一下可以关掉");
  canvasCalls.animate.length = 0;
  globalThis.__ccApi.emit("executing", "113:7");
  await sleep(200);
  eq(canvasCalls.animate.length, 0, "关掉后不再抢镜头");
  focusBtn.dispatch("click");
  await tick(10);
  ok(JSON.parse(localStorage.getItem("cc_dock_ui_v1")).focus === true, "开关状态记进 localStorage");

  console.log("\n[6] 钉回顶部通栏 / 恢复浮动");
  const dockBtn = byText("📌");
  dockBtn.dispatch("click");
  await tick(20);
  ok(root().classList.contains("ccd-docked"), "钉回顶部");
  eq(root().style.left, "0", "通栏时贴左");
  eq(root().style.width, "", "通栏时宽度交给 CSS");
  dockBtn.dispatch("click");
  await tick(20);
  ok(!root().classList.contains("ccd-docked"), "再点恢复浮动");
  ok(/px$/.test(root().style.width), "恢复浮动后有固定宽度");

  console.log("\n[7] 模型切换 + LoRA 联动");
  const modelNode = app.graph.getNodeById("101");
  modelSel.value = MODELS[1];
  modelSel.dispatch("change", {});
  await tick(20);
  eq(modelNode.widgets[0].value, MODELS[1], "模型槽跟着下拉走");
  eq(app.graph.getNodeById("p_steps").widgets[0].value, 30, "ANIMA 自动套 30 步");
  eq(app.graph.getNodeById("p_cfg").widgets[0].value, 4.5, "ANIMA 自动套 CFG 4.5");
  eq(app.graph.getNodeById("102").mode, 4, "ANIMA 旁路 CLIPSetLastLayer");
  eq(app.graph.getNodeById("m_pa").mode, 0, "ANIMA 姿势模块自动接上 LLLite");
  eq(app.graph.getNodeById("m_ps").mode, 4, "SDXL 姿势模块让位");
  eq(app.graph.getNodeById("f_clip").widgets[0].value, 2, "ANIMA 切 CLIP 来源到 110");
  eq(app.graph.getNodeById("f_vae").widgets[0].value, 2, "ANIMA 切 VAE 来源到 111");

  modelSel.value = MODELS[0];
  modelSel.dispatch("change", {});
  await tick(20);
  eq(app.graph.getNodeById("f_clip").widgets[0].value, 1, "切回 SDXL 恢复 CLIP 来源 1");
  eq(app.graph.getNodeById("f_vae").widgets[0].value, 1, "切回 SDXL 恢复 VAE 来源 1");

  const loraCol = root().querySelectorAll(".ccd-lora-col")[0];
  const loraSel = loraCol.children[1].children[0].children[1];
  loraSel.value = "qingxiao_anima_v1.safetensors";
  loraSel.dispatch("change", {});
  await tick(10);
  // 注意：v1.9.0 起 role=te_slot/vae_slot 的节点也用 key="image"，必须连 role 一起判
  const imgLora = app.graph.nodes.find((n) => n.properties
    && n.properties.cc_dock_role === "lora_group"
    && n.properties.cc_dock_key === "image");
  eq(imgLora.widgets[0].value.lora, "qingxiao_anima_v1.safetensors", "LoRA 行写入画布节点");

  console.log("\n[8] LoRA 勾选写入缺陷（选了却不生效）+ 状态行");
  const loraCol0 = root().querySelectorAll(".ccd-lora-col")[0];
  const loraRow0 = loraCol0.children[1].children[0];
  const loraOn = loraRow0.children[0];
  const loraPick = loraRow0.children[1];
  const loraStatus = loraRow0.children[3];
  ok(!!loraStatus && loraStatus.className.indexOf("ccd-lora-status") >= 0, "LoRA 行带状态行");
  loraPick.value = "hiyuki_(wuthering_waves)_ilv1.0-xl.safetensors";
  loraPick.dispatch("change", {});
  await tick(10);
  eq(imgLora.widgets[0].value.on, true, "新选一行写成 on=true（以前错写成 false）");
  eq(loraOn.checked, true, "勾选框同步打勾");
  ok(/触发词/.test(loraStatus.textContent), "状态行显示触发词信息");
  loraOn.checked = false;
  loraOn.dispatch("change", {});
  await tick(10);
  eq(imgLora.widgets[0].value.on, false, "手动取消勾选写回 on=false");
  ok(loraStatus.textContent.indexOf("未启用") >= 0, "状态行提示「已选但未启用」");
  loraStatus.classList.contains("ccd-warn") && ok(true, "未启用时状态行标黄");
  loraOn.checked = true;
  loraOn.dispatch("change", {});
  await tick(10);
  loraPick.value = "qingxiao_anima_v1.safetensors";
  loraPick.dispatch("change", {});
  await tick(10);
  ok(loraStatus.textContent.indexOf("模型族") >= 0, "ANIMA 系 LoRA 挂在 SDXL 模型上会提示不匹配");
  eq(imgLora.widgets[0].value.on, true, "换 LoRA 继续保持启用");

  console.log("\n[9] 种子：🎲 随机开关（默认开）");
  const paramTab = root().querySelector(".ccd-params");
  const imgSet = paramTab.children[0];
  let seedChk = null;
  walk(imgSet, (n) => {
    if (seedChk || n.tagName !== "INPUT" || n.attrs.type !== "checkbox") return;
    const lab = n.parentNode;
    const txt = ((lab && lab.children) || []).map((c) => c.textContent).join("");
    if (txt.indexOf("随机") >= 0) seedChk = n;
  });
  ok(!!seedChk, "图像种子有 🎲 随机勾选框");
  eq(seedChk.checked, true, "默认就是勾上的");
  const seedNode = app.graph.getNodeById("p_seed");
  eq(seedNode.widgets[1].value, "randomize", "画布上写成 randomize（每张都换种子）");
  seedChk.checked = false;
  seedChk.dispatch("change", {});
  await tick(10);
  eq(seedNode.widgets[1].value, "fixed", "取消后写 fixed（按种子细调）");
  seedChk.checked = true;
  seedChk.dispatch("change", {});
  await tick(10);
  eq(seedNode.widgets[1].value, "randomize", "再勾上恢复 randomize");

  console.log("\n[10] 分段提示词总线（8 段 / 手填·插件二选一 / ⌖ 跳转）");
  const posNode = app.graph.getNodeById("t_image_pos");
  const posGroup = root().querySelectorAll(".ccd-pg")[0];
  const segRows = posGroup.children[1].children;
  eq(segRows.length, 8, "每组 8 段");
  const visible = (rows) => rows.filter((r) => !r.classList.contains("ccd-hide")).length;
  eq(visible(segRows), 5, "默认露到「最后用到的第 3 段 + 2」= 5 行");
  const sw2 = app.graph.getNodeById("sw_image_pos_2");
  const ta2 = segRows[1].children[1];
  ta2.value = "extra words";
  ta2.dispatch("change", {});
  await tick(10);
  eq(sw2.widgets[1].value, "extra words", "第 2 段写进开关节点的 text_false");
  eq(sw2.widgets[2].value, "extra words", "text_true 同步兜底文本");
  eq(posNode.widgets[4].value, "extra words", "拼接器第 2 格同步镜像");
  const plugChk2 = segRows[1].children[2].children[0];
  plugChk2.checked = true;
  plugChk2.dispatch("change", {});
  await tick(10);
  eq(sw2.widgets[0].value, true, "勾「插件输入」写 boolean_value=true");
  ok(segRows[1].children[6].textContent.indexOf("插件：未连线") === 0,
    "勾了插件但没连线时提示去连");
  const sw3 = app.graph.getNodeById("sw_image_pos_3");
  const plugChk3 = segRows[2].children[2].children[0];
  plugChk3.checked = true;
  plugChk3.dispatch("change", {});
  await tick(10);
  eq(sw3.widgets[0].value, true, "第 3 段插件输入打开");
  eq(segRows[2].children[6].textContent, "插件 ← 环境描述", "状态显示插件来源节点名");
  const en2 = segRows[1].children[3].children[0];
  en2.checked = false;
  en2.dispatch("change", {});
  await tick(10);
  eq(posNode.widgets[3].value, false, "取消启用写 enable2=false");
  const ta6 = segRows[5].children[1];
  ta6.value = "seg six";
  ta6.dispatch("change", {});
  await tick(10);
  eq(visible(segRows), 8, "写到第 6 段后下面自动补满 8 行");
  ok(/8 段/.test(posGroup.children[0].children[4].textContent), "顶到 8 段上限时给提示");
  canvasCalls.animate.length = 0;
  segRows[2].children[4].dispatch("click");
  await sleep(80);
  eq(canvasCalls.animate.length, 1, "⌖ 跳转聚焦到那一段的开关节点");
  eq(canvasCalls.animate[0][0], sw3.boundingRect, "聚焦框就是那个开关节点");

  console.log("\n[10c2] 装了本机 Opus-MT 时「译」= 真翻译（不再被词典截胡）");
  const keepFetchNmt = globalThis.fetch;
  globalThis.fetch = async (url, opt) => {
    const u = String(url || "");
    if (u.indexOf("/translate/status") >= 0) {
      return { ok: true, status: 200,
        json: async () => ({ ok: true, installed: true, loaded: true }) };
    }
    if (u.indexOf("/translate") >= 0) {
      return { ok: true, status: 200,
        json: async () => ({ ok: true, installed: true, loaded: true,
          engine: "opus-mt", text: "The silver-haired girl smiles.", chunks: 2,
          load_ms: 4200 }) };
    }
    return keepFetchNmt(url, opt);
  };
  const trBtn8 = segRows[7].children[5];
  const ta8 = segRows[7].children[1];
  ta8.value = "银发女孩微笑";              // 词典能全覆盖，但装了模型就该走 NMT
  ta8.dispatch("change", {});
  await tick(10);
  trBtn8.dispatch("click");
  await tick(60);
  eq(ta8.value, "The silver-haired girl smiles.", "装了 Opus-MT 走 NMT（真翻译）");
  eq(app.graph.getNodeById("sw_image_pos_8").widgets[1].value,
    "The silver-haired girl smiles.", "NMT 结果写回画布节点");
  eq(segRows[7].children[6].textContent, "NMT · 加载 4.2s", "状态栏标出走的是 NMT");
  globalThis.fetch = keepFetchNmt;

  console.log("\n[10c] 中→英翻译按钮（没装模型时：词典兜底、离线可用）");
  const trBtn7 = segRows[6].children[5];
  ok(!!trBtn7 && trBtn7.tagName === "BUTTON", "每段行尾有「译」按钮");
  eq(posGroup.children[0].children[1].textContent, "中→英",
    "组头有「中→英」译本组按钮");
  const ta7 = segRows[6].children[1];
  ta7.value = "银发女孩微笑";
  ta7.dispatch("change", {});
  await tick(10);
  trBtn7.dispatch("click");
  await tick(40);
  eq(ta7.value, "1girl silver hair smile", "点译后文本框变英文标签");
  eq(app.graph.getNodeById("sw_image_pos_7").widgets[1].value,
    "1girl silver hair smile", "英文写回画布节点（手填 text_false）");
  eq(segRows[6].children[6].textContent, "词典",
    "词典兜底时状态栏标「词典」，不报未收录");

  console.log("\n[10b] 负面提示词 = 单框（不分段、无插件开关）");
  const negGroup = root().querySelectorAll(".ccd-pg")[1];
  eq(negGroup.querySelectorAll(".ccd-seg").length, 0, "负面提示词没有分段行");
  const negTa = negGroup.children[1];
  eq(negTa.tagName, "TEXTAREA", "负面提示词就是一个文本框");
  eq(negTa.classList.contains("ccd-pg-plain"), true, "这个框是单框样式");
  const negNode = app.graph.getNodeById("t_image_neg");
  eq(negTa.value, "hello image_neg", "面板显示画布上的负面原文");
  negTa.value = "blurry, extra fingers";
  negTa.dispatch("change", {});
  await tick(10);
  eq(negNode.widgets[0].value, "blurry, extra fingers", "改负面整框直接写节点 value");
  eq(negNode.widgets.length, 1, "负面节点只有一个 widget（没有 enable/段位）");
  const vNegGroup = root().querySelectorAll(".ccd-pg")[3];
  eq(vNegGroup.querySelectorAll(".ccd-seg").length, 0, "视频负面同样是单框");

  console.log("\n[11] 面板随管线过滤");
  const videoGroup = root().querySelectorAll(".ccd-pg")[2];
  const imgLoraCols = root().querySelectorAll(".ccd-lora-col");
  pipeBtn("图生视频").dispatch("click");
  await tick(20);
  eq(posGroup.classList.contains("ccd-hide"), true, "视频管线藏起图像提示词");
  eq(videoGroup.classList.contains("ccd-hide"), false, "视频提示词显示出来");
  eq(imgSet.classList.contains("ccd-hide"), true, "图像参数藏起来");
  eq(paramTab.children[1].classList.contains("ccd-hide"), false, "视频参数显示出来");
  eq(imgLoraCols[0].classList.contains("ccd-hide"), true, "图像 LoRA 组藏起来");
  eq(imgLoraCols[1].classList.contains("ccd-hide"), false, "视频 high LoRA 显示");
  eq(modBtn("姿势").classList.contains("ccd-hide"), true, "视频管线不显示姿势");
  eq(modBtn("脸手眼矫正").classList.contains("ccd-hide"), true, "视频管线不显示脸手眼矫正");
  eq(paramTab.children[2].classList.contains("ccd-hide"), false, "视频管线给一行说明");
  eq(JSON.parse(localStorage.getItem("cc_dock_ui_v1")).pipe, "i2v", "当前管线记进 localStorage");
  pipeBtn("文生图").dispatch("click");
  await tick(20);
  eq(posGroup.classList.contains("ccd-hide"), false, "切回文生图又显示图像提示词");
  eq(imgSet.classList.contains("ccd-hide"), false, "图像参数回来");
  eq(modBtn("姿势").classList.contains("ccd-hide"), false, "文生图显示姿势按钮");
  eq(modBtn("脸手眼矫正").classList.contains("ccd-hide"), false, "文生图显示脸手眼矫正");
  pipeBtn("图生图精修").dispatch("click");
  await tick(20);
  eq(modBtn("姿势").classList.contains("ccd-hide"), true, "图生图不显示姿势（采样前改条件）");
  eq(modBtn("高清化").classList.contains("ccd-hide"), false, "图生图显示高清化");
  pipeBtn("图生图").dispatch("click");
  await tick(20);
  eq(posGroup.classList.contains("ccd-hide"), false, "图生图（固定分辨率）是图像管线：图像提示词显示");
  eq(imgSet.classList.contains("ccd-hide"), false, "图生图显示图像参数");
  eq(imgLoraCols[0].classList.contains("ccd-hide"), false, "图生图用图像 LoRA 组（共用同一个）");
  eq(modBtn("姿势").classList.contains("ccd-hide"), true, "图生图不显示姿势（它也没接 ControlNet）");
  eq(modBtn("脸手眼矫正").classList.contains("ccd-hide"), false, "图生图显示脸手眼矫正");
  eq(modBtn("高清化").classList.contains("ccd-hide"), false, "图生图显示高清化");

  console.log("\n[12] 参数按模块分区（模块开着才显示那一块）");
  const secOf = (set, title) => {
    let hit = null;
    walk(set, (n) => {
      if (hit || n.tagName !== "FIELDSET") return;
      const lg = (n.children || [])[0];
      if (lg && lg.textContent === title) hit = n;
    });
    return hit;
  };
  const fieldOf = (sec, label) => {
    let hit = null;
    walk(sec, (n) => {
      if (hit || n.tagName !== "INPUT") return;
      const lab = (n.parentNode && n.parentNode.children) || [];
      if (lab.length && lab[0].textContent === label) hit = n.parentNode;
    });
    return hit;
  };
  const countInputs = (sec) => {
    let n = 0;
    walk(sec, (x) => { if (x.tagName === "INPUT") n++; });
    return n;
  };
  const setMod = async (label, want) => {
    const b = modBtn(label);
    if (b.classList.contains("ccd-on") !== want) b.dispatch("click");
    await tick(20);
  };
  const tube = (sec) => sec && sec.classList.contains("ccd-hide");
  pipeBtn("文生图").dispatch("click");
  await tick(20);
  const genSec = secOf(imgSet, "生成参数");
  const poseSec = secOf(imgSet, "姿势参数");
  const detSec = secOf(imgSet, "脸手眼矫正参数");
  const upSec = secOf(imgSet, "高清参数");
  ok(!!genSec && !!poseSec && !!detSec && !!upSec,
    "参数页分成生成 / 姿势 / 脸手眼矫正 / 高清四块");
  // 上游用例可能留着模块开着，这里先把三个模块都关掉再断言
  await setMod("姿势", false);
  await setMod("脸手眼矫正", false);
  await setMod("高清化", false);
  eq(tube(genSec), false, "生成参数一直显示");
  eq(tube(poseSec), true, "姿势模块关着 → 姿势参数收起");
  eq(tube(detSec), true, "手眼模块关着 → 手眼参数收起");
  eq(tube(upSec), true, "高清模块关着 → 高清参数收起");
  eq(tube(fieldOf(genSec, "重绘强度")), true, "重绘强度在文生图不显示（只有图生图用）");
  pipeBtn("图生图").dispatch("click");
  await tick(20);
  eq(tube(fieldOf(genSec, "重绘强度")), false, "图生图（固定分辨率）也显示重绘强度");
  eq(tube(genSec), false, "图生图用的是同一份生成参数");
  pipeBtn("文生图").dispatch("click");
  await tick(20);

  await setMod("脸手眼矫正", true);
  eq(tube(detSec), false, "打开手眼矫正 → 手眼参数出现");
  // v6.5：4 个开关（脸 / 手 / 眼 / SAM）+ 9 个数字（含眼检测阈值、检测框放大尺寸）
  eq(countInputs(detSec), 13, "脸手眼参数有 13 项（4 开关 + 9 数字）");
  const thr = fieldOf(detSec, "检测阈值");
  eq(thr.tagName, "SPAN", "参数行是外层 ccd-param 框（收起时整框隐藏）");
  const thrInp = thr.querySelector("input");
  thrInp.value = "0.35";
  thrInp.dispatch("change", {});
  await tick(10);
  eq(app.graph.getNodeById("p_detailer_threshold").widgets[0].value, 0.35,
    "检测阈值写回画布");
  const eyeField = fieldOf(detSec, "眼检测阈值");
  ok(!!eyeField, "脸手眼参数里有单独的「眼检测阈值」");
  const eyeInp = eyeField.querySelector("input");
  eyeInp.value = "0.71";
  eyeInp.dispatch("change", {});
  await tick(10);
  eq(app.graph.getNodeById("p_detailer_threshold_eye").widgets[0].value, 0.71,
    "眼检测阈值写回画布（跟脸 / 手那级分开）");
  ok(/0\.70/.test(String(eyeInp.title || "")), "眼检测阈值写了默认 0.70 的说明");
  const faceDen = fieldOf(detSec, "脸重绘");
  eq(String(faceDen.querySelector("input").value), "0.4", "脸重绘显示画布上的 0.4");

  // v6.5：三级独立开关 + SAM —— 写的是「脸手眼矫正」子图定义里那四个节点的 mode
  const chkOf = (label) => {
    const f = fieldOf(detSec, label);
    return f ? f.querySelector("input") : null;
  };
  const flip = async (label) => {
    const c = chkOf(label);
    c.checked = !c.checked;
    c.dispatch("change", {});
    await tick(20);
    return c;
  };
  const dSub = () => app.graph.getNodeById("m_d1").subgraph;
  const stageNode = (k) => dSub().nodes.find(
    (n) => n.properties.cc_dock_role === "detailer_stage"
      && n.properties.cc_dock_key === k);
  const samNode = () => dSub().nodes.find(
    (n) => n.properties.cc_dock_role === "detailer_sam");
  eq(app.graph.getNodeById("m_d2").subgraph, dSub(),
    "两条图像管线共用同一份矫正子图（开关调一次两边都变）");
  eq(chkOf("🧑 脸").checked, true, "「脸」那级默认开");
  await flip("✋ 手");
  eq(stageNode("hand").mode, 4, "取消「手」→ 手那级走旁路（mode 4）");
  eq(stageNode("face").mode, 0, "关手不影响脸那级");
  await flip("✋ 手");
  eq(stageNode("hand").mode, 0, "再勾回「手」→ 回到正常（mode 0）");
  await flip("👁 眼");
  eq(stageNode("eye").mode, 4, "取消「眼」→ 眼那级走旁路");
  await flip("👁 眼");
  eq(stageNode("eye").mode, 0, "勾回「眼」→ 回到正常");
  eq(chkOf("🧑 脸").checked, true, "脸那级一直没被动过");
  ok(!!fieldOf(detSec, "检测框放大尺寸") && !!fieldOf(detSec, "放大上限")
    && !!fieldOf(detSec, "裁剪倍率"),
    "参数里有检测框放大尺寸 / 放大上限 / 裁剪倍率（v6.5 防「脸被贴上去」）");
  await flip("⬟ SAM 轮廓遮罩");
  eq(samNode().mode, 2, "取消 SAM → SAMLoader 静音（不加载模型）");
  await flip("⬟ SAM 轮廓遮罩");
  eq(samNode().mode, 0, "勾回 SAM → SAMLoader 重新加载");
  // 画布那边被外部改过（比如双击进子图手动旁路）也要回灌到面板
  stageNode("hand").mode = 4;
  pipeBtn("文生图").dispatch("click");
  await tick(20);
  eq(chkOf("✋ 手").checked, false, "画布上旁路了手那级 → 复选框跟着回填");
  stageNode("hand").mode = 0;
  pipeBtn("文生图").dispatch("click");
  await tick(20);

  await setMod("姿势", true);
  eq(tube(poseSec), false, "打开姿势 → 姿势参数出现");
  eq(tube(detSec), false, "手眼仍开着 → 手眼参数还在");
  await setMod("脸手眼矫正", false);
  eq(tube(detSec), true, "关掉手眼矫正 → 手眼参数收起");

  await setMod("高清化", true);
  eq(tube(upSec), false, "打开高清化 → 高清参数出现");
  eq(tube(fieldOf(upSec, "高清倍数")), false, "高清倍数在里面");
  ok(/填几就是几倍/.test(String(
    fieldOf(upSec, "高清倍数").querySelector("input").title || "")),
    "高清倍数注明「填几就是几倍」（链子里只剩一次放大）");
  await setMod("高清化", false);
  eq(tube(upSec), true, "关掉高清化 → 高清参数收起");

  pipeBtn("图生图精修").dispatch("click");
  await tick(20);
  eq(tube(fieldOf(genSec, "重绘强度")), false, "切到图生图 → 重绘强度出现");
  eq(tube(poseSec), true, "图生图这条管线上没有姿势模块 → 姿势参数收起（姿势还开着）");
  pipeBtn("图生视频").dispatch("click");
  await tick(20);
  eq(tube(imgSet), true, "视频管线收起整块图像参数");
  eq(tube(paramTab.children[1]), false, "视频参数显示出来");
  eq(tube(secOf(paramTab.children[1], "视频生成参数")), false, "视频参数那块在");

  console.log("\n[13] 参数悬停说明 + 一键重置默认值");
  const numInputs = [];
  walk(paramTab, (n) => {
    if (n.tagName === "INPUT" && n.attrs.type === "number") numInputs.push(n);
  });
  ok(numInputs.length >= 19, "参数条目共 " + numInputs.length + " 项");
  const noTip = numInputs.filter((n) => {
    const lab = (n.parentNode && n.parentNode.children) || [];
    return !n.title && !(lab[0] && lab[0].title);
  });
  eq(noTip.length, 0, "每一项都有鼠标悬停说明");
  ok(/步数/.test(String((fieldOf(genSec, "步数") || {}).textContent || "")
    + String(fieldOf(genSec, "步数") ? fieldOf(genSec, "步数").querySelector("input").title : "")),
    "提示写在参数行上（步数那条能读到说明）");

  // 先改乱几个值，再点重置
  const wInp = fieldOf(genSec, "宽").querySelector("input");
  wInp.value = "512";
  wInp.dispatch("change", {});
  const detInp = fieldOf(upSec, "高清倍数").querySelector("input");
  detInp.value = "3.5";
  detInp.dispatch("change", {});
  await tick(10);
  eq(app.graph.getNodeById("p_width").widgets[0].value, 512, "先改成 512");

  let resetBtn = null;
  walk(paramTab.parentNode || root(), (n) => {
    if (!resetBtn && n.tagName === "BUTTON" && n.textContent.indexOf("重置默认值") >= 0) {
      resetBtn = n;
    }
  });
  ok(!!resetBtn, "参数页有「↺ 重置默认值」按钮");
  const resetTip = String(resetBtn.getAttribute("title") || resetBtn.title || "");
  ok(/1024/.test(resetTip) && /24/.test(resetTip) && /0\.25/.test(resetTip)
    && /0\.70/.test(resetTip) && /512/.test(resetTip),
    "按钮的悬停说明写了各参数默认值（分辨率按模型推荐、含眼阈值 0.70 与检测框放大 512）");
  const loraBefore = JSON.stringify(
    app.graph.getNodeById("l_image").widgets[0].value);
  const modelBefore = app.graph.getNodeById(101).widgets[0].value;
  resetBtn.dispatch("click");
  await tick(20);
  eq(app.graph.getNodeById("p_width").widgets[0].value, 1024,
    "宽回到当前模型推荐分辨率（Illustrious → 1024）");
  eq(app.graph.getNodeById("p_height").widgets[0].value, 1024,
    "高也回到 1024（模型推荐）");
  eq(app.graph.getNodeById("p_upscale_factor").widgets[0].value, 2, "高清倍数回到 2");
  eq(app.graph.getNodeById("p_upscale_whole_denoise").widgets[0].value, 0.12,
    "整体细化强度回到 0.12");
  eq(app.graph.getNodeById("p_upscale_denoise").widgets[0].value, 0.12,
    "分块精修强度回到 0.12");
  eq(app.graph.getNodeById("p_upscale_seam_fix").widgets[0].value, 0.3,
    "接缝修复强度回到 0.30");
  eq(app.graph.getNodeById("p_detailer_feather").widgets[0].value, 24, "羽化回到 24");
  eq(app.graph.getNodeById("p_detailer_denoise_face").widgets[0].value, 0.25,
    "脸重绘回到 0.25（只修不重画）");
  eq(app.graph.getNodeById("p_detailer_denoise_hand").widgets[0].value, 0.25,
    "手重绘回到 0.25（0.6 那种会凭空长出多余的手指）");
  eq(app.graph.getNodeById("p_detailer_denoise_eye").widgets[0].value, 0.20,
    "眼重绘回到 0.20");
  eq(app.graph.getNodeById("p_detailer_threshold").widgets[0].value, 0.55,
    "检测阈值回到 0.55");
  eq(app.graph.getNodeById("p_detailer_threshold_eye").widgets[0].value, 0.70,
    "眼检测阈值回到 0.70");
  eq(app.graph.getNodeById("p_detailer_guide").widgets[0].value, 512,
    "检测框放大尺寸回到 512");
  eq(app.graph.getNodeById("p_detailer_max_size").widgets[0].value, 1024,
    "放大上限回到 1024");
  eq(app.graph.getNodeById("p_detailer_crop").widgets[0].value, 2.5,
    "裁剪倍率回到 2.5");
  for (const [k, lab] of [["face", "脸"], ["hand", "手"], ["eye", "眼"]]) {
    eq(stageNode(k).mode, 0, "重置把「" + lab + "」那级勾回开");
  }
  eq(samNode().mode, 0, "重置把 SAM 也勾回开");
  eq(app.graph.getNodeById("p_steps").widgets[0].value, 28,
    "步数按当前模型族（Illustrious）回到 28");
  eq(app.graph.getNodeById("p_seed").widgets[1].value, "randomize",
    "随机种子开关跟着回到开");
  eq(app.graph.getNodeById("m_ps").mode, 0, "重置不动模块开关（姿势还开着）");
  eq(JSON.stringify(app.graph.getNodeById("l_image").widgets[0].value), loraBefore,
    "重置不动 LoRA");
  eq(app.graph.getNodeById(101).widgets[0].value, modelBefore, "重置不动模型槽");
  const parStatusEl = root().querySelector(".ccd-par-status");
  ok(!!parStatusEl && /已重置/.test(parStatusEl.textContent),
    "重置后给一句反馈：" + (parStatusEl ? parStatusEl.textContent : "没有状态元素"));

  // 超安全区的值要在那一行下面给提醒（怪图基本都是这几个旋钮造成的）
  const warnTxt = (lab) => {
    const row = fieldOf(detSec, lab);
    const w = row && row.querySelector(".ccd-warn-txt");
    return String((w && w.textContent) || "");
  };
  const setDetNum = async (lab, v) => {
    const i = fieldOf(detSec, lab).querySelector("input");
    i.value = String(v);
    i.dispatch("change", {});
    await tick(20);
  };
  await setDetNum("手重绘", 0.6);
  ok(/≥0\.35/.test(warnTxt("手重绘")), "手重绘 0.6 超出安全区 → 行下面出现提醒");
  await setDetNum("手重绘", 0.25);
  eq(warnTxt("手重绘"), "", "回到 0.25 → 提醒消失");
  await setDetNum("检测框放大尺寸", 1024);
  ok(/≥768/.test(warnTxt("检测框放大尺寸")),
    "检测框放大尺寸 1024 → 提醒「脸会被放大重画后贴回去」");
  await setDetNum("检测框放大尺寸", 512);

  console.log("\n[13b] 面板参数本地记忆（刷新 / 重开工作流不弹回旧值）");
  const pkey = [...store.keys()].find((k) => k.indexOf("cc_dock_params_v1:") === 0);
  ok(!!pkey, "面板调过的参数写进了 localStorage：" + pkey);
  const wInp2 = fieldOf(genSec, "宽").querySelector("input");
  wInp2.value = "896";
  wInp2.dispatch("change", {});
  await tick(10);
  eq(Number((JSON.parse(localStorage.getItem(pkey) || "{}")).width), 896,
    "改宽 → localStorage 记下 896");
  eq(Number((JSON.parse(localStorage.getItem(pkey) || "{}")).detailer_feather), 24,
    "重置后的羽化 24 也被记住");
  app.graph.getNodeById("p_width").widgets[0].value = 512;   // 假装画布上是旧值
  globalThis.__ccApi.emit("graphConfigured");                // 模拟重开工作流
  await tick(60);
  eq(app.graph.getNodeById("p_width").widgets[0].value, 896,
    "重开工作流后把记住的宽写回画布（不再弹回 512）");
  // 收尾：宽改回 1216，别把记住的值留给后面的场景
  const wInp3 = fieldOf(genSec, "宽").querySelector("input");
  wInp3.value = "1216";
  wInp3.dispatch("change", {});
  await tick(10);
  eq(app.graph.getNodeById("p_width").widgets[0].value, 1216, "收尾：宽改回 1216");

  // ---------------------------------------------------------------- 取图同步
  console.log("\n[13c] 分辨率下拉 + 采样器 / 调度器下拉");
  pipeBtn("文生图").dispatch("click");
  await tick(20);
  const selOf = (sec, label) => {
    let hit = null;
    walk(sec, (n) => {
      if (hit || n.tagName !== "SELECT") return;
      const lab = (n.parentNode && n.parentNode.children) || [];
      if (lab.length && lab[0].textContent === label) hit = n;
    });
    return hit;
  };
  const optValues = (s) => (s.children || []).map((o) => String(o.value));
  const pnum = (id) => app.graph.getNodeById(id).widgets[0].value;
  const resSel = selOf(genSec, "分辨率");
  ok(!!resSel, "生成参数里有「分辨率」下拉");
  const resOpts = optValues(resSel);
  eq(resOpts[0], "__rec", "分辨率下拉第一项是「模型推荐」");
  ok(resOpts.indexOf("1216x832") >= 0 && resOpts.indexOf("1344x768") >= 0
    && resOpts.indexOf("1280x720") >= 0 && resOpts.indexOf("768x1344") >= 0
    && resOpts.indexOf("512x512") >= 0,
    "内置主流分辨率（SDXL 官方桶 + 16:9 / 竖屏 + SD1.5）");
  ok(/SDXL|Illustrious/.test(String(resSel.children[0].textContent))
    && /1024/.test(String(resSel.children[0].textContent)),
    "推荐项写明模型族的训练分辨率：" + resSel.children[0].textContent);
  ok(optValues(resSel).indexOf("__custom") >= 0, "留着「自定义」一项给手填宽高");
  resSel.value = "832x1216";
  resSel.dispatch("change");
  await tick(20);
  eq(pnum("p_width"), 832, "选竖图预设 → 宽写 832");
  eq(pnum("p_height"), 1216, "选竖图预设 → 高写 1216");
  eq(Number((JSON.parse(localStorage.getItem(pkey) || "{}")).width), 832,
    "分辨率预设也记进本地记忆");
  // ⇄ 互换：下拉要跟着认出 1216×832 这一档
  fieldOf(genSec, "高").querySelector("button").dispatch("click");
  await tick(20);
  eq(pnum("p_width"), 1216, "⇄ 后宽 = 1216");
  eq(pnum("p_height"), 832, "⇄ 后高 = 832");
  eq(resSel.value, "1216x832", "⇄ 之后下拉自动对上 1216×832 那一档");

  const smpSel = selOf(genSec, "采样器");
  const schSel = selOf(genSec, "调度器");
  ok(!!smpSel && !!schSel, "生成参数里有「采样器」和「调度器」下拉");
  ok(optValues(smpSel).indexOf("dpmpp_2m") >= 0 && optValues(smpSel).length >= 8,
    "采样器列表来自 KSampler 定义（共 " + optValues(smpSel).length + " 项）");
  ok(optValues(schSel).indexOf("karras") >= 0, "调度器列表里有 karras");
  const imgKs = () => app.graph.getNodeById("113").subgraph.getNodeById("7");
  const imgW = (name) => (imgKs().widgets.find((w) => w.name === name) || {}).value;
  eq(imgW("sampler_name"), "dpmpp_2m", "画布上原本是 dpmpp_2m");
  smpSel.value = "euler_ancestral";
  smpSel.dispatch("change");
  await tick(20);
  eq(imgW("sampler_name"), "euler_ancestral",
    "选采样器 → 写进文生图子图里的 KSampler");
  schSel.value = "sgm_uniform";
  schSel.dispatch("change");
  await tick(20);
  eq(imgW("scheduler"), "sgm_uniform", "选调度器 → 写进同一个 KSampler");
  const fitKs = () => app.graph.getNodeById("312").subgraph.getNodeById("3");
  const fitW = (name) => (fitKs().widgets.find((w) => w.name === name) || {}).value;
  eq(fitW("sampler_name"), "euler_ancestral", "采样器也写进图生图（固定分辨率）子图");
  eq(fitW("scheduler"), "sgm_uniform", "  └ 调度器同样写进去");
  eq((JSON.parse(localStorage.getItem(pkey) || "{}")).__sampler_image, "euler_ancestral",
    "采样器选择记进本地记忆");
  // 视频那套是独立的：切到视频管线才显示，写的是 KSamplerAdvanced
  const vidSet0 = paramTab.children[1];
  const vSmp = selOf(vidSet0, "采样器");
  ok(!!vSmp, "视频参数里也有「采样器」下拉");
  eq(tube(paramTab.children[1]), true, "图像管线上整块视频参数收起（含视频采样器）");
  pipeBtn("图生视频").dispatch("click");
  await tick(20);
  eq(tube(paramTab.children[1]), false, "切到图生视频 → 视频参数（含采样器）显示");
  vSmp.value = "uni_pc";
  vSmp.dispatch("change");
  await tick(20);
  const vKs = () => app.graph.getNodeById("431").subgraph.nodes[0];
  const vW = (name) => (vKs().widgets.find((w) => w.name === name) || {}).value;
  eq(vW("sampler_name"), "uni_pc", "视频采样器写进 KSamplerAdvanced");
  eq(imgW("sampler_name"), "euler_ancestral", "视频那套不动图像管线的采样器");
  const vRes = selOf(vidSet0, "分辨率");
  ok(!!vRes, "视频参数里有「分辨率」下拉");
  ok(vRes.value === "__rec"
    || vRes.value === pnum("p_video_width") + "x" + pnum("p_video_height"),
    "视频分辨率下拉对得上画布上的宽高（" + vRes.value + "）");
  vRes.value = "832x480";
  vRes.dispatch("change");
  await tick(20);
  eq(pnum("p_video_width"), 832, "视频也走同一套预设（832×480）");
  eq(pnum("p_video_height"), 480, "视频高度跟着写 480");
  eq(pnum("p_width"), 1216, "视频分辨率不动图像那对宽高");
  pipeBtn("文生图").dispatch("click");
  await tick(20);
  // 刷新 / 重开工作流后，采样器选择从本地记忆写回画布
  imgKs().widgets.find((w) => w.name === "sampler_name").value = "heun";
  globalThis.__ccApi.emit("graphConfigured");
  await tick(60);
  eq(imgW("sampler_name"), "euler_ancestral",
    "重开工作流后把记住的采样器写回画布（不再弹回 heun）");
  eq(imgW("scheduler"), "sgm_uniform", "调度器记忆也写回");

  // ---------------------------------------------------------------- 取图同步
  console.log("\n[14] 输出图在管线之间同步（取图 / 同步 / 切管线）");
  mainWin.__ccDockDebug = true;
  const wImg = (k) => app.graph.getNodeById("src_" + k).widgets[0];
  const nodeSrc = (k) => app.graph.getNodeById("src_" + k);
  const setSrcList = (k, list, cur) => {
    const w = wImg(k);
    w.options = { values: list.slice() };
    if (cur !== undefined) w.value = cur;
  };
  // 文生图出的新图：latest 排在 output 列表最前面
  pipeBtn("文生图").dispatch("click");   // 前面的用例把管线停在了别的分栏上
  await tick();
  // 取图节点上当前选中的就是「刚出的那张」，同步要把它传到下游
  setSrcList("i2i", ["new_t2i.png", "old_i2i.png"], "new_t2i.png");
  setSrcList("i2v", ["old_i2v.png", "older.png"], "old_i2v.png");
  setSrcList("flf_start", ["old_s.png"], "old_s.png");
  setSrcList("flf_end", ["old_e.png"], "old_e.png");
  eq(wImg("i2v").value, "old_i2v.png", "同步前下游还是老图");
  const syncBtn2 = [...root().querySelectorAll("BUTTON")].find(
    (b) => b.textContent.indexOf("同步") >= 0);
  ok(!!syncBtn2, "顶栏有「↻ 同步」按钮");
  syncBtn2.dispatch("click");
  await sleep(1300);
  eq(wImg("i2i").value, "new_t2i.png", "文生图的最新图留在图生图取图节点");
  eq(wImg("i2i_fixed").value, "new_t2i.png", "文生图 → 图生图：也同步过去了");
  eq(wImg("i2v").value, "new_t2i.png", "文生图 → 图生视频：同步过去了");
  eq(wImg("flf_start").value, "new_t2i.png", "文生图 → 首尾帧（首帧）也同步了");
  eq(wImg("flf_end").value, "new_t2i.png", "文生图 → 首尾帧（尾帧）先接上同一张");
  ok(wImg("i2v").options.values.indexOf("new_t2i.png") >= 0,
    "新图不在下拉里时也会补进下拉（不会显示空白）");
  // 切到图生图：再点同步，只往下游（图生视频 / 首尾帧）传
  pipeBtn("图生图精修").dispatch("click");
  await tick();
  setSrcList("i2v", ["keep_i2v.png", "new_t2i.png"], "keep_i2v.png");
  // 图生图自己精修出了另一张
  setSrcList("i2i", ["refine_x.png", "new_t2i.png"], "refine_x.png");
  syncBtn2.dispatch("click");
  await sleep(1300);
  eq(wImg("i2v").value, "refine_x.png", "图生图 → 图生视频：用的是图生图的图");
  eq(wImg("flf_start").value, "refine_x.png", "图生图 → 首尾帧（首帧）同步了");
  eq(nodeSrc("i2i").properties.cc_dock_key, "i2i", "图生图取图节点没被自己改掉");
  eq(wImg("i2i_fixed").value, "refine_x.png", "图生图精修 → 图生图：精修完的图能接着 P");
  // 视频管线没有下游：点同步不该动任何东西
  const beforeV = wImg("i2v").value;
  pipeBtn("图生视频").dispatch("click");
  await tick();
  syncBtn2.dispatch("click");
  await sleep(1300);
  eq(wImg("i2v").value, beforeV, "图生视频没有下游，同步不动它自己");
  eq(wImg("flf_start").value, beforeV, "图生视频没有下游，也不动首尾帧");
  pipeBtn("文生图").dispatch("click");
  await tick();
  // 取图按钮同样会同步
  setSrcList("i2i", ["newer_t2i.png", "new_t2i.png"], "newer_t2i.png");
  const takeBtn = [...root().querySelectorAll("BUTTON")].find(
    (b) => b.textContent.indexOf("取图") >= 0);
  ok(!!takeBtn, "顶栏有「⟳ 取图」按钮");
  takeBtn.dispatch("click");
  await sleep(1300);
  eq(wImg("i2v").value, "newer_t2i.png", "「⟳ 取图」也会把最新的图同步下去");

  // 图生图（固定分辨率）：自己那格是它的取图节点（同步/取图都认它），同步只往下游传
  pipeBtn("图生图").dispatch("click");
  await tick();
  setSrcList("i2i", ["newest_i2i.png", "fit_out.png"], "fit_out.png");
  setSrcList("i2i_fixed", ["newest_i2i.png", "fit_old.png"], "fit_old.png");
  setSrcList("i2v", ["keep_i2v.png"], "keep_i2v.png");
  takeBtn.dispatch("click");
  await sleep(1300);
  eq(wImg("i2i_fixed").value, "newest_i2i.png", "「⟳ 取图」把最新那张填进图生图自己的取图节点");
  eq(wImg("i2i").value, "fit_out.png", "  └ 上游那格保持你手动选的图");
  eq(wImg("i2v").value, "newest_i2i.png", "图生图 → 图生视频：同步过去了");
  eq(wImg("flf_start").value, "newest_i2i.png", "图生图 → 首尾帧（首帧）同步了");
  eq(wImg("flf_end").value, "newest_i2i.png", "图生图 → 首尾帧（尾帧）同步了");
  pipeBtn("文生图").dispatch("click");
  await tick();

  // ---------------------------------------------- 刚跑完就同步（不用等下拉开刷新）
  const api = globalThis.__ccApi;
  ok(!!api && typeof api.emit === "function", "测试桩能派发 ComfyUI 事件");
  setSrcList("i2i", ["newer_t2i.png", "new_t2i.png"], "newer_t2i.png");
  setSrcList("i2v", ["old_i2v.png", "older.png"], "old_i2v.png");
  setSrcList("flf_start", ["old_s.png"], "old_s.png");
  setSrcList("flf_end", ["old_e.png"], "old_e.png");
  // 下拉里还没有这张新图（真实环境里刷新是异步的）—— 旧实现这时点了同步没反应
  api.emit("executed", {
    node: "s_t2i", display_node: "s_t2i", prompt_id: "p1",
    output: { images: [{ filename: "refined_00046_.png", subfolder: "", type: "output" }] },
  });
  eq(wImg("i2v").value, "refined_00046_.png [output]",
    "Save 一跑完就写入下游（同一轮事件里立刻生效）");
  await sleep(150);
  eq(wImg("i2i").value, "refined_00046_.png [output]",
    "  └ 图生图的取图也换成刚出的这张");
  eq(wImg("i2i_fixed").value, "refined_00046_.png [output]",
    "  └ 图生图（固定分辨率）那格也换了");
  eq(wImg("flf_end").value, "refined_00046_.png [output]", "  └ 首尾帧尾帧也换了");

  // 下拉刷新落地后：新图排在列表最前，结果保持一致（不回跳）
  setSrcList("i2i", ["refined_00046_.png [output]", "newer_t2i.png"],
    "refined_00046_.png [output]");
  syncBtn2.dispatch("click");
  await sleep(1300);
  eq(wImg("i2v").value, "refined_00046_.png [output]",
    "下拉刷新后同步结果不变（不会回跳）");

  // 另一条管线晚一步跑完：同步传的就是更晚产出的那张（图生图刚出的图不会被旧的顶掉）
  api.emit("executed", {
    node: "s_i2i", display_node: "s_i2i", prompt_id: "p2",
    output: { images: [{ filename: "refine_newer.png", subfolder: "", type: "output" }] },
  });
  await tick();
  syncBtn2.dispatch("click");
  await sleep(1300);
  eq(wImg("i2v").value, "refine_newer.png [output]",
    "后跑的图优先：同步的永远是最后产出的那张");

  // 视频存盘报回来的也是 images（里面是 mp4）：不能当成图片记下来
  api.emit("executed", {
    node: "s_i2v", display_node: "s_i2v", prompt_id: "p3",
    output: {
      images: [{ filename: "total_i2v_00001_.mp4", subfolder: "video", type: "output" }],
      animated: [true],
    },
  });
  await tick();
  syncBtn2.dispatch("click");
  await sleep(1300);
  eq(wImg("i2v").value, "refine_newer.png [output]",
    "视频 Save 报的 mp4 不算图：传的还是最后那张图");

  // 换工作流后记录清零 + 只认图片（视频文件 / 占位符不能被当成图）
  api.emit("graphConfigured", {});
  await tick();
  setSrcList("i2i", ["_output_images_will_be_put_here [output]"],
    "_output_images_will_be_put_here [output]");
  setSrcList("i2i_fixed", ["_output_images_will_be_put_here [output]"],
    "_output_images_will_be_put_here [output]");
  setSrcList("i2v", ["total_i2v_00001_.mp4 [output]", "real_pic.png [output]"],
    "total_i2v_00001_.mp4 [output]");
  setSrcList("flf_start", ["old_s.png"], "old_s.png");
  takeBtn.dispatch("click");
  await sleep(1300);
  eq(wImg("flf_start").value, "real_pic.png [output]",
    "视频文件 / 占位符不会被当成图片同步过去");
  eq(wImg("i2i").value, "real_pic.png [output]", "  └ 占位符那格也被真图替掉");

  // 刷新下拉不冲掉你手动选的图（首尾帧那一对 / 图生图正在用的源图）
  pipeBtn("图生视频").dispatch("click");
  await tick();
  setSrcList("i2v", ["newest_i2v.png", "old_i2v.png"], "old_i2v.png");
  setSrcList("i2i", ["newest_i2i.png", "keep_i2i.png"], "keep_i2i.png");
  setSrcList("flf_start", ["newest_s.png", "pick_start.png"], "pick_start.png");
  setSrcList("flf_end", ["newest_e.png", "pick_end.png"], "pick_end.png");
  takeBtn.dispatch("click");
  await sleep(1300);
  eq(wImg("i2v").value, "newest_i2v.png",
    "⟳ 取图：当前栏那格换成 output 里最新那张");
  eq(wImg("i2i").value, "keep_i2i.png", "别的栏不被冲掉（图生图在用的源图还在）");
  eq(wImg("flf_start").value, "pick_start.png", "别的栏不被冲掉（首帧还是你选的）");
  eq(wImg("flf_end").value, "pick_end.png", "别的栏不被冲掉（尾帧还是你选的）");

  console.log("\n[15] 高清：倍数语义 / 分块自适应 / 长宽互换");
  pipeBtn("文生图").dispatch("click");
  await tick(20);
  // 先用新的分辨率下拉把画布设回 1216×832（这节后面都按这个基准算分块）
  {
    const rs = selOf(genSec, "分辨率");
    ok(!!rs, "分辨率是下拉菜单（不是两个裸数字）");
    rs.value = "1216x832";
    rs.dispatch("change");
    await tick(20);
    eq(app.graph.getNodeById("p_width").widgets[0].value, 1216,
      "下拉选 1216×832 → 宽写进画布");
    eq(app.graph.getNodeById("p_height").widgets[0].value, 832,
      "下拉选 1216×832 → 高写进画布");
  }
  const usdu = app.graph.getNodeById(205);
  const roOf = (label) => {
    let hit = null;
    walk(upSec, (n) => {
      if (hit || n.tagName !== "SPAN" || !n.classList.contains("ccd-ro")) return;
      const name = n.parentNode && n.parentNode.children[0];
      if (name && name.textContent === label) hit = n;
    });
    return hit;
  };
  const setNum = async (sec, label, v) => {
    const inp = fieldOf(sec, label).querySelector("input");
    inp.value = String(v);
    inp.dispatch("change", {});
    await tick(10);
  };
  const num = (id) => app.graph.getNodeById(id).widgets[0].value;
  // [13] 刚重置过：倍数 2、分块勾着「自动」
  eq(num("p_upscale_factor"), 2, "倍数默认 2（填几就是几倍，链子末尾缩 1/4）");
  ok(/填几就是几倍/.test(String(fieldOf(upSec, "高清倍数").querySelector("input").title)),
    "倍数的悬停说明写清了「填 2 就是 2 倍、以前 2 出来是 4 倍」");
  eq(num("p_upscale_tile"), 1216, "分块自动算出 1216（1216×832 × 2 → 长边 2432 切 2 块）");
  eq(usdu.widgets[0].value, 1216, "分块大小写进了分块精修节点（tile_width）");
  eq(usdu.widgets[1].value, 1216, "分块上下一样（tile_height）");
  eq(String(roOf("输出尺寸").textContent), "2432×1664（1216×832 × 2）",
    "只读行「输出尺寸」显示最终像素");
  eq(String(roOf("实际分块").textContent), "1216×1216（自动）", "只读行「实际分块」标了自动");

  // 分辨率一变，分块跟着变（不用手动数）
  await setNum(genSec, "宽", 512);
  eq(num("p_upscale_tile"), 1024, "宽改成 512 → 分块自动跟到下限 1024");
  eq(usdu.widgets[0].value, 1024, "子图里的分块精修也跟着改成 1024");
  eq(String(roOf("输出尺寸").textContent), "1024×1664（512×832 × 2）", "输出尺寸跟着分辨率走");

  // 取消「自动」→ 手填说了算
  const tileRow = fieldOf(upSec, "分块大小");
  ok(!!tileRow, "高清参数里有「分块大小」一行");
  const autoChk = tileRow.querySelectorAll("input").find((n) => n.attrs.type === "checkbox");
  ok(!!autoChk, "分块大小右边有「自动」勾选框");
  autoChk.checked = false;
  autoChk.dispatch("change", {});
  await tick(10);
  await setNum(genSec, "宽", 1216);
  eq(num("p_upscale_tile"), 1024, "取消自动后，改分辨率不再覆盖手填的分块");
  eq(String(roOf("实际分块").textContent), "1024×1024（手动）", "只读行改成「手动」");
  await setNum(upSec, "分块大小", 1280);
  eq(usdu.widgets[0].value, 1280, "手填 1280 → 分块精修按 1280 走");
  eq(String(roOf("实际分块").textContent), "1280×1280（手动）", "只读行显示手填值");

  // ⇄ 长宽互换（竖图）
  const swapImg = fieldOf(genSec, "高").querySelector("button");
  ok(!!swapImg, "「高」那一行有 ⇄ 按钮");
  ok(/交换长宽/.test(String(swapImg.getAttribute("title") || swapImg.title || "")),
    "⇄ 的悬停说明写了交换长宽");
  swapImg.dispatch("click");
  await tick(20);
  eq(num("p_width"), 832, "⇄ 后宽 = 原来的高（832）");
  eq(num("p_height"), 1216, "⇄ 后高 = 原来的宽（1216）→ 竖图");
  eq(num("p_upscale_tile"), 1280, "手动模式下 ⇄ 不动分块");

  // 重置默认值也把「自动」勾回来
  resetBtn.dispatch("click");
  await tick(20);
  eq(num("p_width"), 1024, "重置：宽回到当前模型推荐分辨率（Illustrious 1024）");
  eq(num("p_height"), 1024, "重置：高回到 1024（模型推荐，不是老的 1216×832）");
  eq(autoChk.checked, true, "重置：分块的「自动」勾回来");
  eq(num("p_upscale_tile"), 1024, "重置：分块按模型推荐分辨率自动算（1024×1024×2 → 1024）");
  eq(usdu.widgets[0].value, 1024, "重置：分块精修节点也跟着回到 1024");

  // 视频那对长宽是独立的
  const vidSet = paramTab.children[1];
  await setNum(vidSet, "宽", 832);
  await setNum(vidSet, "高", 480);
  const swapVid = fieldOf(vidSet, "高").querySelector("button");
  ok(!!swapVid, "视频「高」那一行也有 ⇄");
  swapVid.dispatch("click");
  await tick(20);
  eq(num("p_video_width"), 480, "视频 ⇄：宽 = 原来的高（480）");
  eq(num("p_video_height"), 832, "视频 ⇄：高 = 原来的宽（832）");
  eq(num("p_width"), 1024, "视频 ⇄ 不带跑图像那对（宽还是 1024）");
  eq(num("p_upscale_tile"), 1024, "视频 ⇄ 不影响图像的分块大小");

  // ------------------------------------------------------------ 插件形态
  console.log("\n[16] 插件形态：版本号 / 缺插件黄条 / 一键生成蓝图");
  const clsFind = (sel) => {
    let hit = null;
    walk(root(), (n) => {
      if (!hit && n.classList.contains(sel)) hit = n;
    });
    return hit;
  };
  const verEl = clsFind("ccd-ver");
  ok(!!verEl && /^v\d+\.\d+\.\d+$/.test(verEl.textContent || ""),
    "标题栏有插件版本号：" + (verEl ? verEl.textContent : "没有"));
  const warnEl = clsFind("ccd-missing");
  ok(!!warnEl, "有缺插件黄条");
  ok(!!clsFind("ccd-lora-status") && !warnEl.classList.contains("ccd-lora-status"),
    "黄条类名与 LoRA 状态提示分开（不串样式）");
  eq(warnEl.classList.contains("ccd-hide"), true, "没缺件时黄条收起");
  ok(!!byText("🏗 生成 / 更新蓝图", "BUTTON"), "说明页有「生成 / 更新蓝图」按钮");
  ok(!!byText("🧱 以默认值重建", "BUTTON"), "说明页有「以默认值重建」按钮");

  // 造一个「缺 YogurtStringConcat」的画布 + 一个 UUID 类型的子图实例
  const known = {};
  const collect = (g) => {
    for (const n of g.nodes || []) {
      if (n.type && !/^[0-9a-f]{8}-[0-9a-f]{4}-/i.test(n.type)) known[n.type] = 1;
      if (n.subgraph) collect(n.subgraph);
    }
  };
  collect(app.graph);
  const reg = {};
  for (const t of Object.keys(known)) {
    if (t !== "YogurtStringConcat") reg[t] = 1;
  }
  globalThis.LiteGraph = { registered_node_types: reg };
  app.graph.nodes.push({
    id: 999, type: "0b7a1c10-0001-4a01-9c01-000000000001", mode: 0,
  });
  await sleep(1400);                       // 等面板轮询里的一次 sync
  eq(warnEl.classList.contains("ccd-hide"), false, "缺插件时黄条弹出来");
  ok(String(warnEl.textContent).indexOf("YogurtStringConcat") >= 0,
    "黄条点名缺的那一种");
  const missNum = /缺少\s*(\d+)\s*种/.exec(String(warnEl.textContent));
  eq(missNum ? missNum[1] : "?", "1", "只报这 1 个缺件");
  ok(String(warnEl.textContent).indexOf("000000000001") < 0,
    "子图实例（UUID 类型）不算缺件");
  app.graph.nodes.pop();
  delete globalThis.LiteGraph;
  await sleep(1400);
  eq(warnEl.classList.contains("ccd-hide"), true, "补齐后黄条自己收起来");

  // 点「生成 / 更新蓝图」：打插件的本地接口，结果写在按钮旁边
  const calls = [];
      globalThis.fetch = async (url, opt) => {
        // 面板「队列」那排会轮询 /queue：只把蓝图请求记进 calls，
        // 其他请求照实回一个空队列，别让轮询冲乱请求计数
        if (String(url).indexOf("/cc_dashboard/blueprint") < 0) {
          return { status: 200, ok: true, json: async () => ({ queue_running: [], queue_pending: [] }) };
        }
        calls.push([url, opt]);
        return {
      status: 200,
      json: async () => ({
        ok: true, path: "D:\\x\\00_总控台.json", backup: "D:\\x\\bak.json",
        report: { nodes: 89, links: 151, carried: 55 }, workflow: { nodes: [] },
      }),
    };
  };
  byText("🏗 生成 / 更新蓝图", "BUTTON").dispatch("click");
  await tick(30);
  eq(calls.length, 1, "点按钮发了 1 次请求");
  eq(calls[0][0], "/cc_dashboard/blueprint", "请求打到插件的本地接口");
  eq(JSON.parse(calls[0][1].body).mode, "update", "默认走「结转重建」");
  const toolSt = clsFind("ccd-tool-status");
  ok(!!toolSt && /已生成/.test(toolSt.textContent || ""),
    "按钮旁边给出结果：" + (toolSt ? toolSt.textContent : "没有状态行"));
  byText("🧱 以默认值重建", "BUTTON").dispatch("click");
  await tick(30);
  eq(calls.length, 2, "再点一次「以默认值重建」");
  eq(JSON.parse(calls[1][1].body).mode, "fresh", "「以默认值重建」传 fresh");

  // ------------------------------------------------- 旧蓝图橙条 + 一键重建
  console.log("\n[17] 画布上那份还是旧蓝图时，面板要说出来");
  const driftEl = clsFind("ccd-drift");
  ok(!!driftEl, "面板里有旧蓝图橙条");
  ok(!!driftEl.querySelector(".ccd-drift-fix"), "橙条右边有按钮");
  eq(driftEl.classList.contains("ccd-hide"), true, "当前（没有高清子图信息）不误报");

  // 造一份「旧高清链」：分块精修后面还挂着 ImageUpscaleWithModel + ImageScaleBy，
  // 而且没有 v6.4 加上去的 ColorMatch —— 就是用户 9/13 那份 4 倍链的样子
  const OLD_UP_NODES = ["CR Upscale Image", "KSampler", "VAEEncode", "VAEDecode",
    "UltimateSDUpscaleNoUpscale", "ImageUpscaleWithModel", "ImageScaleBy"];
  const oldUp = {
    id: "sg_old_up", name: "高清化", isRootGraph: false,
    nodes: OLD_UP_NODES.map((t, i) => ({ id: "old_" + i, type: t, mode: 0, widgets: [] })),
    getNodeById: () => null,
  };
  const oldUpNode = {
    id: 998, type: "0b7a1c10-0001-4a01-9c01-000000000009", title: "高清化",
    mode: 0, subgraph: oldUp,
  };
  app.graph.nodes.push(oldUpNode);
  app.graph.extra = {};                 // 老前端恢复出来的那份没有版本戳
  await sleep(1400);                    // 等面板轮询里的一次 sync
  eq(driftEl.classList.contains("ccd-hide"), false, "旧高清链 → 橙条弹出来");
  const driftTxt = () => String(driftEl.querySelector(".ccd-drift-txt").textContent || "");
  ok(driftTxt().indexOf("4 倍") >= 0 && driftTxt().indexOf("× 2") >= 0,
    "橙条点明「实际 = 面板倍数 × 2」：" + driftTxt());
  ok(driftTxt().indexOf("ImageUpscaleWithModel") >= 0
    || driftTxt().indexOf("ColorMatch") >= 0,
    "橙条顺带点名旧链和当前链的节点差异");

  // 只读的「输出尺寸」这时要报真会出来的尺寸（1024×1024 × 2 × 2 = 4096）
  eq(num("p_width"), 1024, "前提：宽是 1024（[15] 末尾重置过）");
  eq(num("p_upscale_factor"), 2, "前提：倍数 2");
  const sizeTxt = () => String(roOf("输出尺寸").textContent || "");
  ok(sizeTxt().indexOf("4096×4096") === 0,
    "旧链下「输出尺寸」改成报真实尺寸：" + sizeTxt());

  // 点「载入最新蓝图」：请求要带上画布现况（插件按它做参数结转）
  // 先来一份「序列化不出来」的画布（带环）：重建照样要发出去，只是退回让插件读磁盘
  const circular = { marker: "circular" };
  circular.self = circular;
  app.graph.serialize = () => circular;
  driftEl.querySelector(".ccd-drift-fix").dispatch("click");
  await tick(40);
  eq(calls.length, 3, "画布现况序列化不出来时也照样发请求");
  eq(JSON.parse(calls[2][1].body).canvas, undefined, "那份就退回让插件读磁盘");

  app.graph.serialize = () => ({ marker: "from-canvas", nodes: [{ id: 1 }] });
  driftEl.querySelector(".ccd-drift-fix").dispatch("click");
  await tick(40);
  eq(calls.length, 4, "点橙条按钮又发了 1 次请求");
  eq(calls[2][0], "/cc_dashboard/blueprint", "还是打插件的本地接口");
  const body4 = JSON.parse(calls[3][1].body);
  eq(body4.mode, "update", "默认按画布现况结转重建");
  eq(body4.canvas && body4.canvas.marker, "from-canvas", "请求体里带了画布现况");

  // 换回「当前蓝图」：六个节点齐全 + 版本戳到位 → 橙条自己收起来
  app.graph.nodes.pop();
  oldUp.nodes = ["CR Upscale Image", "KSampler", "VAEEncode", "VAEDecode",
    "UltimateSDUpscaleNoUpscale", "ColorMatch"]
    .map((t, i) => ({ id: "cur_" + i, type: t, mode: 0, widgets: [] }));
  app.graph.nodes.push(oldUpNode);
  // 版本戳 ≥ 面板当前的 BLUEPRINT_REV 才算「跟上」（这里用一个大数，免得每次
  // 蓝图结构升级都要回来改测试里的硬编码）
  app.graph.extra = { cc_dashboard_blueprint: { rev: 999, tag: "current" } };
  await sleep(1400);
  eq(driftEl.classList.contains("ccd-hide"), true, "结构对上了 → 橙条收起来");
  ok(sizeTxt().indexOf("2048×2048") === 0,
    "「输出尺寸」回到按倍数算的真实口径：" + sizeTxt());

  // 版本戳落后也算旧（光看结构认不出来的那些改动靠它兜底）
  app.graph.extra = { cc_dashboard_blueprint: { rev: 1 } };
  await sleep(1400);
  eq(driftEl.classList.contains("ccd-hide"), false, "版本戳落后 → 橙条弹出来");
  ok(driftTxt().indexOf("蓝图版本") >= 0, "橙条写出「蓝图版本」：" + driftTxt());
  app.graph.nodes.pop();
  app.graph.extra = {};
  await sleep(1400);
  eq(driftEl.classList.contains("ccd-hide"), true, "没有高清子图信息时不当成旧蓝图");

  // 视频那条链里本来就有 ImageScaleBy（放大模型放大之后再缩回目标倍数），
  // 不能因为「高清化」三个字就把「视频高清化」也当成图像高清链 —— v1.5.0 修掉的误报
  const vidUp = {
    id: "sg_vid_up", name: "视频高清化", isRootGraph: false,
    nodes: ["UpscaleModelLoader", "UpscaleWithModelAdvanced", "ImageScaleBy"]
      .map((t, i) => ({ id: "vu_" + i, type: t, mode: 0, widgets: [] })),
    getNodeById: () => null,
  };
  app.graph.nodes.push({
    id: 997, type: "0b7a1c10-0001-4a01-9c01-00000000000b", title: "视频高清化",
    mode: 0, subgraph: vidUp,
  });
  app.graph.extra = { cc_dashboard_blueprint: { rev: 999, tag: "current" } };
  await sleep(1400);
  eq(driftEl.classList.contains("ccd-hide"), true,
    "只有视频高清化（里面也有 ImageScaleBy）时不报「图像高清链多绕一段」");
  app.graph.nodes.pop();
  app.graph.extra = {};
  await sleep(1400);

  console.log("\n[18] 重开工作流后 LoRA 行重绑（v6.6：选了不丢 / 开开关不冲掉）");
  {
    const gi = app.graph.nodes.findIndex((n) => n.properties
      && n.properties.cc_dock_role === "lora_group"
      && n.properties.cc_dock_key === "image");
    ok(gi >= 0, "画布上有图像 LoRA 组");
    const oldNode = app.graph.nodes[gi];
    const oldRow0 = oldNode.widgets[0].value.lora;   // 换节点前它自己的值，用来验证「没被误写」
    const colEl = root().querySelectorAll(".ccd-lora-col")[0];
    const rowBox = colEl.children[1];
    const rowEl = rowBox.children[0];
    // 真前端「重开工作流」= 同一个 graph 对象里节点被换成新对象，行数往往一模一样
    const fresh = loraNode("image", [{ i: 0, lora: "", on: false }, { i: 1, lora: "", on: false }]);
    app.graph.nodes[gi] = fresh;

    const pickEl = rowEl.children[1];
    pickEl.value = "hiyuki02.safetensors";
    pickEl.dispatch("change", {});
    await tick(10);
    eq(fresh.widgets[0].value.lora, "hiyuki02.safetensors", "选 LoRA 写进新节点");
    eq(oldNode.widgets[0].value.lora, oldRow0, "旧节点不再被误写（以前写向脱离画布的旧对象）");

    const onEl = rowBox.children[0].children[0];
    onEl.checked = true;
    onEl.dispatch("change", {});
    await tick(10);
    eq(fresh.widgets[0].value.on, true, "开开关写的是新节点的 on");
    eq(fresh.widgets[0].value.lora, "hiyuki02.safetensors", "开开关不会把刚选的 LoRA 冲掉");

    await sleep(1400);
    const rowEl2 = rowBox.children[0];
    ok(rowEl2 !== rowEl, "轮询发现节点被换掉后重建了 LoRA 行");
    eq(rowEl2.children[1].value, "hiyuki02.safetensors", "重建后的行显示新节点的值");
    eq(rowEl2.children[0].checked, true, "重建后的勾选框跟着新节点");
  }

  console.log("\n[19] 队列一排（数量 / 运行 / 插队 / 停止 / 活动任务）");
  {
    const qbar = root().querySelector(".ccd-qbar");
    ok(!!qbar, "标题栏下面有队列那一排");
    const qNumEl = qbar.querySelector(".ccd-q-num");
    const steps = qbar.querySelectorAll(".ccd-q-step");
    const runEl = qbar.querySelector(".ccd-q-run");
    const frontEl = qbar.querySelector(".ccd-q-front");
    const stopEl = qbar.querySelector(".ccd-q-stop");
    const countEl = qbar.querySelector(".ccd-q-count");
    const msgEl = qbar.querySelector(".ccd-q-msg");
    ok(!!(qNumEl && runEl && frontEl && stopEl && countEl), "数量 / 运行 / 插队 / 停止 / 活动任务 都在");
    eq(steps.length, 2, "数量旁边有 ▲ / ▼ 两个按钮");
    eq(qNumEl.value, "1", "数量默认 1（localStorage 里没有时）");

    // 数量：手填 → 记住；▲ 翻倍、▼ 减半（和 ComfyUI 那个框一致）
    qNumEl.value = "3";
    qNumEl.dispatch("change", {});
    await tick(4);
    eq(JSON.parse(localStorage.getItem("cc_dock_ui_v1")).batch, 3, "手填数量写进 localStorage");
    eq(runEl.textContent, "▶ 运行 ×3", "运行按钮上标出数量");
    steps[0].dispatch("click", {});
    await tick(4);
    eq(qNumEl.value, "6", "▲ 翻倍");
    steps[1].dispatch("click", {});
    await tick(4);
    eq(qNumEl.value, "3", "▼ 减半");

    // 运行：走 app.queuePrompt(number, batchCount)，数量由面板决定
    app.queueCalls.length = 0;
    runEl.dispatch("click", {});
    await tick(4);
    eq(app.queueCalls.length, 1, "点「运行」排了一次队");
    eq(app.queueCalls[0].number, 0, "运行 = 排到队尾（number 0）");
    eq(app.queueCalls[0].batch, 3, "排队用的是面板上的数量 3");
    ok(msgEl.textContent.indexOf("已排队") === 0, "排完有提示：" + msgEl.textContent);

    // Shift + 运行 = 插队；⇥ 插队按钮同理（number -1）
    runEl.dispatch("click", { shiftKey: true });
    frontEl.dispatch("click", {});
    await tick(4);
    eq(app.queueCalls.length, 3, "Shift+运行 / ⇥ 插队 各排一次");
    eq(app.queueCalls[1].number, -1, "Shift+运行 排到队首");
    eq(app.queueCalls[2].number, -1, "⇥ 插队 排到队首");

    // app.queuePrompt 不在时退到命令总线
    const keepQueuePrompt = app.queuePrompt;
    delete app.queuePrompt;
    app.extensionManager.command.calls.length = 0;
    runEl.dispatch("click", {});
    await tick(4);
    eq(app.extensionManager.command.calls.length, 1, "拿不到 app.queuePrompt 时退到命令总线");
    eq(app.extensionManager.command.calls[0].id, "Comfy.QueuePrompt", "兜底用的是 Comfy.QueuePrompt");
    app.queuePrompt = keepQueuePrompt;

    // 停止：走 Comfy.Interrupt
    app.extensionManager.command.calls.length = 0;
    stopEl.dispatch("click", {});
    await tick(6);
    eq(app.extensionManager.command.calls.length, 1, "点「停止」发一次中断");
    eq(app.extensionManager.command.calls[0].id, "Comfy.Interrupt", "中断用的是 Comfy.Interrupt");
    ok(msgEl.textContent.indexOf("已中断") === 0, "中断后有提示：" + msgEl.textContent);

    // 命令入口的两种叫法都要认：只有 executeCommand 的前端也得能中断
    {
      const cmd = app.extensionManager.command;
      const keep = cmd.execute;
      const alt = { calls: [] };
      delete cmd.execute;
      cmd.executeCommand = function (id, args) { alt.calls.push({ id, args }); return Promise.resolve(true); };
      stopEl.dispatch("click", {});
      await tick(6);
      eq(alt.calls.length, 1, "只有 executeCommand 的前端也能中断");
      eq(alt.calls[0].id, "Comfy.Interrupt", "两种命令入口都打到 Comfy.Interrupt");
      delete cmd.executeCommand;
      cmd.execute = keep;
    }

    // 活动任务数：轮询 /queue 后画到药丸上（跑着 1 个 + 等着 2 个 = 3）
    const keepFetch = globalThis.fetch;
    globalThis.fetch = async () => ({
      ok: true,
      json: async () => ({ queue_running: [{}], queue_pending: [{}, {}] }),
    });
    // 真前端队列一动就推 status：这条链路把刷新做成即时的（否则要等轮询那 1.2s）
    globalThis.__ccApi.emit("status", {});
    await tick(20);
    eq(countEl.textContent, "3 个活动任务", "活动任务数 = 正在跑 + 等待");
    eq(countEl.classList.contains("ccd-busy"), true, "有任务时药丸高亮");
    globalThis.fetch = async () => ({ ok: true, json: async () => ({ queue_running: [], queue_pending: [] }) });
    globalThis.__ccApi.emit("status", {});
    await tick(20);
    eq(countEl.textContent, "0 个活动任务", "队列空了数字跟着回落");
    eq(countEl.classList.contains("ccd-busy"), false, "空了不再高亮");
    globalThis.fetch = keepFetch;
  }

  console.log("\n[20] 独立窗口里编辑要真的落到画布（v6.8：focused 认自己那份文档）");
  {
    const segs = root().querySelectorAll(".ccd-seg");
    ok(segs.length > 0, "提示词分段行在");
    const ta = segs[0].children[1];                 // 第 1 段的手填框
    const swA = app.graph.nodes.find((n) => n.id === "sw_image_pos_1");
    ok(!!swA, "画布上有第 1 段的开关节点");
    const before = swA.widgets[1].value;            // text_false = 手填文字

    byText("⧉").dispatch("click");
    await tick(40);
    ok(pipWindows[pipWindows.length - 1].document.body.children.includes(root()),
      "面板在独立窗口里");

    // 正在输入：光标还在框里时，同步不许把内容盖回画布旧值
    ta.focus();
    ta.value = "独立窗口里新写的一段";
    await sleep(1400);
    eq(ta.value, "独立窗口里新写的一段", "输入框里的字没被同步盖回去");
    eq(swA.widgets[1].value, before, "还没失焦时画布保持原值（不提前写）");

    // 失焦（change）：这次修改要落到画布上
    ta.dispatch("change", {});
    await tick(10);
    eq(swA.widgets[1].value, "独立窗口里新写的一段", "提交后写进了画布节点");

    // 没失焦就把独立窗口关了：也要先把这段字提交掉
    ta.focus();
    ta.value = "关窗前那一下";
    pipWindows[pipWindows.length - 1].dispatch("pagehide", {});
    await tick(40);
    ok(mainDoc.body.children.includes(root()), "关窗后面板自动收回主页面");
    eq(swA.widgets[1].value, "关窗前那一下", "关窗前没失焦的编辑也被提交了");

    // 独立窗口失去焦点（回到主窗口跑图）：同样要先提交
    byText("⧉").dispatch("click");
    await tick(40);
    const pipWin2 = pipWindows[pipWindows.length - 1];
    ok(pipWin2.document.body.children.includes(root()), "又进了一次独立窗口");
    ta.focus();
    ta.value = "切窗口那次";
    pipWin2.dispatch("blur", {});
    await tick(10);
    eq(swA.widgets[1].value, "切窗口那次", "独立窗口失焦时也提交了没失焦的编辑");
    byText("⧉").dispatch("click");
    await tick(40);
  }

  console.log("\n[21] 视频后处理：视频高清化 / 视频补帧（v1.4.0）");
  {
    const roTextOf = (sec, label) => {
      let hit = null;
      walk(sec, (n) => {
        if (hit || n.tagName !== "SPAN") return;
        const c = n.children || [];
        if (c.length === 2 && c[0].textContent === label) hit = c[1];
      });
      return hit ? hit.textContent : null;
    };
    const instsOf = (k) => app.graph.nodes.filter(
      (n) => n.properties.cc_dock_role === "module"
        && n.properties.cc_dock_key === k);
    pipeBtn("图生视频").dispatch("click");
    await tick(20);
    const vSet = paramTab.children[1];
    const vfiSec = secOf(vSet, "视频补帧参数");
    const vupSec = secOf(vSet, "视频高清参数");
    ok(!!vfiSec && !!vupSec, "参数页分成 视频生成 / 视频补帧 / 视频高清 三块");
    eq(modBtn("视频高清化").classList.contains("ccd-hide"), false,
      "视频管线出现「视频高清化」按钮");
    eq(modBtn("视频补帧").classList.contains("ccd-hide"), false,
      "视频管线出现「视频补帧」按钮");
    eq(modBtn("姿势").classList.contains("ccd-hide"), true,
      "视频管线上图像模块按钮收起（姿势）");
    eq(modBtn("高清化").classList.contains("ccd-hide"), true,
      "视频管线上图像那个「高清化」也收起");
    eq(tube(vfiSec), true, "补帧模块关着 → 补帧参数收起");
    eq(tube(vupSec), true, "视频高清模块关着 → 视频高清参数收起");

    await setMod("视频高清化", true);
    await setMod("视频补帧", true);
    eq(tube(vupSec), false, "打开视频高清化 → 参数出现");
    eq(tube(vfiSec), false, "打开视频补帧 → 参数出现");
    eq(instsOf("vfi").length, 3, "三条视频管线各有一个补帧实例");
    eq(instsOf("vfi").every((n) => n.mode === 0), true,
      "一个开关把三个补帧实例一起打开");
    eq(instsOf("vupscale").length, 3, "三条视频管线各有一个视频高清化实例");
    eq(instsOf("vupscale").every((n) => n.mode === 0), true,
      "一个开关把三个视频高清化实例一起打开");

    const mInp = fieldOf(vfiSec, "补帧倍数").querySelector("input");
    mInp.value = "3";
    mInp.dispatch("change");
    await tick(20);
    eq(pnum("p_vfi_multiplier"), 3, "补帧倍数写进画布参数节点");
    const vLen = pnum("p_video_length"), vFps = pnum("p_video_fps");
    eq(roTextOf(vfiSec, "补帧后"),
      Math.round((vLen - 1) * 3 + 1) + " 帧 / " + (vFps * 3) + " fps（"
        + vLen + " 帧 ×3，时长不变）",
      "只读行算出补帧后的帧数 / 帧率（时长不变）");
    mInp.value = "4";
    mInp.dispatch("change");
    await tick(20);
    const mRow = fieldOf(vfiSec, "补帧倍数");
    const wEl = mRow && mRow.querySelector(".ccd-warn-txt");
    ok(!!wEl && /拖影/.test(String(wEl.textContent)),
      "补帧倍数 ≥4 会挂醒目提示（得到 "
        + (wEl ? JSON.stringify(String(wEl.textContent)) : "没有提醒元素") + "）");
    mInp.value = "2";
    mInp.dispatch("change");
    await tick(20);

    const fInp = fieldOf(vupSec, "目标倍数").querySelector("input");
    fInp.value = "1.5";
    fInp.dispatch("change");
    await tick(20);
    eq(pnum("p_video_upscale_factor"), 1.5, "目标倍数写进画布参数节点");
    const vw = pnum("p_video_width"), vh = pnum("p_video_height");
    const roTxt = String(roTextOf(vupSec, "输出尺寸"));
    ok(roTxt.indexOf(Math.round(vw * 1.5) + "×" + Math.round(vh * 1.5)) === 0,
      "只读行算出高清后的尺寸：" + roTxt);
    ok(/缩回系数 0.375/.test(roTxt),
      "只读行标出「目标 ÷ 模型倍率」的实际缩回系数：" + roTxt);
    const bInp = fieldOf(vupSec, "每批帧数").querySelector("input");
    bInp.value = "2";
    bInp.dispatch("change");
    await tick(20);
    eq(pnum("p_video_upscale_batch"), 2, "每批帧数写进画布参数节点");
    const tInp = fieldOf(vupSec, "分块大小").querySelector("input");
    tInp.value = "384";
    tInp.dispatch("change");
    await tick(20);
    eq(pnum("p_video_upscale_tile"), 384, "分块大小写进画布参数节点");
    ok(/0 = 自动|自动/.test(String(fieldOf(vupSec, "分块大小").querySelector("input").title || "")),
      "分块大小的悬停说明里写了「0 = 自动」");

    await setMod("视频补帧", false);
    eq(instsOf("vfi").every((n) => n.mode === 4), true,
      "关掉补帧 → 三个实例一起旁路（帧 / 帧率原样透传）");
    eq(tube(vfiSec), true, "关掉补帧 → 补帧参数收起");
    eq(tube(vupSec), false, "视频高清还开着 → 那块参数还在");

    // 图像管线：这两个按钮不该出现，视频参数也要收起
    pipeBtn("文生图").dispatch("click");
    await tick(20);
    eq(modBtn("视频补帧").classList.contains("ccd-hide"), true,
      "切回文生图 → 视频补帧按钮收起");
    eq(modBtn("视频高清化").classList.contains("ccd-hide"), true,
      "切回文生图 → 视频高清化按钮收起");
    eq(tube(paramTab.children[1]), true, "切回文生图 → 整块视频参数收起");
    eq(modBtn("高清化").classList.contains("ccd-hide"), false,
      "图像那个「高清化」按钮回来");
  }

  console.log("\n[22] 图像模型 / 视频模型分开（视频 high + low 成对，v1.5.0）");
  {
    const groupOf = (labelText) => {
      let hit = null;
      walk(root(), (n) => {
        if (hit || !n.classList.contains("ccd-group")) return;
        // v1.9.0 起模型那一格是「模型行 + 外挂资源行」，label 在里面一层
        walk(n, (c) => {
          if (!hit && c.tagName === "LABEL" && c.textContent === labelText) hit = n;
        });
      });
      return hit;
    };
    // 模型行（外挂资源行是同一个分组框里的第二条）
    const modelRow = (g) => (g.children || []).find(
      (c) => c.classList.contains("ccd-row")) || g;
    const selectsIn = (box) => {
      const out = [];
      walk(box, (n) => { if (n.tagName === "SELECT") out.push(n); });
      return out;
    };
    const dig = (box, pred) => {
      let hit = null;
      walk(box, (n) => { if (!hit && pred(n)) hit = n; });
      return hit;
    };
    const unetOf = (k) => {
      const n = app.graph.nodes.find((x) => x.properties
        && x.properties.cc_dock_role === "unet_slot"
        && x.properties.cc_dock_key === k);
      return n ? n.widgets[0].value : null;
    };
    const imgG = groupOf("图像模型");
    const vidG = groupOf("视频模型");
    ok(!!imgG && !!vidG, "顶栏把模型拆成「图像模型」和「视频模型」两块");

    pipeBtn("文生图").dispatch("click");
    await tick(20);
    eq(imgG.classList.contains("ccd-hide"), false, "图像管线：显示图像模型");
    eq(vidG.classList.contains("ccd-hide"), true, "图像管线：收起视频模型");
    eq(selectsIn(modelRow(imgG))[0].children.length, MODELS.length,
      "图像模型下拉还是那套 ckpt");

    pipeBtn("图生视频").dispatch("click");
    await tick(20);
    eq(imgG.classList.contains("ccd-hide"), true, "视频管线：收起图像模型");
    eq(vidG.classList.contains("ccd-hide"), false, "视频管线：显示视频模型");
    const vSels = selectsIn(modelRow(vidG));
    eq(vSels.length, 2, "视频模型区是 high / low 两个下拉");
    const hiSel = vSels[0], loSel = vSels[1];
    eq(hiSel.children.length, UNETS.length, "high 下拉列出全部 UNET");
    eq(hiSel.value, UNETS[1], "high 下拉选中画布上的值");
    eq(loSel.value, UNETS[2], "low 下拉选中画布上的值");
    eq(vidG.classList.contains("ccd-vmodel-bad"), false, "成套时不给警告底色");

    // ⇄ 成对：默认开着，改 high 要把 low 一起换成配对的
    hiSel.value = UNETS[3];
    hiSel.dispatch("change", {});
    await tick(20);
    eq(unetOf("video_high"), UNETS[3], "high 写进画布 406");
    eq(unetOf("video_low"), UNETS[4], "成对联动：low 自动换成配对的那个");
    eq(loSel.value, UNETS[4], "low 下拉跟着显示");

    // 拆开成对：只改一个，另一个不动
    const pairChk = dig(vidG, (n) => n.tagName === "INPUT");
    ok(!!pairChk, "视频模型区有「⇄ 成对」勾选框");
    pairChk.checked = false;
    pairChk.dispatch("change", {});
    await tick(20);
    loSel.value = UNETS[2];
    loSel.dispatch("change", {});
    await tick(20);
    eq(unetOf("video_low"), UNETS[2], "取消成对后 low 独立写画布");
    eq(unetOf("video_high"), UNETS[3], "取消成对后 high 不受影响");
    ok(vidG.classList.contains("ccd-vmodel-bad"), "high / low 不是同一套 → 区块给警告底色");
    const vWarn = dig(vidG, (n) => n.classList.contains("ccd-vmodel-warn"));
    ok(!!vWarn && /不是同一套/.test(String(vWarn.textContent)),
      "黄字说明两边的族名对不上：" + (vWarn ? vWarn.textContent : "没有提示元素"));

    // 配回同一套 + 重新勾上成对 → 警告收起
    pairChk.checked = true;
    pairChk.dispatch("change", {});
    hiSel.value = UNETS[1];
    hiSel.dispatch("change", {});
    await tick(20);
    eq(unetOf("video_low"), UNETS[2], "重新成对：low 回到 i2v 那套");
    eq(vWarn.classList.contains("ccd-hide"), true, "配回同一套后提示收起");
    eq(vidG.classList.contains("ccd-vmodel-bad"), false, "警告底色也跟着撤掉");
  }

  console.log("\n[23] 视频模型：GGUF 加载器 / 更多配对写法 / 拖窗不还原（v1.5.0）");
  {
    const GGUF_UNETS = [
      "wan22RemixI2VGGUFV20_highQ80.gguf",
      "wan22RemixI2VGGUFV20_lowQ80.gguf",
      "wan22EnhancedNSFWSVICamera_nolightningSVICfQ8H.gguf",
      "wan22EnhancedNSFWSVICamera_nolightningSVICfQ8L.gguf",
      "wan22I2VA14BGGUF_q8A14BHigh.gguf",
    ];
    let seq = 0, lid = 5000;
    const reg = {
      registered_node_types: {
        UNETLoader: {
          nodeData: {
            input: {
              required: {
                unet_name: [UNETS.slice()],
                weight_dtype: [["default", "fp8_e4m3fn"]],
              },
            },
          },
        },
        UnetLoaderGGUF: {
          nodeData: { input: { required: { unet_name: [GGUF_UNETS.slice()] } } },
        },
      },
      createNode(type) {
        const def = this.registered_node_types[type];
        if (!def) return null;
        const n = mkNode("sw" + (++seq), type, {
          widgets: type === "UNETLoader"
            ? [widget("unet_name", "", { options: { values: UNETS.slice() } }),
              widget("weight_dtype", "default")]
            : [widget("unet_name", "", { options: { values: GGUF_UNETS.slice() } })],
        });
        n.comfyClass = type;
        n.outputs = [{ name: "MODEL", links: [] }];
        n.connect = function (oslot, target, tslot) {
          const id = ++lid;
          target.inputs[tslot].link = id;
          this.outputs[oslot].links = this.outputs[oslot].links || [];
          this.outputs[oslot].links.push(id);
          app.graph.links.push([id, this.id, oslot, target.id, tslot, "MODEL"]);
          return id;
        };
        return n;
      },
    };
    globalThis.LiteGraph = reg;
    mainWin.LiteGraph = reg;

    const unetNode = (k) => app.graph.nodes.find((x) => x.properties
      && x.properties.cc_dock_role === "unet_slot"
      && x.properties.cc_dock_key === k);
    const unetType = (k) => { const n = unetNode(k); return n ? n.type : null; };
    const unetVal = (k) => { const n = unetNode(k); return n ? n.widgets[0].value : null; };
    const downLink = (k) => {
      const n = unetNode(k);
      const src = n && n.outputs && n.outputs[0];
      const id = src && src.links && src.links[0];
      return id ? app.graph.links.find((x) => x[0] === id) : null;
    };
    const groupOf = (labelText) => {
      let hit = null;
      walk(root(), (n) => {
        if (hit || !n.classList.contains("ccd-group")) return;
        // v1.9.0 起模型那一格是「模型行 + 外挂资源行」，label 在里面一层
        walk(n, (c) => {
          if (!hit && c.tagName === "LABEL" && c.textContent === labelText) hit = n;
        });
      });
      return hit;
    };
    const vidG = groupOf("视频模型");
    // 模型行（外挂资源行是同一个分组框里的第二条）
    const vidRow = (vidG.children || []).find(
      (c) => c.classList.contains("ccd-row")) || vidG;
    const vSels = [];
    walk(vidRow, (n) => { if (n.tagName === "SELECT") vSels.push(n); });
    const hiSel = vSels[0], loSel = vSels[1];
    const vWarn = (() => {
      let hit = null;
      walk(vidG, (n) => { if (!hit && n.classList.contains("ccd-vmodel-warn")) hit = n; });
      return hit;
    })();
    const pairChk = (() => {
      let hit = null;
      walk(vidRow, (n) => { if (!hit && n.tagName === "INPUT") hit = n; });
      return hit;
    })();

    pipeBtn("图生视频").dispatch("click");
    await tick(20);
    eq(hiSel.children.length, UNETS.length + GGUF_UNETS.length,
      "下拉把 safetensors 和 GGUF 合在一张清单里");
    const ggufOpt = hiSel.children.find((o) => o.attrs.value === GGUF_UNETS[0]);
    ok(!!ggufOpt && /GGUF/.test(ggufOpt.textContent), "GGUF 那几行标了（GGUF）");
    pairChk.checked = true;
    pairChk.dispatch("change", {});

    // 选 GGUF：406 换成 UnetLoaderGGUF，下游线还在，low 自动配成 lowQ80
    hiSel.value = GGUF_UNETS[0];
    hiSel.dispatch("change", {});
    await tick(20);
    eq(unetType("video_high"), "UnetLoaderGGUF", "选 .gguf 把 406 换成 GGUF 加载器");
    eq(unetVal("video_high"), GGUF_UNETS[0], "GGUF 文件名写进画布");
    eq(unetType("video_low"), "UnetLoaderGGUF", "成对联动：407 也跟着换成 GGUF 加载器");
    eq(unetVal("video_low"), GGUF_UNETS[1], "成对联动认出 highQ80 ↔ lowQ80");
    const dl = downLink("video_high");
    ok(!!dl && dl[1] === unetNode("video_high").id,
      "换加载器后 MODEL 那条线接回原来的下游：" + JSON.stringify(dl));

    // 拖动面板（旧 bug：松手时 sync(true) 把下拉重置回第一项）
    const bar = root().children[0];
    bar.dispatch("pointerdown", { button: 0, clientX: 300, clientY: 30 });
    mainWin.dispatch("pointermove", { clientX: 360, clientY: 90 });
    await tick(20);
    mainWin.dispatch("pointerup", {});
    await tick(30);
    eq(hiSel.value, GGUF_UNETS[0], "拖窗之后 high 下拉还是你选的那个（不再自己还原）");
    eq(loSel.value, GGUF_UNETS[1], "拖窗之后 low 下拉也保持");
    eq(unetVal("video_high"), GGUF_UNETS[0], "拖窗之后画布 406 没被改回去");

    // 选回 safetensors：加载器换回 UNETLoader，weight_dtype 那格回来
    hiSel.value = UNETS[3];
    hiSel.dispatch("change", {});
    await tick(20);
    eq(unetType("video_high"), "UNETLoader", "选回 safetensors 换回核心 UNETLoader");
    eq(unetNode("video_high").widgets.length, 2, "换回后 weight_dtype 那格还在");
    eq(unetVal("video_low"), UNETS[4], "safetensors 那套也照旧成对（t2v high ↔ low）");

    // Q8H / Q8L 也认
    hiSel.value = GGUF_UNETS[2];
    hiSel.dispatch("change", {});
    await tick(20);
    eq(unetVal("video_low"), GGUF_UNETS[3], "认得出 Q8H ↔ Q8L 这种写法");
    eq(vWarn.classList.contains("ccd-hide"), true, "配成一套时不提示");

    // 只有 High 的半套不硬凑
    hiSel.value = GGUF_UNETS[4];
    hiSel.dispatch("change", {});
    await tick(20);
    eq(unetVal("video_low"), GGUF_UNETS[3], "找不到另一半就不动 low（半套不硬凑）");
    ok(/不是同一套/.test(String(vWarn.textContent)),
      "半套 / 不配套时给黄字：" + vWarn.textContent);

    // 旧蓝图（画布上没有视频模型槽）：下拉禁掉 + 提示，别假装改成功
    app.graph.remove(unetNode("video_high"));
    app.graph.remove(unetNode("video_low"));
    await sleep(1400);                     // 等面板轮询里的一次 sync
    eq(hiSel.disabled, true, "画布上没有视频模型槽 → high 下拉禁掉");
    eq(loSel.disabled, true, "low 下拉也禁掉");
    ok(/载入最新蓝图/.test(String(vWarn.textContent)),
      "黄字告诉你去载入最新蓝图：" + vWarn.textContent);
    delete globalThis.LiteGraph;
    delete mainWin.LiteGraph;
  }

  console.log("\n[24] 外挂资源：文本编码器 / VAE（v1.9.0）");
  {
    const groupOf = (labelText) => {
      let hit = null;
      walk(root(), (n) => {
        if (hit || !n.classList.contains("ccd-group")) return;
        walk(n, (c) => {
          if (!hit && c.tagName === "LABEL" && c.textContent === labelText) hit = n;
        });
      });
      return hit;
    };
    const dig = (box, pred) => {
      let hit = null;
      walk(box, (n) => { if (!hit && pred(n)) hit = n; });
      return hit;
    };
    const selectsIn = (box) => {
      const out = [];
      walk(box, (n) => { if (n.tagName === "SELECT") out.push(n); });
      return out;
    };
    const imgG = groupOf("图像模型");
    const vidG = groupOf("视频模型");
    const imgRes = dig(imgG, (n) => n.classList.contains("ccd-res"));
    const vidRes = dig(vidG, (n) => n.classList.contains("ccd-res"));
    ok(!!imgRes && !!vidRes, "图像 / 视频模型下面各有一行「外挂资源」");

    const imgResSels = selectsIn(imgRes);
    const vidResSels = selectsIn(vidRes);
    eq(imgResSels.length, 2, "图像侧两个下拉：文本编码器 + VAE");
    eq(vidResSels.length, 2, "视频侧两个下拉：文本编码器 + VAE");
    const [teSel, vaeSel] = imgResSels;
    const optsOf = (sel) => sel.children.map((o) => o.attrs.value);
    eq(optsOf(teSel).length, TE_FILES.length + 1, "图像文本编码器清单 = 画布节点的清单 + 「用模型自带」");
    ok(TE_FILES.every((f) => optsOf(teSel).indexOf(f) >= 0), "清单里就是 models\\text_encoders 那些文件");
    eq(optsOf(vaeSel).length, VAE_FILES.length + 1, "图像 VAE 清单 = 画布节点的清单 + 「用模型自带」");
    eq(optsOf(vidResSels[0]).length, TE_FILES.length, "视频侧没有「用模型自带」（分离式模型必须外挂）");

    // 选文件 → 写节点 + 把来源开关（112 / 113）切到外挂
    teSel.value = TE_FILES[0];
    teSel.dispatch("change", {});
    await tick(20);
    eq(app.graph.getNodeById("te_img").widgets[0].value, TE_FILES[0], "选文本编码器写进画布 110");
    eq(app.graph.getNodeById("f_clip").widgets[0].value, 2, "来源开关 112 切到外挂");
    vaeSel.value = VAE_FILES[1];
    vaeSel.dispatch("change", {});
    await tick(20);
    eq(app.graph.getNodeById("vae_img").widgets[0].value, VAE_FILES[1], "选 VAE 写进画布 111");
    eq(app.graph.getNodeById("f_vae").widgets[0].value, 2, "来源开关 113 切到外挂");

    // 选回「用模型自带」→ 开关回 1
    teSel.value = "__builtin";
    teSel.dispatch("change", {});
    await tick(20);
    eq(app.graph.getNodeById("f_clip").widgets[0].value, 1, "选「用模型自带」把 112 切回 1");
    vaeSel.value = "__builtin";
    vaeSel.dispatch("change", {});
    await tick(20);
    eq(app.graph.getNodeById("f_vae").widgets[0].value, 1, "选「用模型自带」把 113 切回 1");

    // 后端探测：ANIMA 那种裸 DiT（缺 TE + VAE）→ 这一行出现并自动预填
    const keepFetchRes = globalThis.fetch;
    const PROBE = {
      [MODELS[0]]: { known: true, has_te: true, has_vae: true, is_anima: false },
      [MODELS[1]]: { known: true, has_te: false, has_vae: false, is_anima: true },
    };
    globalThis.fetch = async (url) => {
      const u = String(url || "");
      const m = /\/cc_dashboard\/model_info\?name=([^&]+)/.exec(u);
      if (m) {
        const name = decodeURIComponent(m[1]);
        return { ok: true, status: 200,
          json: async () => (PROBE[name] || { known: false }) };
      }
      return { ok: true, status: 200,
        json: async () => ({ queue_running: [], queue_pending: [] }) };
    };
    // 前面场景用默认桩探测过（返回 {} → 失败缓存 60s），清掉再测，免得桩不生效
    globalThis.__ccDock.resetProbes();

    modelSel.value = MODELS[1];
    modelSel.dispatch("change", {});
    await tick(30);
    eq(imgRes.classList.contains("ccd-hide"), false, "裸模型（缺 TE / VAE）→ 图像侧资源行显示出来");
    eq(teSel.value, "qwen_3_06b_base.safetensors", "自动预填 ANIMA 的文本编码器");
    eq(vaeSel.value, "qwen_image_vae.safetensors", "自动预填 ANIMA 的 VAE");
    eq(app.graph.getNodeById("f_clip").widgets[0].value, 2, "预填后 112 自动切到外挂");
    eq(app.graph.getNodeById("f_vae").widgets[0].value, 2, "预填后 113 自动切到外挂");
    ok(/不自带/.test(String(imgRes.children[imgRes.children.length - 1].textContent)),
      "给一行提示说明模型不自带：" + imgRes.children[imgRes.children.length - 1].textContent);

    // 自带 TE / VAE 的模型（Illustrious）→ 整行收起，只剩「🛠 外挂」按钮
    modelSel.value = MODELS[0];
    modelSel.dispatch("change", {});
    await tick(30);
    eq(imgRes.classList.contains("ccd-hide"), true, "自带 TE / VAE → 图像侧资源行收起");
    eq(app.graph.getNodeById("f_clip").widgets[0].value, 1, "收起时 112 也用模型自带");
    eq(vidRes.classList.contains("ccd-hide"), false, "视频侧那一行不受图像模型影响，恒显示");
    eq(vidResSels[0].disabled, false, "视频侧文本编码器下拉可用");

    // 🛠 强制展开 + 每模型记住选过的那份
    const resOpen = dig(imgG, (n) => n.classList.contains("ccd-res-open"));
    ok(!!resOpen, "「🛠 外挂」按钮在模型那一行");
    resOpen.dispatch("click");
    await tick(20);
    eq(imgRes.classList.contains("ccd-hide"), false, "点 🛠 能把收起的资源行强制展开");
    vaeSel.value = "sdxlVAE_sdxlVAE.safetensors";
    vaeSel.dispatch("change", {});
    await tick(20);
    eq(app.graph.getNodeById("vae_img").widgets[0].value, "sdxlVAE_sdxlVAE.safetensors",
      "给自带 VAE 的模型强换外挂也写得进画布");
    modelSel.value = MODELS[1];
    modelSel.dispatch("change", {});
    await tick(30);
    modelSel.value = MODELS[0];
    modelSel.dispatch("change", {});
    await tick(30);
    eq(app.graph.getNodeById("vae_img").widgets[0].value, "sdxlVAE_sdxlVAE.safetensors",
      "切回这个模型自动还原你给它选过的 VAE");
    eq(app.graph.getNodeById("f_vae").widgets[0].value, 2, "还原的那份也照样切外挂");

    // 管线过滤：视频只看视频资源行，图像只看图像资源行（整格隐藏）
    pipeBtn("图生视频").dispatch("click");
    await tick(20);
    eq(imgG.classList.contains("ccd-hide"), true, "视频管线：图像模型那格（含资源行）收起");
    eq(vidG.classList.contains("ccd-hide"), false, "视频管线：视频资源行显示");
    pipeBtn("文生图").dispatch("click");
    await tick(20);
    eq(vidG.classList.contains("ccd-hide"), true, "图像管线：视频资源行收起");
    eq(imgG.classList.contains("ccd-hide"), false, "图像管线：图像资源行显示");

    // 回归：选完 VAE 之后清单刷新会把下拉视觉上冲回「用模型自带」（画布值其实没被改）——
    // 用户看到的就是「我选 VAE，它自己又切回自带」。重建选项后必须保住选中项。
    vaeSel.value = VAE_FILES[0];
    vaeSel.dispatch("change", {});
    await tick(20);
    eq(app.graph.getNodeById("vae_img").widgets[0].value, VAE_FILES[0], "先选一份 VAE");
    ok(/已写进画布 111/.test(String(imgRes.children[imgRes.children.length - 1].textContent)),
      "选完给一句「写进画布 111」的反馈："
      + imgRes.children[imgRes.children.length - 1].textContent);
    // 模拟 models\vae 里新丢进一个文件 → 清单签名变了 → 下拉重建
    app.graph.getNodeById("vae_img").widgets[0].options =
      { values: VAE_FILES.concat(["brand_new_vae.safetensors"]).slice() };
    const resReload = dig(imgRes, (n) => n.classList.contains("ccd-res-reload"));
    resReload.dispatch("click");
    await tick(30);
    ok(optsOf(vaeSel).indexOf("brand_new_vae.safetensors") >= 0,
      "⟳ 重拉清单：新文件出现在下拉里");
    eq(vaeSel.value, VAE_FILES[0], "清单重建后选中项没被冲回「用模型自带」");
    eq(app.graph.getNodeById("f_vae").widgets[0].value, 2, "来源开关还停在外挂");
    globalThis.fetch = keepFetchRes;
  }

  console.log("\n[25] 流匹配模型（ANIMA）：karras 调度器会把图洗白（自动纠正 + 黄字）");
  {
    const schSel2 = selOf(genSec, "调度器");
    const smpSel2 = selOf(genSec, "采样器");
    const warnOf = (sel) => {
      const w = sel.parentNode && sel.parentNode.querySelector(".ccd-warn-txt");
      return String((w && w.textContent) || "");
    };
    // 先落在 SDXL 的正常默认上（karras 对扩散模型没问题）
    schSel2.value = "karras";
    schSel2.dispatch("change");
    await tick(20);
    eq(imgW("scheduler"), "karras", "前提：Illustrious + karras（扩散模型的正常配方）");
    eq(warnOf(schSel2), "", "SDXL 上不提示（karras 是它的甜点）");

    // 切到 ANIMA：karras 必须自动换掉
    modelSel.value = MODELS[1];
    modelSel.dispatch("change", {});
    await tick(30);
    eq(imgW("scheduler"), "simple", "切到 ANIMA → 调度器自动从 karras 换成 simple");
    eq(imgW("sampler_name"), "dpmpp_2m", "采样器不动（当前值本身安全）");
    const parStatus2 = root().querySelector(".ccd-par-status");
    ok(/karras/.test(String(parStatus2.textContent)) && /simple/.test(String(parStatus2.textContent)),
      "面板说清改了哪一项：" + parStatus2.textContent);
    eq((JSON.parse(localStorage.getItem(pkey) || "{}")).__scheduler_image, "simple",
      "纠正后的调度器也记进本地记忆");

    // 手动选回 karras：你说了算，值照样写进去，但那一行下面出黄字
    schSel2.value = "karras";
    schSel2.dispatch("change");
    await tick(20);
    eq(imgW("scheduler"), "karras", "手动选 karras 照样写进画布（不偷偷改你的选择）");
    ok(/流匹配/.test(warnOf(schSel2)) && /simple/.test(warnOf(schSel2)),
      "调度器那一行下面出现黄字：" + warnOf(schSel2));
    schSel2.value = "simple";
    schSel2.dispatch("change");
    await tick(20);
    eq(warnOf(schSel2), "", "换回 simple → 黄字消失");

    // 重置默认值：按当前模型族取，ANIMA 给 er_sde + simple（不会重置回 karras）
    const resetBtn2 = [...root().querySelectorAll("BUTTON")].find(
      (b) => b.textContent.indexOf("重置默认值") >= 0);
    ok(!!resetBtn2, "参数页的重置按钮还在");
    resetBtn2.dispatch("click");
    await tick(30);
    eq(imgW("sampler_name"), "er_sde", "重置 → ANIMA 的采样器回到 er_sde（官方推荐）");
    eq(imgW("scheduler"), "simple", "重置 → 调度器回到 simple，不会又踩 karras");

    // 老会话在 localStorage 里留着 karras：重开工作流写回记忆时也要纠掉
    const st2 = JSON.parse(localStorage.getItem(pkey) || "{}");
    st2.__scheduler_image = "karras";
    st2.__sampler_image = "dpmpp_2m";
    localStorage.setItem(pkey, JSON.stringify(st2));
    imgKs().widgets.find((w) => w.name === "scheduler").value = "karras";
    globalThis.__ccApi.emit("graphConfigured");
    await tick(60);
    eq(imgW("scheduler"), "simple", "重开工作流：记忆里的 karras 也被纠成 simple");
    eq(imgW("sampler_name"), "dpmpp_2m", "采样器按记忆写回（这个值本身没问题）");

    // 本地记忆里没有调度器那一项（老会话 / 换电脑）：画布上留着的 karras 也要在打开工作流时纠掉
    const st3 = JSON.parse(localStorage.getItem(pkey) || "{}");
    delete st3.__scheduler_image;
    localStorage.setItem(pkey, JSON.stringify(st3));
    imgKs().widgets.find((w) => w.name === "scheduler").value = "karras";
    globalThis.__ccApi.emit("graphConfigured");
    await tick(60);
    eq(imgW("scheduler"), "simple", "打开工作流时也按族纠一遍（不靠本地记忆兜）");

    // 切回 Illustrious：只纠正流匹配族，不会误伤（SDXL 上 karras 合法）
    schSel2.value = "karras";
    schSel2.dispatch("change");
    await tick(20);
    modelSel.value = MODELS[0];
    modelSel.dispatch("change", {});
    await tick(30);
    eq(imgW("scheduler"), "karras", "切回 Illustrious 时不动调度器（仍是你要的 karras）");
    eq(warnOf(schSel2), "", "切回 SDXL 后黄字也消失");
    smpSel2.value = "dpmpp_2m";
    smpSel2.dispatch("change");
    await tick(20);
    eq(imgW("sampler_name"), "dpmpp_2m", "收尾：采样器回到 dpmpp_2m");
  }

  console.log("\n[26] 推荐分辨率真的读模型头部（v1.9.2）");
  {
    const keepFetch3 = globalThis.fetch;
    const EXTRA = "krea2Style_test.safetensors";        // 名字里什么族都认不出 → 只能靠头部
    const EXTRA_UNET = "wan2.2_testX_high_noise.safetensors";
    const PROBE3 = {
      [EXTRA]: {
        known: true, has_te: true, has_vae: true, is_anima: false, arch: "sdxl",
        res: [1216, 832], res_src: "file",
        res_why: "模型文件里写了训练分辨率（合成：ss_bucket_info）",
        buckets: [[1024, 1536, 55]],
      },
      [EXTRA_UNET]: {
        known: true, has_te: false, has_vae: false, is_anima: false, arch: "wan",
        res: [832, 480], res_src: "family",
        res_why: "Wan 2.2 官方 480P 档 832×480（合成）", buckets: [],
      },
    };
    const asked = [];
    globalThis.fetch = async (url) => {
      const u = String(url || "");
      const m = /\/cc_dashboard\/model_info\?name=([^&]+)/.exec(u);
      if (m) {
        const name = decodeURIComponent(m[1]);
        asked.push(name);
        return { ok: true, status: 200,
          json: async () => (PROBE3[name] || { known: false }) };
      }
      return { ok: true, status: 200,
        json: async () => ({ queue_running: [], queue_pending: [] }) };
    };

    // 新模型塞进画布清单：名字里没有 anima / illustrious 线索
    const slot = app.graph.nodes.find((n) => n.properties
      && n.properties.cc_dock_role === "model_slot");
    slot.widgets[0].options.values.push(EXTRA);
    // 先把宽高压成「按名字猜出来的推荐值」1024×1024（这时面板只会给 1024）
    const wInp = fieldOf(genSec, "宽").querySelector("input");
    const hInp = fieldOf(genSec, "高").querySelector("input");
    wInp.value = "1024"; wInp.dispatch("change", {});
    hInp.value = "1024"; hInp.dispatch("change", {});
    globalThis.__ccApi.emit("graphConfigured");
    await tick(60);
    const slotSel = root().querySelector("select");
    eq(slotSel, modelSel, "顶上第一个下拉就是图像模型下拉");
    // 桩里 option 的 value 只在 el() 里设属性，这里按文本判断
    ok(slotSel.children.map((o) => String(o.textContent)).indexOf(EXTRA) >= 0,
      "新模型出现在下拉里：" + EXTRA);

    slotSel.value = EXTRA;
    slotSel.dispatch("change", {});
    await tick(60);
    ok(asked.indexOf(EXTRA) >= 0, "换模型时向后端问了头部（model_info）：" + EXTRA);
    const resSel3 = selOf(genSec, "分辨率");
    const recTxt3 = String(resSel3.children[0].textContent);
    ok(/1216/.test(recTxt3) && /832/.test(recTxt3),
      "推荐项按头部给的真值（1216×832），不再拿 1024×1024 糊弄：" + recTxt3);
    ok(/文件里写了训练分辨率/.test(recTxt3),
      "文件里写了训练分辨率 → 文案说清来源：" + recTxt3);
    ok(/读自模型文件/.test(String(resSel3.title || "")),
      "推荐项悬停说明写清来源：" + String(resSel3.title || "").slice(0, 24) + "…");
    eq(pnum("p_width"), 1216, "宽高还停在猜测值时自动跟随头部：宽 = 1216");
    eq(pnum("p_height"), 832, "宽高还停在猜测值时自动跟随头部：高 = 832");
    const bucketOpt = (resSel3.children || []).find(
      (o) => String(o.attrs.value) === "1024x1536");
    ok(!!bucketOpt && /训练桶|55/.test(String(bucketOpt.textContent)),
      "kohya 训练桶也列成选项：" + (bucketOpt ? bucketOpt.textContent : "没有这一项"));

    // 视频侧：场景 [22] 把两个视频模型槽都删了（验证「没有槽就禁用下拉」），
    // 这里重新挂一对回来，换一个没探过的 unet → 推荐跟着它自己的头部走
    const mkUnet = (key, cur) => {
      const n = mkNode("u_" + key + "_back", "UNETLoader", {
        widgets: [
          widget("unet_name", cur, { options: { values: UNETS.concat([EXTRA_UNET]) } }),
          widget("weight_dtype", "default"),
        ],
      });
      n.properties = { cc_dock_role: "unet_slot", cc_dock_key: key };
      app.graph.add(n);
      return n;
    };
    mkUnet("video_high", UNETS[1]);
    mkUnet("video_low", UNETS[2]);
    globalThis.__ccApi.emit("graphConfigured");
    await tick(60);
    pipeBtn("图生视频").dispatch("click");
    await tick(30);
    const vidModelGroup = (() => {
      let hit = null;
      walk(root(), (n) => {
        if (hit || !n.classList.contains("ccd-group")) return;
        walk(n, (c) => { if (!hit && c.tagName === "LABEL" && c.textContent === "视频模型") hit = n; });
      });
      return hit;
    })();
    const hiSel3 = (() => {
      let hit = null;
      walk(vidModelGroup, (n) => { if (!hit && n.tagName === "SELECT") hit = n; });
      return hit;
    })();
    ok(!!hiSel3, "视频模型 high 下拉在");
    hiSel3.value = EXTRA_UNET;
    hiSel3.dispatch("change", {});
    await tick(60);
    ok(asked.indexOf(EXTRA_UNET) >= 0, "换视频模型也会问头部：" + EXTRA_UNET);
    const vSec3 = secOf(paramTab.children[1], "视频生成参数");
    const vResSel3 = selOf(vSec3, "分辨率");
    ok(!!vResSel3, "视频参数里有分辨率下拉");
    const vRecTxt = String(vResSel3.children[0].textContent);
    ok(/832/.test(vRecTxt) && /480/.test(vRecTxt) && /合成/.test(vRecTxt),
      "视频推荐项按 unet 头部给（832×480）：" + vRecTxt);

    pipeBtn("文生图").dispatch("click");
    await tick(20);
    globalThis.fetch = keepFetch3;
  }

  console.log("\n[27] LoRA 下拉：排序 + ⟳ 刷新（v1.9.3）");
  {
    const keepFetch4 = globalThis.fetch;
    const NOW = Date.now() / 1000;
    // 名字顺序和时间顺序故意不一致，才能看出排的是哪个
    const FILES = [
      { name: "a_newest.safetensors", mtime: NOW - 60, size: 11 },
      { name: "b_oldest.safetensors", mtime: NOW - 900000, size: 22 },
      { name: "c_middle.safetensors", mtime: NOW - 90000, size: 33 },
    ];
    let asks = 0, extra = false;
    globalThis.fetch = async (url) => {
      const u = String(url || "");
      if (u.indexOf("/cc_dashboard/loras") >= 0) {
        asks++;
        const items = FILES.concat(extra
          ? [{ name: "z_fresh_download.safetensors", mtime: NOW + 5, size: 44 }] : []);
        return { ok: true, status: 200,
          json: async () => ({ ok: true, count: items.length, items: items.slice(),
            dirs: ["D:/models/loras"] }) };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    };

    const cols = root().querySelectorAll(".ccd-lora-col");
    eq(cols.length, 3, "LoRA 页还是三个分组（图像 / high / low）");
    const sorts = root().querySelectorAll(".ccd-lora-sort");
    eq(sorts.length, 3, "三个分组各有一个排序下拉");
    eq((sorts[0].children || []).length, 4, "排序下拉有四项（名称 ↑↓ / 时间 新→旧、旧→新）");
    eq(sorts[0].value, "name", "默认按名称 A→Z");
    const refBtn = root().querySelectorAll(".ccd-lora-refresh")[0];
    ok(!!refBtn, "每个分组有一个 ⟳ 刷新按钮");

    // ⟳：问后端要清单（新下的文件也在这份里）
    refBtn.dispatch("click", {});
    await tick(40);
    ok(asks > 0, "⟳ 会去问 /cc_dashboard/loras（问了 " + asks + " 次）");
    const pickOf = (colIdx, rowIdx) => cols[colIdx].children[1].children[rowIdx].children[1];
    const optsOf = (s) => (s.children || []).map((o) => String(o.attrs.value));
    eq(optsOf(pickOf(0, 0)).slice(1, 4).join("|"),
      "a_newest.safetensors|b_oldest.safetensors|c_middle.safetensors",
      "默认名称排序：a → b → c");
    ok(optsOf(pickOf(0, 0)).indexOf("hiyuki02.safetensors") >= 0,
      "面板里正在用的那个（清单里没有的）也留着，不会被刷新冲掉");
    eq(String(pickOf(0, 0).children[0].textContent), "— 无 —", "第一个选项还是「— 无 —」");

    // 选中一个，再换排序：选中项必须保住
    pickOf(0, 0).value = "c_middle.safetensors";
    pickOf(0, 0).dispatch("change", {});
    await tick(20);
    sorts[0].value = "time_desc";
    sorts[0].dispatch("change", {});
    await tick(40);
    eq(optsOf(pickOf(0, 0)).slice(1).join("|"),
      "a_newest.safetensors|c_middle.safetensors|b_oldest.safetensors",
      "时间 新→旧：a（最新）→ c → b");
    eq(pickOf(0, 0).value, "c_middle.safetensors", "换成时间排序后，选中的那个没被冲掉");
    eq(sorts[1].value, "time_desc", "三个分组的排序是同一份设置（high 跟着变）");
    eq(sorts[2].value, "time_desc", "low 也跟着变");
    eq(JSON.parse(localStorage.getItem("cc_dock_ui_v1")).loraSort, "time_desc",
      "排序方式记进本地记忆（换页面还在）");
    const loraNode = app.graph.nodes.find((n) => n.properties
      && n.properties.cc_dock_role === "lora_group" && n.properties.cc_dock_key === "image");
    eq(loraNode.widgets[0].value.lora, "c_middle.safetensors", "排序只动面板下拉，画布那行没被改");

    sorts[0].value = "time";
    sorts[0].dispatch("change", {});
    await tick(40);
    eq(optsOf(pickOf(0, 0)).slice(1).join("|"),
      "b_oldest.safetensors|c_middle.safetensors|a_newest.safetensors",
      "时间 旧→新：b（最旧）→ c → a");

    sorts[0].value = "name_desc";
    sorts[0].dispatch("change", {});
    await tick(40);
    eq(optsOf(pickOf(0, 0)).slice(1).join("|"),
      "c_middle.safetensors|b_oldest.safetensors|a_newest.safetensors",
      "名称 Z→A：c → b → a");

    // 刚下完一个新 LoRA：点 ⟳ 就能选到，还能看出「新增 1 个」
    extra = true;
    refBtn.dispatch("click", {});
    await tick(60);
    ok(optsOf(pickOf(0, 0)).indexOf("z_fresh_download.safetensors") >= 0,
      "刷新后新下载的 LoRA 出现在下拉里（不用重启）");
    const note = cols[0].children[2];
    ok(/新增 1 个/.test(String(note.textContent)),
      "刷新后给一句「新增了几个」：" + note.textContent);
    ok(/新增 1 个/.test(String(cols[1].children[2].textContent)),
      "提示三个分组一起显示（不用切过去看）");
    eq(pickOf(0, 0).value, "c_middle.safetensors", "刷新也不会把你正选着的那个冲掉");

    // 回到名称排序收尾，别把状态留给后面的预览
    sorts[0].value = "name";
    sorts[0].dispatch("change", {});
    await tick(20);
    globalThis.fetch = keepFetch4;
  }

} catch (e) {
  results.fail++;
  console.log("\n运行期异常：" + (e && e.stack ? e.stack : e));
} finally {
  try { fs.unlinkSync(UNDER_TEST); } catch (e) { /* 保留也没关系 */ }
}

console.log("\n" + "=".repeat(60));
console.log("结果：" + results.pass + " 通过，" + results.fail + " 失败");
console.log("=".repeat(60));
process.exit(results.fail ? 1 : 0);

// ------------------------------------------------- 真实 DOM 快照 → HTML
function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function serialize(el) {
  const tag = el.tagName.toLowerCase();
  const attrs = [];
  if (el.attrs.id) attrs.push(`id="${esc(el.attrs.id)}"`);
  if (el.className) attrs.push(`class="${esc(el.className)}"`);
  const style = Object.entries(el.style)
    .filter(([, v]) => v !== "" && v !== null && v !== undefined)
    .map(([k, v]) => `${k}:${v}`).join(";");
  if (style) attrs.push(`style="${esc(style)}"`);
  for (const [k, v] of Object.entries(el.attrs)) {
    if (k === "id" || k === "class" || k === "style") continue;
    if (tag === "input" && (k === "value" || k === "checked")) continue;   // 重复属性会让浏览器取第一个
    attrs.push(`${k}="${esc(v)}"`);
  }
  const a = attrs.join(" ");
  if (tag === "textarea") return `<textarea ${a}>${esc(el.value || "")}</textarea>`;
  if (tag === "input") {
    return `<input ${a} value="${esc(el.value)}"${el.checked ? " checked" : ""}>`;
  }
  if (tag === "option") {
    return `<option ${a}${el.attrs.value === el.value ? " selected" : ""}>${esc(el.textContent)}</option>`;
  }
  if (tag === "select") {
    const kids = el.children.map(serialize).join("");
    return `<select ${a}>${kids}</select>`;
  }
  const kids = el.children.map(serialize).join("") + esc(el._text || "");
  return `<${tag} ${a}>${kids}</${tag}>`;
}

function writePreview(source, rootEl, name) {
  const m = /const CSS = `([\s\S]*?)`;/.exec(source);
  const css = (m ? m[1] : "")
    .replace(/\$\{ROOT_ID\}/g, "cc-dock-root")
    .replace(/\$\{GEOM_MIN_W\}/g, "420")
    .replace(/\$\{GEOM_MIN_H\}/g, "200");
  const grid = "background-color:#1f2027;background-image:" +
    "linear-gradient(#2a2b33 1px,transparent 1px)," +
    "linear-gradient(90deg,#2a2b33 1px,transparent 1px);background-size:24px 24px";
  const html = `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>cc_dashboard 预览</title>
<style>
html,body{margin:0;height:100%;background:#1f2027;font:12px/1.45 "Segoe UI","Microsoft YaHei",sans-serif}
#fake-menu{position:fixed;left:0;right:0;top:0;height:40px;background:#20212a;
 border-bottom:1px solid #3b3f4a;color:#9aa0ad;display:flex;align-items:center;padding-left:12px}
#fake-canvas{position:absolute;inset:40px 0 0 0;${grid}}
</style>
<style data-cc-dock="1">${css}</style>
</head><body>
<div id="fake-menu">ComfyUI 菜单栏（示意）</div>
<div id="fake-canvas"></div>
<style>/* 截图用固定位置，避免跟着测试里的拖动跑 */
#cc-dock-root{left:20px!important;top:56px!important}</style>
${serialize(rootEl)}
</body></html>`;
  fs.writeFileSync(path.join(TMP_DIR, name || "preview.html"), html, "utf8");
}
