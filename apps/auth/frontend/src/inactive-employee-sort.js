function departureTimestamp(employee) {
  const timestamp = Date.parse(String(employee?.formerOrganizationRecordedAt || ""));
  return Number.isFinite(timestamp) ? timestamp : Number.NEGATIVE_INFINITY;
}

export function sortInactiveEmployeesByDepartureDate(employees) {
  return [...(Array.isArray(employees) ? employees : [])].sort((left, right) => {
    const leftTimestamp = departureTimestamp(left);
    const rightTimestamp = departureTimestamp(right);
    if (leftTimestamp === rightTimestamp) return 0;
    return rightTimestamp - leftTimestamp;
  });
}
