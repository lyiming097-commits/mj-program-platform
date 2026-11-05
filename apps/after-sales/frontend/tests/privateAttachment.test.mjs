import assert from "node:assert/strict";
import test from "node:test";
import {
  downloadPrivateAttachment,
  fetchPrivateAttachment,
  isPdfAttachment,
} from "../src/privateAttachment.js";

test("only PDF attachments use the document preview", () => {
  assert.equal(isPdfAttachment({ originalName: "说明书.pdf", mimeType: "application/pdf" }), true);
  assert.equal(isPdfAttachment({ originalName: "清单.xlsx", mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }), false);
  assert.equal(isPdfAttachment({ originalName: "photo.png", mimeType: "image/png" }), false);
});

test("private files are read through the authenticated API client", async () => {
  const blob = new Blob(["%PDF-1.4"], { type: "application/pdf" });
  const calls = [];
  const result = await fetchPrivateAttachment(
    { downloadUrl: "/api/after-sales/attachments/7/download" },
    async (...args) => { calls.push(args); return { blob: async () => blob }; },
  );
  assert.equal(result, blob);
  assert.deepEqual(calls, [["/api/after-sales/attachments/7/download", {}, null, { timeoutMs: 600_000 }]]);
});

test("download uses a temporary URL and releases it", () => {
  const blob = new Blob(["workbook"]);
  const events = [];
  const link = {
    click: () => events.push("click"),
    remove: () => events.push("remove"),
  };
  const timers = [];
  downloadPrivateAttachment(blob, "清单.xlsx", {
    documentRef: {
      createElement: (tag) => { assert.equal(tag, "a"); return link; },
      body: { appendChild: (value) => { assert.equal(value, link); events.push("append"); } },
    },
    urlApi: {
      createObjectURL: (value) => { assert.equal(value, blob); return "blob:private-file"; },
      revokeObjectURL: (url) => events.push(`revoke:${url}`),
    },
    schedule: (callback, delay) => timers.push([callback, delay]),
  });

  assert.equal(link.href, "blob:private-file");
  assert.equal(link.download, "清单.xlsx");
  assert.deepEqual(events, ["append", "click", "remove"]);
  assert.equal(timers[0][1], 60_000);
  timers[0][0]();
  assert.equal(events.at(-1), "revoke:blob:private-file");
});

test("a failed download releases its temporary URL immediately", () => {
  const released = [];
  assert.throws(() => downloadPrivateAttachment(new Blob(["broken"]), "清单.xlsx", {
    documentRef: {
      createElement: () => ({ click: () => { throw new Error("download blocked"); }, remove: () => {} }),
      body: { appendChild: () => {} },
    },
    urlApi: {
      createObjectURL: () => "blob:failed-download",
      revokeObjectURL: (url) => released.push(url),
    },
  }), /download blocked/);
  assert.deepEqual(released, ["blob:failed-download"]);
});
