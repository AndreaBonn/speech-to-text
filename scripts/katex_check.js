// Reads a JSON array of LaTeX strings on stdin and prints, for each one,
// whether the vendored KaTeX parses it and its MathML (for equality checks
// that ignore spacing and redundant braces). Used by eval_math.py (T060).
"use strict";

const path = require("path");
const katex = require(
  path.join(__dirname, "..", "src", "sbobina", "web", "static", "vendor", "katex-0.19.0", "katex.min.js")
);

const OPTIONS = { output: "mathml", throwOnError: true, strict: "ignore", trust: false };

let input = "";
process.stdin.on("data", (chunk) => {
  input += chunk;
});
process.stdin.on("end", () => {
  const results = JSON.parse(input).map((expression) => {
    try {
      const mathml = katex.renderToString(expression, OPTIONS);
      // The annotation repeats the source LaTeX: drop it so only structure counts.
      return { ok: true, mathml: mathml.replace(/<annotation[\s\S]*?<\/annotation>/, "") };
    } catch (error) {
      return { ok: false, mathml: "" };
    }
  });
  process.stdout.write(JSON.stringify(results));
});
