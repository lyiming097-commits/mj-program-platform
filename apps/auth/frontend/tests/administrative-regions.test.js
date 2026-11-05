import assert from "node:assert/strict";
import test from "node:test";

import {
  administrativeRegions,
  administrativeRegionStats,
  buildAdministrativeRegionTree,
  searchAdministrativeRegions,
} from "../src/administrative-regions.js";

test("administrative region data contains the complete province city district hierarchy", () => {
  assert.deepEqual(administrativeRegionStats, {
    provinces: 34,
    cities: 369,
    districts: 3478,
  });
  const zhejiang = administrativeRegions.find((item) => item.code === "330000");
  const hangzhou = zhejiang.cities.find((item) => item.code === "330100");
  assert.equal(zhejiang.name, "浙江省");
  assert.equal(hangzhou.name, "杭州市");
  assert.equal(hangzhou.districts.some((item) => item.name === "临平区"), true);
  assert.equal(hangzhou.districts.some((item) => item.name === "钱塘区"), true);
  assert.equal(hangzhou.districts.some((item) => ["下城区", "江干区"].includes(item.name)), false);
});

test("region search matches the current level name or administrative code", () => {
  assert.deepEqual(searchAdministrativeRegions("余杭区").map((item) => [item.path, item.code]), [
    ["浙江省 / 杭州市 / 余杭区", "330110"],
  ]);
  assert.equal(searchAdministrativeRegions("330100")[0].path, "浙江省 / 杭州市");
});

test("tree builder ignores orphan rows instead of assigning them to the wrong parent", () => {
  const tree = buildAdministrativeRegionTree({
    province_list: { 110000: "甲省" },
    city_list: { 110100: "甲市", 990100: "孤立市" },
    county_list: { 110101: "甲区", 110201: "孤立区" },
  });
  assert.deepEqual(tree, [{
    code: "110000",
    name: "甲省",
    cities: [{
      code: "110100",
      name: "甲市",
      districts: [{ code: "110101", name: "甲区" }],
    }],
  }]);
});
