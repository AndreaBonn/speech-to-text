import assert from "node:assert/strict";
import { test } from "node:test";

import { loadBrowserScript } from "./load.mjs";

const When = loadBrowserScript("when.js").SbobinaWhen;
const NOW = new Date(2026, 9, 8, 12, 0);

test("same day reads as oggi without seconds", () => {
  assert.equal(When.format(new Date(2026, 9, 8, 1, 11, 48).toISOString(), NOW), "oggi, 01:11");
});

test("previous day reads as ieri", () => {
  assert.equal(When.format(new Date(2026, 9, 7, 9, 5).toISOString(), NOW), "ieri, 09:05");
});

test("same year shows weekday and day/month", () => {
  assert.equal(When.format(new Date(2026, 9, 2, 16, 3, 18).toISOString(), NOW), "ven 02/10, 16:03");
});

test("another year keeps the year", () => {
  assert.equal(When.format(new Date(2025, 11, 31, 23, 59).toISOString(), NOW), "31/12/2025, 23:59");
});

test("formatDay drops the time", () => {
  assert.equal(When.formatDay(new Date(2026, 9, 2, 16, 3).toISOString(), NOW), "ven 02/10");
});
