// 测试用桩：dock.js 里的 `await import("../../scripts/api.js")`
const api = (globalThis.__ccApi = {
  listeners: {},
  addEventListener(type, fn) {
    (this.listeners[type] = this.listeners[type] || []).push(fn);
  },
  emit(type, detail) {
    for (const fn of (this.listeners[type] || []).slice()) {
      fn({ detail });
    }
  },
});

export { api };
