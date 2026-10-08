import assert from "node:assert/strict";
import { test } from "node:test";

import { loadBrowserScript } from "./load.mjs";

const Choice = loadBrowserScript("modelli-scelta.js").SbobinaModelChoice;

function model(name, extra = {}) {
  return Object.assign(
    { name: name, aliases: [], recommended_gpu: false, recommended_cpu: false },
    extra
  );
}

function names(list) {
  return Array.from(list, (item) => item.name);
}

test("recommended and in-use models stay in view, the rest is folded", () => {
  const split = Choice.split(
    [
      model("tiny"),
      model("large-v3", { aliases: ["large"], recommended_gpu: true }),
      model("small"),
      model("large-v3-turbo", { recommended_cpu: true }),
    ],
    "small"
  );
  assert.deepEqual(names(split.primary), ["large-v3", "small", "large-v3-turbo"]);
  assert.deepEqual(names(split.others), ["tiny"]);
});

test("the in-use model matches through an alias", () => {
  const split = Choice.split([model("large-v3", { aliases: ["large"] }), model("tiny")], "large");
  assert.deepEqual(names(split.primary), ["large-v3"]);
});

test("English-only models go after the multilingual ones", () => {
  const split = Choice.split([model("tiny.en"), model("base"), model("small.en"), model("medium")], null);
  assert.deepEqual(names(split.others), ["base", "medium", "tiny.en", "small.en"]);
  assert.equal(Choice.isEnglishOnly(model("tiny.en")), true);
  assert.equal(Choice.isEnglishOnly(model("tiny")), false);
});
