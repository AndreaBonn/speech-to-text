import assert from "node:assert/strict";
import { test } from "node:test";

import { loadBrowserScript } from "./load.mjs";

const Filters = loadBrowserScript("storico-filtri.js").SbobinaHistoryFilters;

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

test("each filter maps to the status query of the jobs API", () => {
  assert.equal(Filters.statusQuery("all"), "");
  assert.equal(Filters.statusQuery("done"), "&status=done");
  assert.equal(
    Filters.statusQuery("unfinished"),
    "&status=cancelled&status=interrupted&status=failed"
  );
});

test("counts add up per filter from meta.status_counts", () => {
  const counts = plain(
    Filters.counts({ done: 3, interrupted: 1, cancelled: 1, queued: 2 })
  );
  assert.deepEqual(counts, { all: 7, done: 3, unfinished: 2 });
});

test("missing statuses count as zero", () => {
  assert.deepEqual(plain(Filters.counts({})), { all: 0, done: 0, unfinished: 0 });
});

test("an unknown filter falls back to all", () => {
  assert.equal(Filters.statusQuery("bogus"), "");
});
