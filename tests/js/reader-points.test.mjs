import assert from "node:assert/strict";
import { test } from "node:test";

import { loadBrowserScript } from "./load.mjs";

const Points = loadBrowserScript("reader-points.js").SbobinaReaderPoints;

function point(start, text, mostUncertain = false) {
  return { start: start, before: "", text: text, after: "", most_uncertain: mostUncertain };
}

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

test("nearby points merge into one passage with its range and words", () => {
  const groups = plain(
    Points.groupPoints([point(1, "un"), point(3, "punta"), point(4, "possessoria"), point(40, "fame")], "all")
  );
  assert.deepEqual(groups, [
    { start: 1, end: 4, words: 3, texts: ["un", "punta", "possessoria"] },
    { start: 40, end: 40, words: 1, texts: ["fame"] },
  ]);
});

test("a chain of close points stays one passage while it is short", () => {
  const groups = Points.groupPoints([point(0, "a"), point(8, "b"), point(16, "c")], "all");
  assert.equal(groups.length, 1);
  assert.equal(groups[0].end, 16);
});

test("a long chain splits so no passage runs longer than a short listen", () => {
  const chain = [];
  for (let t = 0; t <= 120; t += 5) {
    chain.push(point(t, "w" + t));
  }
  const groups = Array.from(Points.groupPoints(chain, "all"));
  assert.ok(groups.length > 1);
  for (const group of groups) {
    assert.ok(group.end - group.start <= 20, `passage ${group.start}-${group.end}`);
  }
});

test("multi-word points count every word", () => {
  const groups = Points.groupPoints([point(9, "e mio")], "all");
  assert.equal(groups[0].words, 2);
});

test("the most doubtful level keeps only flagged points", () => {
  const groups = plain(Points.groupPoints([point(1, "un"), point(3, "punta", true)], "most"));
  assert.deepEqual(groups, [{ start: 3, end: 3, words: 1, texts: ["punta"] }]);
});

test("the none level shows no passage", () => {
  assert.equal(Points.groupPoints([point(1, "un", true)], "none").length, 0);
});

test("repeated words are listed once", () => {
  const groups = Points.groupPoints([point(1, "punta"), point(2, "punta")], "all");
  assert.deepEqual(Array.from(groups[0].texts), ["punta"]);
});
