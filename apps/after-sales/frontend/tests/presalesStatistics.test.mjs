import assert from "node:assert/strict";
import test from "node:test";
import { statisticNumber } from "../src/presalesStatistics.js";

test("missing statistics are distinct from zero and fractional project amounts remain visible", () => {
  assert.equal(statisticNumber(null, { currency: true }), "未填写");
  assert.equal(statisticNumber(undefined), "未填写");
  assert.equal(statisticNumber(""), "未填写");
  assert.equal(statisticNumber("0.00", { currency: true }), "￥0");
  assert.equal(statisticNumber("0.02", { currency: true }), "￥0.02");
  assert.equal(statisticNumber("1000.25", { area: true }), "1,000.25 ㎡");
});
