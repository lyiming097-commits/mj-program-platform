import assert from "node:assert/strict";
import test from "node:test";

import { splitParameterLines } from "./parameterText.js";

test("splits legacy row separators but preserves slashes in values", () => {
  assert.deepEqual(
    splitParameterLines("速度35mm/s / 密度720kg/立方米 / 符合QB/T 2454"),
    ["速度35mm/s", "密度720kg/立方米", "符合QB/T 2454"],
  );
});

test("uses real line breaks when the catalog provides structured rows", () => {
  assert.deepEqual(
    splitParameterLines("输入 / 输出\n速度35mm/s\n符合QB/T 2454"),
    ["输入 / 输出", "速度35mm/s", "符合QB/T 2454"],
  );
});
