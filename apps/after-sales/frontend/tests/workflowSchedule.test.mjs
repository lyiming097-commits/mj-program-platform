import assert from "node:assert/strict";
import test from "node:test";

import {
  MIDSALES_SCHEDULE_DEPENDENCIES,
  PRESALES_SCHEDULE_DEPENDENCIES,
  inheritedScheduleStart,
  schedulePredecessorKeys,
} from "../src/workflowSchedule.js";

test("parallel presales branches do not inherit dates from each other", () => {
  const earlyKeys = new Set(["early-plan", "budget-match", "project-filing"]);
  assert.deepEqual(schedulePredecessorKeys("early-plan", PRESALES_SCHEDULE_DEPENDENCIES, earlyKeys), []);
  assert.deepEqual(schedulePredecessorKeys("budget-match", PRESALES_SCHEDULE_DEPENDENCIES, earlyKeys), []);
  assert.deepEqual(schedulePredecessorKeys("project-filing", PRESALES_SCHEDULE_DEPENDENCIES, earlyKeys), ["budget-match"]);

  const lateKeys = new Set([
    "late-plan", "device-plan", "budget", "device-budget", "cost-control",
    "device-cost-control", "rendering", "tender-plan", "layout", "bid-prep",
  ]);
  assert.deepEqual(schedulePredecessorKeys("device-budget", PRESALES_SCHEDULE_DEPENDENCIES, lateKeys), ["device-plan"]);
  assert.deepEqual(schedulePredecessorKeys("tender-plan", PRESALES_SCHEDULE_DEPENDENCIES, lateKeys), ["device-cost-control"]);
  assert.deepEqual(schedulePredecessorKeys("layout", PRESALES_SCHEDULE_DEPENDENCIES, lateKeys), ["rendering"]);
});

test("project filing inherits only the budget matching end date", () => {
  const result = inheritedScheduleStart("project-filing", PRESALES_SCHEDULE_DEPENDENCIES, {
    "early-plan": { endDate: "2026-09-30" },
    "budget-match": { endDate: "2026-09-19" },
    "project-filing": { startDate: "" },
  });
  assert.deepEqual(result, {
    predecessorKeys: ["budget-match"],
    startDate: "2026-09-19",
  });
});

test("midsales skips disabled nodes when resolving the effective predecessor", () => {
  const result = inheritedScheduleStart("device-install", MIDSALES_SCHEDULE_DEPENDENCIES, {
    "construction-work": { plannedEndDate: "2026-10-08" },
    "device-install": { plannedStartDate: "" },
    "device-debug": { plannedEndDate: "2026-10-18" },
  });
  assert.deepEqual(result, {
    predecessorKeys: ["construction-work"],
    startDate: "2026-10-08",
  });
});

test("an automatic start waits until every resolved predecessor has an end date", () => {
  const result = inheritedScheduleStart("construction-result", PRESALES_SCHEDULE_DEPENDENCIES, {
    layout: { endDate: "2026-11-02" },
    "bid-prep": { endDate: "" },
    "construction-result": { startDate: "" },
  });
  assert.deepEqual(result.predecessorKeys, ["layout", "bid-prep"]);
  assert.equal(result.startDate, "");
});
