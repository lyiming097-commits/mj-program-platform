import assert from "node:assert/strict";
import test from "node:test";
import { createRenderer } from "vue";
import { useDebouncedAutosave } from "../src/composables/useDebouncedAutosave.js";
import { allCollectionRows } from "../src/collectionPagination.js";

const renderer = createRenderer({
  createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
  insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {},
  parentNode: () => null, nextSibling: () => null,
});
function mountAutosave(t, save) {
  const previousWindow = globalThis.window;
  globalThis.window = { setTimeout, clearTimeout };
  let autosave;
  const app = renderer.createApp({ setup() {
    autosave = useDebouncedAutosave(save, { delay: 60_000 });
    return () => null;
  } });
  app.mount({});
  t.after(() => { app.unmount(); globalThis.window = previousWindow; });
  return { autosave, app };
}

test("failed autosaves retain the latest nested draft for retry", async t => {
  let fail = true;
  const saved = [];
  const { autosave } = mountAutosave(t, async value => {
    if (fail) throw new Error("network unavailable");
    saved.push(value);
  });
  autosave.reset({ note: "original" });
  const draft = { note: "new", nested: { fee: 2 } };
  autosave.schedule(draft);
  draft.nested.fee = 3;
  await assert.rejects(autosave.flush(), /network unavailable/);
  assert.equal(autosave.pending.value, true);
  assert.equal(autosave.saving.value, false);
  fail = false;
  await autosave.flush();
  assert.deepEqual(saved, [{ note: "new", nested: { fee: 2 } }]);
  assert.equal(autosave.pending.value, false);
});

test("typing during a save is serialized, including reverting to the original value", async t => {
  let release;
  const saved = [];
  const { autosave } = mountAutosave(t, async value => {
    saved.push(value);
    if (saved.length === 1) await new Promise(resolve => { release = resolve; });
  });
  autosave.reset({ note: "original" });
  autosave.schedule({ note: "first" });
  const flushing = autosave.flush();
  await Promise.resolve();
  assert.equal(autosave.saving.value, true);
  autosave.schedule({ note: "second" });
  autosave.schedule({ note: "original" });
  release();
  await flushing;
  assert.deepEqual(saved, [{ note: "first" }, { note: "original" }]);
  assert.equal(autosave.pending.value, false);
});

test("undo before saving cancels the draft, and confirmed discard does not send it on unmount", async t => {
  const saved = [];
  const { autosave, app } = mountAutosave(t, async value => saved.push(value));
  autosave.reset({ note: "original" });
  autosave.schedule({ note: "changed" });
  autosave.schedule({ note: "original" });
  await autosave.flush();
  assert.equal(autosave.pending.value, false);
  autosave.schedule({ note: "discard me" });
  app.unmount();
  await autosave.flush();
  assert.deepEqual(saved, []);
});

test("reset during an older save cannot clear a new project's pending draft", async t => {
  let release;
  const saved = [];
  const { autosave } = mountAutosave(t, async value => {
    saved.push(value);
    if (saved.length === 1) await new Promise(resolve => { release = resolve; });
  });
  autosave.schedule({ project: 1 });
  const first = autosave.flush();
  await Promise.resolve();
  autosave.reset({ project: 2, note: "initial" });
  autosave.schedule({ project: 2, note: "edited" });
  release();
  await first;
  assert.equal(autosave.pending.value, true);
  await autosave.flush();
  assert.deepEqual(saved, [{ project: 1 }, { project: 2, note: "edited" }]);
});

test("directory pagination reads beyond 100, preserves filters and deduplicates page boundaries", async () => {
  const rows = Array.from({ length: 245 }, (_, id) => ({ id: id + 1 }));
  const calls = [];
  const result = await allCollectionRows(async params => {
    calls.push(params);
    return { items: rows.slice((params.page - 1) * 100, params.page * 100), totalPages: 3 };
  }, { providerId: 7, page_size: 200 });
  assert.deepEqual(result, rows);
  assert.deepEqual(calls.map(item => item.page), [1, 2, 3]);
  assert.ok(calls.every(item => item.providerId === 7 && item.page_size === 100));
  assert.deepEqual(await allCollectionRows(async ({ page }) => ({ items: [{ id: page }, { id: 2 }], totalPages: 2 })), [{ id: 1 }, { id: 2 }]);
});

test("a failed later page never masquerades as the complete collection", async () => {
  await assert.rejects(allCollectionRows(async ({ page }) => {
    if (page === 2) throw new Error("page 2 unavailable");
    return { items: [{ id: 1 }], totalPages: 2 };
  }), /page 2 unavailable/);
});
