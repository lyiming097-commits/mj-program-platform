"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const { isAllowedFeishuUrl } = require("./renderer");

test("accepts only HTTPS Feishu document hosts", () => {
  assert.equal(isAllowedFeishuUrl("https://tenant.feishu.cn/wiki/document-token"), true);
  assert.equal(isAllowedFeishuUrl("https://feishu.cn/docx/document-token"), true);
  assert.equal(isAllowedFeishuUrl("http://tenant.feishu.cn/wiki/document-token"), false);
  assert.equal(isAllowedFeishuUrl("https://feishu.cn.example.com/wiki/document-token"), false);
  assert.equal(isAllowedFeishuUrl("https://user@tenant.feishu.cn/wiki/document-token"), false);
});
