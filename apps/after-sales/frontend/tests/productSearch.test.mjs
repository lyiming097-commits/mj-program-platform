import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { matchesSearch, pinyinInitials } from "../src/productSearch.js";

test("management search uses mall-style Chinese initials and compact cross-field matches", () => {
  assert.equal(pinyinInitials("乐享款讲台"), "lxkjt");
  assert.equal(matchesSearch("LXK JT", ["乐享款讲台", "ELCP-H22C"]), true);
  assert.equal(matchesSearch("乐享款 ELCP", "乐享款", "ELCP-H22C"), true);
  assert.equal(matchesSearch("ELCP", ["乐享款讲台", "ELCP-H22C"]), true);
  assert.equal(matchesSearch("无关产品", "乐享款讲台", "ELCP-H22C"), false);
});

test("management search fields use one matcher rather than local case-sensitive includes", () => {
  for (const component of [
    "ProjectWorkspace", "ResourceWorkspace", "TeamWorkspace", "RewardWorkspace",
    "ProjectCollaborationPanel",
  ]) {
    const source = readFileSync(new URL(`../src/components/${component}.vue`, import.meta.url), "utf8");
    assert.match(source, /import \{ matchesSearch \} from "@\/productSearch"/);
  }
  const settlement = readFileSync(new URL("../src/components/SettlementWorkspace.vue", import.meta.url), "utf8");
  assert.match(settlement, /matchesDirectorySearchKeyword/);
});
