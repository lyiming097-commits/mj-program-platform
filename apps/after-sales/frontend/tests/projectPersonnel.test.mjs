import assert from "node:assert/strict";
import test from "node:test";
import { personnelAssignmentMembers, personnelAssignmentSelection } from "../src/projectPersonnel.js";

test("legacy shared work instructions remain visible until each person has an explicit note", () => {
  const previous = { members: [{ userId: "a", name: "甲" }, { userId: "b", name: "乙" }], note: "原有工作说明" };
  const members = personnelAssignmentMembers(previous);
  assert.deepEqual(members.map(member => member.note), ["原有工作说明", "原有工作说明"]);
  const saved = personnelAssignmentSelection(members, previous);
  saved.members[1].note = "";
  assert.equal(personnelAssignmentMembers(saved)[1].note, "", "an intentionally empty personal note must not inherit another person's text");
});

test("searching, reordering and removing selections keep work instructions with their owner", () => {
  const previous = { members: [{ userId: "a", name: "同名", note: "方案" }, { userId: "b", name: "同名", note: "预算" }] };
  const next = personnelAssignmentSelection([{ userId: "b", name: "同名" }, { userId: "c", name: "新同事" }], previous);
  assert.deepEqual(next.members, [{ userId: "b", name: "同名", note: "预算" }, { userId: "c", name: "新同事", note: "" }]);
  assert.deepEqual(next.userIds, ["b", "c"]);
});
