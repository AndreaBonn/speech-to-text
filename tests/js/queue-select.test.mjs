import assert from "node:assert/strict";
import { test } from "node:test";

import { loadBrowserScript } from "./load.mjs";

const QueueSelect = loadBrowserScript("queue-select.js").SbobinaQueueSelect;

function job(id, status) {
  return { id: id, status: status };
}

// selectVisible runs in the vm sandbox from loadBrowserScript, so the array
// it returns is built with that sandbox's Array constructor. node:assert's
// strict deepEqual treats a cross-realm array as not equal to a same-realm
// one even with identical contents; Array.from re-materializes it here.
function visible(jobs) {
  return Array.from(QueueSelect.selectVisible(jobs));
}

test("active and actionable jobs always show", () => {
  const jobs = [job("a", "queued"), job("b", "running"), job("c", "interrupted"), job("d", "failed")];
  assert.deepEqual(visible(jobs), ["a", "b", "c", "d"]);
});

test("only the first 3 completed jobs show, newest first", () => {
  const jobs = [job("a", "done"), job("b", "done"), job("c", "done"), job("d", "done")];
  assert.deepEqual(visible(jobs), ["a", "b", "c"]);
});

test("cancelled jobs never show", () => {
  const jobs = [job("a", "cancelled"), job("b", "done")];
  assert.deepEqual(visible(jobs), ["b"]);
});

test("active jobs do not count against the completed cap", () => {
  const jobs = [
    job("a", "running"),
    job("b", "done"),
    job("c", "done"),
    job("d", "done"),
    job("e", "done"),
  ];
  assert.deepEqual(visible(jobs), ["a", "b", "c", "d"]);
});

test("empty queue returns no ids", () => {
  assert.deepEqual(visible([]), []);
});
