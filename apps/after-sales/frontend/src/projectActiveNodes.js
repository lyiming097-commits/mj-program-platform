// Lists and overview use a lightweight server summary; details can also use
// their already loaded nodes. Preserve node keys when parallel labels repeat.
export function projectIsCompleted(project) {
  const status = String(project?.status || project?.statusLabel || project?.status_display || "").toLowerCase();
  return ["completed", "closed", "已完成", "结束"].includes(status);
}

export function projectActiveNodes(project) {
  const type = project?.serviceType || project?.service_type;
  const status = project?.status;
  if (type !== "presales" || (status && !["in_progress", "进行中"].includes(status))) return [];
  const rows = Array.isArray(project?.activeNodes) ? project.activeNodes
    : (project?.nodes || []).filter(node => node.enabled !== false && ["active", "进行中"].includes(node.status));
  return [...new Map(rows.map(node => [String(node.nodeKey || node.node_key || ""), node]))]
    .filter(([key]) => key).map(([key, node]) => ({ ...node, nodeKey: key }));
}
