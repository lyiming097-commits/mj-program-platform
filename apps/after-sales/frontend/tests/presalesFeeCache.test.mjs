import assert from "node:assert/strict";
import test from "node:test";
import { clearPresalesFeeCache, loadPresalesFeeCache, readPresalesFeeCache } from "../src/presalesFeeCache.js";

test("reopening a fee tab joins pending reads and reuses fresh amounts, including zero and missing values", async () => {
  clearPresalesFeeCache();
  let finish;
  let calls = 0;
  const fetcher = () => {
    calls += 1;
    return new Promise(resolve => { finish = resolve; });
  };
  const first = loadPresalesFeeCache("session-one", "project-one", "mall", fetcher);
  const reopened = loadPresalesFeeCache("session-one", "project-one", "mall", fetcher);
  assert.equal(first, reopened);
  await Promise.resolve();
  finish({ externalQuote: 0, actualFee: null });
  await first;
  assert.deepEqual(await loadPresalesFeeCache("session-one", "project-one", "mall", fetcher), { externalQuote: 0, actualFee: null });
  assert.equal(calls, 1);
  assert.equal(readPresalesFeeCache("session-one", "other-project", "mall"), null);
  assert.equal(readPresalesFeeCache("session-one", "project-one", "crm"), null);
});

test("cached amounts have a freshness window and a hard limit rather than being retained forever", async t => {
  let now = 1_000_000;
  t.mock.method(Date, "now", () => now);
  await loadPresalesFeeCache("expiry-session", "project-one", "crm", () => 50);
  now += 31_000;
  assert.deepEqual(readPresalesFeeCache("expiry-session", "project-one", "crm"), { value: 50, fresh: false });
  now += 300_000;
  assert.equal(readPresalesFeeCache("expiry-session", "project-one", "crm"), null);
});

test("switching accounts clears amounts and late responses cannot repopulate an old account's cache", async () => {
  let finish;
  const oldRead = loadPresalesFeeCache("old-session", "project-one", "mall", () => new Promise(resolve => { finish = resolve; }));
  await Promise.resolve();
  await loadPresalesFeeCache("new-session", "project-one", "mall", () => 99);
  finish(1);
  await oldRead;
  assert.equal(readPresalesFeeCache("new-session", "project-one", "mall").value, 99);
  assert.equal(readPresalesFeeCache("old-session", "project-one", "mall"), null);
});

test("a denied source read clears cached financial data and cannot cache another late source", async () => {
  let finish;
  await loadPresalesFeeCache("denied-session", "project-one", "crm", () => 50);
  const otherRead = loadPresalesFeeCache("denied-session", "project-two", "mall", () => new Promise(resolve => { finish = resolve; }));
  await Promise.resolve();
  const denied = Object.assign(new Error("denied"), { status: 403 });
  await assert.rejects(loadPresalesFeeCache("denied-session", "project-one", "mall", () => Promise.reject(denied)), { status: 403 });
  finish(100);
  await otherRead;
  assert.equal(readPresalesFeeCache("denied-session", "project-one", "crm"), null);
  assert.equal(readPresalesFeeCache("denied-session", "project-two", "mall"), null);
});
