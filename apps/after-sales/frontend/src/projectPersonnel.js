export function personnelMembers(selection) {
  const rows = Array.isArray(selection?.members) ? selection.members
    : selection?.userId ? [selection] : [];
  return [...new Map(rows.filter(row => row?.userId).map(row => {
    const userId = String(row.userId).trim();
    return [userId, { userId, name: String(row.name || userId).trim(),
      ...(Object.hasOwn(row, "note") ? { note: String(row.note || "") } : {}) }];
  })).values()];
}

export function personnelAssignmentMembers(selection) {
  return personnelMembers(selection).map(member => ({ ...member,
    note: Object.hasOwn(member, "note") ? member.note : String(selection?.note || "") }));
}

export function personnelAssignmentSelection(selected, previous) {
  const existing = personnelAssignmentMembers(previous);
  const byId = new Map(existing.map(member => [member.userId, member]));
  const members = personnelMembers({ members: selected }).map((member, index) => ({ ...member,
    note: byId.get(member.userId)?.note ?? (existing.length === 0 && index === 0 ? String(previous?.note || "") : ""),
  }));
  return { ...personnelSelection(members), note: members[0]?.note || "" };
}

export function personnelSelection(members) {
  const rows = personnelMembers({ members });
  return { members: rows, userIds: rows.map(row => row.userId),
    userId: rows[0]?.userId || "", name: rows.map(row => row.name).join("、") };
}
