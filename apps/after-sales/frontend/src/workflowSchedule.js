function frozenDependencies(entries) {
  return Object.freeze(Object.fromEntries(
    entries.map(([nodeKey, predecessorKeys]) => [nodeKey, Object.freeze(predecessorKeys)]),
  ));
}

// Keep these dependencies aligned with the workflow rendered by ProjectWorkspace
// and the presales rules enforced by the backend.
export const PRESALES_SCHEDULE_DEPENDENCIES = frozenDependencies([
  ["early-approval", []],
  ["early-plan", ["early-approval"]],
  ["budget-match", ["early-approval"]],
  ["project-filing", ["budget-match"]],
  ["early-plan-result", ["early-plan", "project-filing"]],
  ["late-approval", ["early-plan-result"]],
  ["late-plan", ["late-approval"]],
  ["device-plan", ["late-approval"]],
  ["budget", ["late-plan"]],
  ["device-budget", ["device-plan"]],
  ["cost-control", ["budget"]],
  ["device-cost-control", ["device-budget"]],
  ["rendering", ["cost-control"]],
  ["tender-plan", ["device-cost-control"]],
  ["layout", ["rendering"]],
  ["bid-prep", ["tender-plan"]],
  ["construction-result", ["layout", "bid-prep"]],
  ["construction", ["construction-result"]],
  ["project-end", ["construction"]],
]);

export const MIDSALES_SCHEDULE_DEPENDENCIES = frozenDependencies([
  ["midsales-project", []],
  ["construction-work", ["midsales-project"]],
  ["furniture-install", ["construction-work"]],
  ["device-install", ["furniture-install"]],
  ["device-debug", ["device-install"]],
  ["school-support", ["device-debug"]],
  ["project-acceptance", ["school-support"]],
  ["midsales-project-end", ["project-acceptance"]],
]);

export function schedulePredecessorKeys(nodeKey, dependencies, availableKeys) {
  const available = availableKeys instanceof Set ? availableKeys : new Set(availableKeys);
  const resolved = [];
  const resolvedSet = new Set();
  const visited = new Set([nodeKey]);

  function visit(currentKey) {
    for (const predecessorKey of dependencies[currentKey] || []) {
      if (available.has(predecessorKey)) {
        if (!resolvedSet.has(predecessorKey)) {
          resolvedSet.add(predecessorKey);
          resolved.push(predecessorKey);
        }
        continue;
      }
      if (visited.has(predecessorKey)) continue;
      visited.add(predecessorKey);
      visit(predecessorKey);
    }
  }

  visit(nodeKey);
  return resolved;
}

export function inheritedScheduleStart(nodeKey, dependencies, plansByKey) {
  const predecessorKeys = schedulePredecessorKeys(
    nodeKey,
    dependencies,
    Object.keys(plansByKey),
  );
  const endDates = predecessorKeys.map((key) => String(
    plansByKey[key]?.endDate || plansByKey[key]?.plannedEndDate || "",
  ));
  return {
    predecessorKeys,
    startDate: endDates.length && endDates.every(Boolean)
      ? [...endDates].sort().at(-1)
      : "",
  };
}
