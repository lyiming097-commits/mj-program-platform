export function emptyPresalesProgressRound() {
  return { plannedStartDate: "", plannedEndDate: "", submitDate: "", submittedAt: "", note: "", attachmentIds: [] };
}

export function normalizePresalesProgressRound(item = {}) {
  const round = { ...emptyPresalesProgressRound(), ...item };
  delete round.result;
  round.attachmentIds = Array.isArray(item.attachmentIds) ? item.attachmentIds.map(String) : [];
  return round;
}

export function canAddPresalesProgressRound(rounds) {
  const last = rounds.at(-1);
  return !last || Boolean(
    last.plannedStartDate || last.plannedEndDate || last.designDate || String(last.note || "").trim() || last.attachmentIds?.length,
  );
}

export function canRemovePresalesProgressRound(rounds) {
  return rounds.length > 1 && !rounds.at(-1)?.attachmentIds?.length;
}

export function canEditPresalesProgressRound(rounds, index, { editable, managed, progressSubmitted, completed }) {
  return Boolean(editable) && !completed && index >= 0 && index === rounds.length - 1
    && (managed || !progressSubmitted);
}

export function presalesRoundTimeError(round) {
  return round.plannedStartDate && round.plannedEndDate && round.plannedEndDate < round.plannedStartDate
    ? "预计完成时间不能早于计划开始时间" : "";
}

export function presalesRoundTiming(round, now = Date.now(), { completed = false, completedAt = "" } = {}) {
  const end = round.plannedEndDate;
  if (!end) return completed ? { label: "已完成", tone: "done" } : { label: "未设置预计完成时间", tone: "pending" };
  const format = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai" });
  const today = format.format(new Date(now));
  const completedTimestamp = completedAt ? Date.parse(completedAt) : NaN;
  if (completed && !Number.isFinite(completedTimestamp)) return { label: "已完成", tone: "done" };
  const compareDate = completed ? format.format(new Date(completedTimestamp)) : today;
  const days = Math.round((Date.parse(`${compareDate}T00:00:00Z`) - Date.parse(`${end}T00:00:00Z`)) / 86400000);
  if (!Number.isFinite(days)) return { label: "未设置预计完成时间", tone: "pending" };
  if (completed) return days > 0
    ? { label: `延期完成 ${days} 天`, tone: "late" }
    : { label: "按时完成", tone: "done" };
  if (days > 0) return { label: `已延期 ${days} 天`, tone: "late" };
  return { label: round.plannedStartDate && today < round.plannedStartDate ? "未到开始日期" : "未超时", tone: "normal" };
}
