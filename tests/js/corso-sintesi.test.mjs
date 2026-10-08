import assert from "node:assert/strict";
import { test } from "node:test";

import { loadBrowserScript } from "./load.mjs";

const Summary = loadBrowserScript("corso-sintesi.js").SbobinaCourseSummary;

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

test("each known count becomes a link to its section", () => {
  const items = plain(Summary.items({ lessons: 2, materials: 1, exercises: 1, cards: 0 }));
  assert.deepEqual(items, [
    { text: "2 lezioni", href: "#corsi-lessons" },
    { text: "1 materiale", href: "#corsi-materials" },
    { text: "1 esercitazione", href: "#corsi-generations" },
    { text: "0 carte da ripassare oggi", href: "/ripasso" },
  ]);
});

test("singular and plural follow the count", () => {
  const items = plain(Summary.items({ lessons: 1, materials: 3, exercises: 2, cards: 1 }));
  assert.deepEqual(
    items.map((item) => item.text),
    ["1 lezione", "3 materiali", "2 esercitazioni", "1 carta da ripassare oggi"]
  );
});

test("a count that failed to load is left out, never shown as zero", () => {
  const items = plain(Summary.items({ lessons: 2, materials: null, exercises: undefined, cards: 4 }));
  assert.deepEqual(
    items.map((item) => item.text),
    ["2 lezioni", "4 carte da ripassare oggi"]
  );
});

test("unfinished jobs are attempts, queued and running are not", () => {
  assert.equal(Summary.isAttempt("cancelled"), true);
  assert.equal(Summary.isAttempt("interrupted"), true);
  assert.equal(Summary.isAttempt("failed"), true);
  assert.equal(Summary.isAttempt("done"), false);
  assert.equal(Summary.isAttempt("running"), false);
  assert.equal(Summary.isAttempt("queued"), false);
});
