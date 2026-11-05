export const PRESALES_STATISTIC_DIMENSIONS = Object.freeze([
  { value: "all", label: "全部项目", field: "" },
  { value: "nature", label: "按项目性质", field: "项目性质" },
  { value: "stage", label: "按项目阶段分", field: "CRM阶段" },
  { value: "sales", label: "按销售分", field: "销售负责人" },
  { value: "design", label: "按设计负责人", field: "设计负责人" },
]);

// Keep each view's remaining field order. Project IDs, obsolete approval links
// and DingTalk's parent-record field intentionally stay out of this workspace.
const columns = {
  name: { label: "项目名称", width: 250 },
  startedAt: { label: "启动时间", width: 125 },
  amount: { label: "项目金额", width: 140, type: "money" },
  totalArea: { label: "项目总面积", width: 135, type: "area" },
  designArea: { label: "设计面积", width: 125, type: "area" },
  natures: { label: "项目性质", width: 160, type: "tags" },
  latestStage: { label: "项目最新阶段", width: 180 },
  crmStage: { label: "CRM阶段", width: 145 },
  projectLevel: { label: "项目等级", width: 145 },
  description: { label: "项目说明", width: 280, type: "text" },
  tasks: { label: "关联任务", width: 200, type: "tasks" },
  taskProgress: { label: "项目任务进度", width: 165, type: "progress" },
  ownerName: { label: "销售负责人", width: 135 },
  designOwners: { label: "设计负责人", width: 145, type: "people" },
  solutionOwners: { label: "方案负责人", width: 145, type: "people" },
  participants: { label: "参与人汇总", width: 180, type: "people" },
  requirementCount: { label: "项目需求文档", width: 155, type: "attachments" },
  taskCount: { label: "任务总数", width: 105 },
  completedTaskCount: { label: "已完成任务", width: 115 },
  expectedBidAt: { label: "预计招标时间", width: 145 },
  urgency: { label: "紧急程度", width: 120 },
};
const viewFields = {
  all: ["name", "startedAt", "amount", "totalArea", "designArea", "natures", "latestStage", "crmStage",
    "projectLevel", "description", "tasks", "taskProgress", "ownerName", "designOwners", "solutionOwners",
    "participants", "requirementCount", "taskCount", "completedTaskCount"],
  nature: ["name", "natures", "ownerName", "requirementCount", "latestStage", "crmStage", "amount", "expectedBidAt", "urgency",
    "designOwners", "solutionOwners", "projectLevel"],
  stage: ["name", "natures", "description", "startedAt", "ownerName", "requirementCount", "tasks", "participants",
    "completedTaskCount", "taskCount", "taskProgress", "totalArea", "designArea", "latestStage", "crmStage", "amount",
    "expectedBidAt", "urgency", "designOwners", "solutionOwners", "projectLevel"],
  sales: ["name", "ownerName", "natures", "amount", "expectedBidAt", "urgency", "startedAt", "tasks", "latestStage", "crmStage",
    "projectLevel", "taskProgress", "designOwners", "solutionOwners", "participants", "description", "requirementCount",
    "taskCount", "completedTaskCount", "totalArea", "designArea"],
  design: ["name", "projectLevel", "natures", "description", "startedAt", "ownerName", "requirementCount", "tasks",
    "participants", "completedTaskCount", "taskCount", "taskProgress", "totalArea", "designArea", "latestStage", "crmStage",
    "amount", "expectedBidAt", "urgency", "designOwners", "solutionOwners"],
};

export function presalesStatisticColumns(view) {
  return (viewFields[view] || viewFields.all).map(key => ({ key, ...columns[key] }));
}

export function statisticNumber(value, { currency = false, area = false } = {}) {
  if (value === null || value === undefined || value === "" || !Number.isFinite(Number(value))) return "未填写";
  const formatted = Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
  return `${currency ? "￥" : ""}${formatted}${area ? " ㎡" : ""}`;
}
