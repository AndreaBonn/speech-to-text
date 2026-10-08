import assert from "node:assert/strict";
import { test } from "node:test";

import { loadBrowserScript } from "./load.mjs";

const Coverage = loadBrowserScript("settings-semantic-coverage.js").SbobinaSettingsSemanticCoverage;

function course(embedded, total, missing, truncated = 0) {
  return { coverage: { embedded: embedded, total: total, truncated: truncated }, missing_units: missing };
}

test("a fully indexed course reads as ready, without internal units", () => {
  const text = Coverage.coverageText(course(97, 97, 0));
  assert.equal(text, "pronta su tutte le lezioni e i materiali");
  assert.ok(!text.includes("unità"));
});

test("a partly indexed course reads as a percentage", () => {
  assert.equal(Coverage.coverageText(course(50, 200, 150)), "pronta al 25%, il resto è da indicizzare");
});

test("new text after a full index says so", () => {
  assert.equal(
    Coverage.coverageText(course(97, 97, 4)),
    "pronta sul testo già indicizzato, ci sono parti nuove da indicizzare"
  );
});

test("truncated passages are mentioned in words", () => {
  assert.equal(
    Coverage.coverageText(course(10, 10, 0, 2)),
    "pronta su tutte le lezioni e i materiali (alcuni passaggi molto lunghi sono stati accorciati)"
  );
});

test("a course with nothing to index says so", () => {
  assert.equal(Coverage.coverageText({ coverage: null, missing_units: null }), "nessun contenuto da indicizzare");
  assert.equal(Coverage.coverageText(course(0, 0, 0)), "nessun contenuto da indicizzare");
});

test("the exact count stays available for the tooltip", () => {
  assert.equal(Coverage.coverageDetail(course(97, 97, 0)), "97 passaggi indicizzati su 97");
});
