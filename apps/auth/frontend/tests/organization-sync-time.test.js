import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { formatOrganizationSyncTime } from "../src/organization-sync-time.js";

test("last successful sync timestamp is shown in the viewer's local time", () => {
  const localDate = new Date(2026, 8, 21, 10, 5);
  assert.equal(formatOrganizationSyncTime(localDate.toISOString()), "2026-09-21 10:05");
  assert.equal(formatOrganizationSyncTime(""), "");
  assert.equal(formatOrganizationSyncTime("not-a-date"), "");
});

test("desktop and phone sync actions show and refresh the last successful sync time", () => {
  for (const variant of ["web", "phone"]) {
    const source = readFileSync(
      new URL(`../src/components/settings/SettingsWorkspace_${variant}.vue`, import.meta.url),
      "utf8",
    );
    assert.match(source, /useOrganizationSyncTime\(\)/);
    assert.match(source, /if \(canSyncContacts\.value\) void refreshLastSyncTime\(\)/);
    assert.match(source, /if \(!result\) return;\s+void refreshLastSyncTime\(\)/);
    assert.match(source, /aria-live="polite">\{\{ lastSyncLabel \}\}/);
  }
});
