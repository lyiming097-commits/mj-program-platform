import assert from "node:assert/strict";
import test from "node:test";

import { sortInactiveEmployeesByDepartureDate } from "../src/inactive-employee-sort.js";

test("inactive employees sort by departure time descending with missing dates last", () => {
  const source = [
    { userId: "missing", formerOrganizationRecordedAt: "" },
    { userId: "middle-first", formerOrganizationRecordedAt: "2026-09-11T08:00:00Z" },
    { userId: "latest", formerOrganizationRecordedAt: "2026-09-22T08:00:00Z" },
    { userId: "invalid", formerOrganizationRecordedAt: "not-a-date" },
    { userId: "middle-second", formerOrganizationRecordedAt: "2026-09-11T08:00:00Z" },
    { userId: "earliest", formerOrganizationRecordedAt: "2026-08-27T08:00:00Z" },
  ];

  assert.deepEqual(sortInactiveEmployeesByDepartureDate(source).map((item) => item.userId), [
    "latest",
    "middle-first",
    "middle-second",
    "earliest",
    "missing",
    "invalid",
  ]);
  assert.equal(source[0].userId, "missing");
});
