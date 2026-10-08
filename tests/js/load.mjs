// Loads a browser IIFE from static/js into a fake `window` and returns it.
// Only for pure helpers: scripts that touch `document` need a real browser.
import fs from "node:fs";
import vm from "node:vm";

const STATIC_JS = new URL("../../src/sbobina/web/static/js/", import.meta.url);

export function loadBrowserScript(name, globals = {}) {
  const window = { ...globals };
  const source = fs.readFileSync(new URL(name, STATIC_JS), "utf8");
  vm.runInNewContext(source, { window, ...globals });
  return window;
}
