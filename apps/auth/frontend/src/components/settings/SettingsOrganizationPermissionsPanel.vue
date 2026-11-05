<script setup>
import { backdropDismiss as vBackdropDismiss } from "@platform-ui/backdrop-dismiss.js";
import { matchesDirectorySearchKeyword } from "@platform-ui";
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import {
  Building2,
  ChevronDown,
  LoaderCircle,
  Plus,
  Search,
  ShieldCheck,
  UserMinus,
  UserRound,
  X,
} from "@lucide/vue";

import { apiGet, apiPut } from "@/api";
import { useSettingsFeedback } from "./useSettingsFeedback";
import SettingsUnsavedChangesDialog from "@/components/settings/SettingsUnsavedChangesDialog.vue";

const props = defineProps({
  apiPath: { type: String, default: "/api/org/permissions" },
  permissionLabel: { type: String, default: "后台管理权限" },
  permissionNote: { type: String, default: "可使用后台管理内全部功能，代理除外。" },
  memberLabel: { type: String, default: "后台管理员" },
  roleOptions: { type: Array, default: () => [] },
  activeRoleId: { type: String, default: "" },
});
const emit = defineEmits(["dirty-change", "saving-change", "role-select"]);
const rolePicker = ref(null);

const PERMISSION = {
  id: "admin",
  get label() { return props.permissionLabel; },
  get note() { return props.permissionNote; },
};
const SCOPE_DEPARTMENT = "department";
const SCOPE_DEPARTMENT_WITH_SUB = "departmentSub";
const SCOPE_EMPLOYEE = "employee";
const SCOPE_EXCLUDED_EMPLOYEE = "excludedEmployee";
const SOURCE_GROUPS = [
  { id: SCOPE_DEPARTMENT, label: "部门", icon: Building2, empty: "未添加部门" },
  { id: SCOPE_EMPLOYEE, label: "人员", icon: UserRound, empty: "未添加人员" },
];
const VALID_SCOPES = new Set([
  SCOPE_DEPARTMENT,
  SCOPE_EMPLOYEE,
  SCOPE_EXCLUDED_EMPLOYEE,
]);

const loading = ref(true);
const saving = ref(false);
const loaded = ref(false);
const conflict = ref(false);
const saveSucceeded = ref(false);
const showFeedback = useSettingsFeedback();
const errorMessage = ref("");
const departmentTree = ref([]);
const departments = ref([]);
const employees = ref([]);
const rules = ref([]);
const revision = ref("");
const orgRevision = ref("");
const snapshot = ref("");
const expandedDepartmentIds = ref(new Set());
const refreshConfirmOpen = ref(false);
const sourcePickerInput = ref(null);
const sourcePickerPanel = ref(null);
let sourcePickerReturnFocus = null;

const sourcePicker = reactive({
  open: false,
  scopeType: SCOPE_DEPARTMENT,
  keyword: "",
});

const departmentByIdMap = computed(() => new Map(
  departments.value.map((department) => [department.id, department]),
));
const employeeByIdMap = computed(() => new Map(
  employees.value.map((employee) => [employee.id, employee]),
));
const departmentSources = computed(() => rulesFor(SCOPE_DEPARTMENT));
const employeeSources = computed(() => rulesFor(SCOPE_EMPLOYEE));
const departmentSourceMap = computed(() => new Map(
  departmentSources.value.map((source) => [source.targetId, source]),
));
const employeeSourceMap = computed(() => new Map(
  employeeSources.value.map((source) => [source.targetId, source]),
));
const forcedDepartmentIds = computed(() => {
  const ids = new Set();
  departmentSources.value.forEach((source) => {
    if (!source.includeSubDepartments) return;
    const department = departmentById(source.targetId);
    (department?.childIds || []).forEach((id) => ids.add(id));
  });
  return ids;
});
const sourceGroups = computed(() => SOURCE_GROUPS.map((group) => ({
  ...group,
  rows: rulesFor(group.id),
})));
const memberRows = computed(() => memberRowsForRules(rules.value));
const excludedRows = computed(() => excludedRowsForRules(rules.value));
const sourceTotal = computed(() => departmentSources.value.length + employeeSources.value.length);
const permissionDirty = computed(() => (
  loaded.value && snapshot.value !== serializeRules(rules.value)
));
const saveButtonText = computed(() => (
  saveSucceeded.value && !permissionDirty.value ? "已保存" : "保存"
));
const statusText = computed(() => {
  if (saving.value) return "正在保存...";
  if (conflict.value) return "配置版本冲突，请重新加载后核对";
  if (permissionDirty.value) return "有未保存的修改";
  if (saveSucceeded.value) return "权限配置已保存";
  return `按部门和人员配置${props.permissionLabel}`;
});
const filteredDepartmentTree = computed(() => filterDepartmentTree(
  departmentTree.value,
  sourcePicker.keyword.trim().toLowerCase(),
));
const sourceDepartmentRows = computed(() => flattenVisibleDepartments(
  filteredDepartmentTree.value,
  0,
  Boolean(sourcePicker.keyword.trim()),
));
const sourceEmployeeRows = computed(() => {
  const keyword = sourcePicker.keyword.trim().toLowerCase();
  return employees.value
    .map((employee, index) => ({
      id: employee.id,
      name: employee.name,
      meta: employeeDepartmentText(employee),
      employee,
      selected: employeeSourceMap.value.has(employee.id),
      index,
    }))
    .filter((row) => !keyword || employeeMatches(row.employee, keyword))
    .sort((left, right) => {
      if (left.selected !== right.selected) return left.selected ? -1 : 1;
      return left.name.localeCompare(right.name, "zh-Hans-CN") || left.index - right.index;
    })
    .slice(0, 160);
});

function normalizeId(value) {
  return String(value ?? "").trim();
}

function normalizeBoolean(value, fallback = false) {
  if (value === undefined || value === null) return fallback;
  if (typeof value === "boolean") return value;
  const normalized = String(value).trim().toLowerCase();
  if (["1", "true", "yes", "y", "on"].includes(normalized)) return true;
  if (["0", "false", "no", "n", "off"].includes(normalized)) return false;
  return fallback;
}

function normalizeSortOrder(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function normalizeDepartmentNodes(nodes = []) {
  return (Array.isArray(nodes) ? nodes : [])
    .map((item) => {
      const id = normalizeId(item?.deptId ?? item?.dept_id ?? item?.id);
      if (!id) return null;
      return {
        id,
        name: normalizeId(item?.name) || id,
        pinyin: normalizeId(item?.pinyin),
        pinyinInitials: normalizeId(item?.pinyinInitials ?? item?.pinyin_initials).toLowerCase(),
        departmentPathText: normalizeId(item?.departmentPathText ?? item?.department_path_text),
        sortOrder: normalizeSortOrder(item?.sortOrder ?? item?.sort_order),
        children: normalizeDepartmentNodes(item?.children || []),
      };
    })
    .filter(Boolean)
    .sort((left, right) => (
      left.sortOrder - right.sortOrder
      || left.name.localeCompare(right.name, "zh-Hans-CN")
    ));
}

function cropEnabledDepartmentTree(nodes, enabledIds) {
  return nodes.flatMap((node) => {
    const children = cropEnabledDepartmentTree(node.children || [], enabledIds);
    if (!enabledIds.has(node.id)) return children;
    return [{ ...node, children }];
  });
}

function collectDepartmentIds(nodes = []) {
  return nodes.flatMap((node) => [node.id, ...collectDepartmentIds(node.children || [])]);
}

function decorateDepartmentTree(nodes = [], parentId = "", depth = 0) {
  return nodes.map((node) => {
    const children = decorateDepartmentTree(node.children || [], node.id, depth + 1);
    return {
      ...node,
      parentId,
      depth,
      childIds: collectDepartmentIds(children),
      children,
    };
  });
}

function flattenDepartments(nodes = [], output = []) {
  nodes.forEach((node) => {
    output.push({ ...node, children: undefined });
    flattenDepartments(node.children || [], output);
  });
  return output;
}

function normalizeEmployeeDepartment(item) {
  if (typeof item === "string" || typeof item === "number") {
    const id = normalizeId(item);
    return id ? { id, name: departmentById(id)?.name || id, pinyin: "", pinyinInitials: "", departmentPathText: "" } : null;
  }
  const id = normalizeId(item?.deptId ?? item?.dept_id ?? item?.id);
  const name = normalizeId(item?.name) || departmentById(id)?.name || id;
  return id || name ? {
    id,
    name,
    pinyin: normalizeId(item?.pinyin),
    pinyinInitials: normalizeId(item?.pinyinInitials ?? item?.pinyin_initials).toLowerCase(),
    departmentPathText: normalizeId(item?.departmentPathText ?? item?.department_path_text),
  } : null;
}

function normalizeEmployee(item, enabledIds) {
  const id = normalizeId(item?.userId ?? item?.user_id ?? item?.id);
  const rawDepartments = Array.isArray(item?.departments)
    ? item.departments
    : (Array.isArray(item?.departmentIds) ? item.departmentIds : []);
  return {
    id,
    name: normalizeId(item?.name ?? item?.rawName) || id,
    avatarUrl: normalizeId(item?.avatarUrl ?? item?.avatar_url),
    pinyin: normalizeId(item?.pinyin),
    pinyinInitials: normalizeId(item?.pinyinInitials ?? item?.pinyin_initials).toLowerCase(),
    departments: rawDepartments
      .map(normalizeEmployeeDepartment)
      .filter((department) => department && enabledIds.has(department.id)),
  };
}

function normalizeRule(item, fallbackOrder = 0) {
  const rawScopeType = normalizeId(item?.scopeType ?? item?.scope_type);
  const includeSubDepartments = rawScopeType === SCOPE_DEPARTMENT_WITH_SUB
    || normalizeBoolean(item?.includeSubDepartments ?? item?.include_sub_departments);
  const scopeType = rawScopeType === SCOPE_DEPARTMENT_WITH_SUB
    ? SCOPE_DEPARTMENT
    : rawScopeType;
  return {
    permission: normalizeId(item?.permission) || PERMISSION.id,
    scopeType,
    targetId: normalizeId(item?.targetId ?? item?.target_id),
    targetName: normalizeId(item?.targetName ?? item?.target_name),
    sortOrder: normalizeSortOrder(item?.sortOrder ?? item?.sort_order, fallbackOrder),
    includeSubDepartments: scopeType === SCOPE_DEPARTMENT && includeSubDepartments,
  };
}

function departmentById(id) {
  return departmentByIdMap.value.get(normalizeId(id)) || null;
}

function employeeById(id) {
  return employeeByIdMap.value.get(normalizeId(id)) || null;
}

function employeeInitial(employee) {
  return normalizeId(employee?.name || employee?.id).slice(0, 1) || "?";
}

function employeeDepartmentIds(employee) {
  return (employee?.departments || []).map((department) => department.id).filter(Boolean);
}

function employeeDepartmentText(employee) {
  const names = (employee?.departments || []).map((department) => department.name).filter(Boolean);
  return names.length ? names.join(" / ") : "未分配部门";
}

function departmentMatches(department, keyword) {
  return matchesDirectorySearchKeyword(keyword, {
    names: [department?.name, department?.departmentPathText],
    ids: department?.id,
    pinyin: department?.pinyin,
    pinyinInitials: department?.pinyinInitials,
  });
}

function employeeMatches(employee, keyword) {
  return matchesDirectorySearchKeyword(keyword, {
    names: employee?.name,
    ids: employee?.id,
    pinyin: employee?.pinyin,
    pinyinInitials: employee?.pinyinInitials,
  }) || (employee?.departments || []).some((department) => departmentMatches(department, keyword));
}

function filterDepartmentTree(nodes, keyword) {
  if (!keyword) return nodes;
  return nodes.map((node) => {
    const matchingChildren = filterDepartmentTree(node.children || [], keyword);
    if (departmentMatches(node, keyword)) return node;
    return matchingChildren.length ? { ...node, children: matchingChildren } : null;
  }).filter(Boolean);
}

function flattenVisibleDepartments(nodes, depth = 0, forceOpen = false, output = []) {
  nodes.forEach((node) => {
    const hasChildren = Boolean(node.children?.length);
    const expanded = forceOpen || expandedDepartmentIds.value.has(node.id);
    output.push({
      id: node.id,
      name: node.name,
      department: node,
      depth,
      hasChildren,
      expanded,
      memberCount: departmentUserCount(node, true),
    });
    if (hasChildren && expanded) {
      flattenVisibleDepartments(node.children, depth + 1, forceOpen, output);
    }
  });
  return output;
}

function departmentUserCount(department, includeSubDepartments = false) {
  const departmentIds = new Set([
    department?.id,
    ...(includeSubDepartments ? (department?.childIds || []) : []),
  ].filter(Boolean));
  return employees.value.filter((employee) => (
    employeeDepartmentIds(employee).some((id) => departmentIds.has(id))
  )).length;
}

function ruleKey(rule) {
  return `${rule.permission}:${rule.scopeType}:${rule.targetId}`;
}

function targetNameForRule(rule) {
  if (rule.scopeType === SCOPE_DEPARTMENT) {
    return departmentById(rule.targetId)?.name || rule.targetName || rule.targetId;
  }
  return employeeById(rule.targetId)?.name || rule.targetName || rule.targetId;
}

function rulesFor(scopeType, items = rules.value) {
  return items
    .filter((rule) => rule.permission === PERMISSION.id && rule.scopeType === scopeType)
    .sort((left, right) => (
      left.sortOrder - right.sortOrder
      || targetNameForRule(left).localeCompare(targetNameForRule(right), "zh-Hans-CN")
    ));
}

function departmentIdsForRules(items) {
  const ids = new Set();
  rulesFor(SCOPE_DEPARTMENT, items).forEach((rule) => {
    const department = departmentById(rule.targetId);
    ids.add(rule.targetId);
    if (rule.includeSubDepartments) {
      (department?.childIds || []).forEach((id) => ids.add(id));
    }
  });
  return ids;
}

function departmentIncludedUserIds(items) {
  const departmentIds = departmentIdsForRules(items);
  return new Set(employees.value
    .filter((employee) => employeeDepartmentIds(employee).some((id) => departmentIds.has(id)))
    .map((employee) => employee.id));
}

function normalizeRules(items = rules.value) {
  const normalized = [];
  const seen = new Set();
  (Array.isArray(items) ? items : []).forEach((item, index) => {
    const rule = normalizeRule(item, index);
    if (rule.permission !== PERMISSION.id || !VALID_SCOPES.has(rule.scopeType) || !rule.targetId) return;
    const key = ruleKey(rule);
    if (seen.has(key)) return;
    seen.add(key);
    normalized.push({
      ...rule,
      targetName: targetNameForRule(rule),
      includeSubDepartments: rule.scopeType === SCOPE_DEPARTMENT && rule.includeSubDepartments,
    });
  });

  const includedByDepartment = departmentIncludedUserIds(normalized);
  return normalized.filter((rule) => (
    rule.scopeType !== SCOPE_EXCLUDED_EMPLOYEE || includedByDepartment.has(rule.targetId)
  ));
}

function sourceNamesForEmployee(employee, items) {
  const names = [];
  if (rulesFor(SCOPE_EMPLOYEE, items).some((rule) => rule.targetId === employee.id)) {
    names.push("单独人员");
  }
  const employeeDepartmentIdSet = new Set(employeeDepartmentIds(employee));
  rulesFor(SCOPE_DEPARTMENT, items).forEach((rule) => {
    const department = departmentById(rule.targetId);
    const scopeIds = new Set([
      rule.targetId,
      ...(rule.includeSubDepartments ? (department?.childIds || []) : []),
    ]);
    if (![...employeeDepartmentIdSet].some((id) => scopeIds.has(id))) return;
    names.push(`${targetNameForRule(rule)}${rule.includeSubDepartments ? "（含下级）" : ""}`);
  });
  return [...new Set(names)];
}

function baseMemberRows(items) {
  const departmentIds = departmentIdsForRules(items);
  const directIds = new Set(rulesFor(SCOPE_EMPLOYEE, items).map((rule) => rule.targetId));
  return employees.value.map((employee) => {
    const includedByDepartment = employeeDepartmentIds(employee).some((id) => departmentIds.has(id));
    const includedByEmployee = directIds.has(employee.id);
    if (!includedByDepartment && !includedByEmployee) return null;
    return {
      userId: employee.id,
      name: employee.name,
      employee,
      departmentText: employeeDepartmentText(employee),
      sourceText: sourceNamesForEmployee(employee, items).join(" / "),
      includedByDepartment,
    };
  }).filter(Boolean).sort((left, right) => (
    left.name.localeCompare(right.name, "zh-Hans-CN") || left.userId.localeCompare(right.userId)
  ));
}

function excludedUserIds(items) {
  return new Set(rulesFor(SCOPE_EXCLUDED_EMPLOYEE, items).map((rule) => rule.targetId));
}

function memberRowsForRules(items) {
  const excluded = excludedUserIds(items);
  return baseMemberRows(items).filter((row) => !excluded.has(row.userId));
}

function excludedRowsForRules(items) {
  const excluded = excludedUserIds(items);
  return baseMemberRows(items).filter((row) => row.includedByDepartment && excluded.has(row.userId));
}

function rulesForApi(items = rules.value) {
  return normalizeRules(items).map((rule, index) => {
    const scopeType = rule.scopeType === SCOPE_DEPARTMENT && rule.includeSubDepartments
      ? SCOPE_DEPARTMENT_WITH_SUB
      : rule.scopeType;
    return {
      scopeType,
      targetId: rule.targetId,
      targetName: targetNameForRule(rule),
      sortOrder: index,
    };
  });
}

function serializeRules(items) {
  return JSON.stringify(rulesForApi(items).map((rule) => ({
    scopeType: rule.scopeType,
    targetId: rule.targetId,
    targetName: rule.targetName,
  })).sort((left, right) => (
    `${left.scopeType}:${left.targetId}`.localeCompare(`${right.scopeType}:${right.targetId}`)
  )));
}

function sourceDisplayName(rule) {
  return targetNameForRule(rule);
}

function toggleDepartmentExpanded(row) {
  if (!row?.hasChildren) return;
  const next = new Set(expandedDepartmentIds.value);
  if (next.has(row.id)) next.delete(row.id);
  else next.add(row.id);
  expandedDepartmentIds.value = next;
}

function departmentSourceChecked(id) {
  return departmentSourceMap.value.has(id) || forcedDepartmentIds.value.has(id);
}

function makeDepartmentSource(row, includeSubDepartments = false) {
  return {
    permission: PERMISSION.id,
    scopeType: SCOPE_DEPARTMENT,
    targetId: row.id,
    targetName: row.name,
    sortOrder: departmentSources.value.length,
    includeSubDepartments,
  };
}

function removeDescendantDepartmentSources(row, items) {
  const childIds = new Set(departmentById(row.id)?.childIds || []);
  return items.filter((rule) => (
    rule.scopeType !== SCOPE_DEPARTMENT || !childIds.has(rule.targetId)
  ));
}

function toggleDepartmentSource(row) {
  if (!row?.id || forcedDepartmentIds.value.has(row.id)) return;
  const existing = departmentSourceMap.value.get(row.id);
  const next = existing
    ? rules.value.filter((rule) => ruleKey(rule) !== ruleKey(existing))
    : [...rules.value, makeDepartmentSource(row)];
  rules.value = normalizeRules(next);
  saveSucceeded.value = false;
}

function setDepartmentIncludeSubDepartments(row, checked) {
  if (!row?.id || forcedDepartmentIds.value.has(row.id)) return;
  const existing = departmentSourceMap.value.get(row.id);
  let next = rules.value;
  if (existing) {
    next = next.map((rule) => (
      ruleKey(rule) === ruleKey(existing) ? { ...rule, includeSubDepartments: checked } : rule
    ));
  } else if (checked) {
    next = [...next, makeDepartmentSource(row, true)];
  } else {
    return;
  }
  if (checked) {
    next = removeDescendantDepartmentSources(row, next);
    expandedDepartmentIds.value = new Set([...expandedDepartmentIds.value, row.id]);
  }
  rules.value = normalizeRules(next);
  saveSucceeded.value = false;
}

function toggleEmployeeSource(row) {
  if (!row?.id) return;
  const existing = employeeSourceMap.value.get(row.id);
  if (existing) {
    rules.value = normalizeRules(rules.value.filter((rule) => !(
      rule.scopeType === SCOPE_EMPLOYEE && rule.targetId === row.id
    )));
    saveSucceeded.value = false;
    return;
  }
  const withoutExclusion = rules.value.filter((rule) => !(
    rule.scopeType === SCOPE_EXCLUDED_EMPLOYEE && rule.targetId === row.id
  ));
  rules.value = normalizeRules([
    ...withoutExclusion,
    {
      permission: PERMISSION.id,
      scopeType: SCOPE_EMPLOYEE,
      targetId: row.id,
      targetName: row.name,
      sortOrder: employeeSources.value.length,
      includeSubDepartments: false,
    },
  ]);
  saveSucceeded.value = false;
}

function removeRule(ruleToRemove) {
  rules.value = normalizeRules(rules.value.filter((rule) => ruleKey(rule) !== ruleKey(ruleToRemove)));
  saveSucceeded.value = false;
}

function excludeMember(row) {
  const withoutDirectAndExistingExclusion = rules.value.filter((rule) => (
    !(rule.scopeType === SCOPE_EMPLOYEE && rule.targetId === row.userId)
    && !(rule.scopeType === SCOPE_EXCLUDED_EMPLOYEE && rule.targetId === row.userId)
  ));
  const next = row.includedByDepartment ? [
    ...withoutDirectAndExistingExclusion,
    {
      permission: PERMISSION.id,
      scopeType: SCOPE_EXCLUDED_EMPLOYEE,
      targetId: row.userId,
      targetName: row.name,
      sortOrder: 0,
      includeSubDepartments: false,
    },
  ] : withoutDirectAndExistingExclusion;
  rules.value = normalizeRules(next);
  saveSucceeded.value = false;
}

function restoreExcludedMember(row) {
  rules.value = normalizeRules(rules.value.filter((rule) => !(
    rule.scopeType === SCOPE_EXCLUDED_EMPLOYEE && rule.targetId === row.userId
  )));
  saveSucceeded.value = false;
}

function expandDepartmentPickerDefaults() {
  const next = new Set(departmentTree.value.map((department) => department.id));
  departmentSources.value.forEach((source) => {
    let current = departmentById(source.targetId);
    while (current?.parentId) {
      next.add(current.parentId);
      current = departmentById(current.parentId);
    }
    if (source.includeSubDepartments) next.add(source.targetId);
  });
  expandedDepartmentIds.value = next;
}

function openSourcePicker(scopeType) {
  if (saving.value || !loaded.value) return;
  sourcePickerReturnFocus = document.activeElement;
  sourcePicker.open = true;
  sourcePicker.scopeType = scopeType;
  sourcePicker.keyword = "";
  if (scopeType === SCOPE_DEPARTMENT) expandDepartmentPickerDefaults();
}

function closeSourcePicker() {
  if (!sourcePicker.open) return;
  sourcePicker.open = false;
}

function focusablePickerElements() {
  return [...(sourcePickerPanel.value?.querySelectorAll(
    'button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
  ) || [])].filter((element) => !element.hidden && element.getClientRects().length > 0);
}

function handlePickerKeydown(event) {
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    closeSourcePicker();
    return;
  }
  if (event.key !== "Tab") return;
  const focusable = focusablePickerElements();
  if (!focusable.length) {
    event.preventDefault();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const active = document.activeElement;
  if (event.shiftKey && (active === first || !sourcePickerPanel.value?.contains(active))) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && active === last) {
    event.preventDefault();
    first.focus();
  }
}

async function loadData() {
  loading.value = true;
  loaded.value = false;
  errorMessage.value = "";
  saveSucceeded.value = false;
  try {
    const [permissionData, treeData, employeeData, enabledData] = await Promise.all([
      apiGet(props.apiPath),
      apiGet("/api/org/departments/tree"),
      apiGet("/api/org/employees", { status: "active", includeDepartments: "true" }),
      apiGet("/api/org/enabled-departments"),
    ]);
    const enabledIds = new Set((enabledData?.departmentIds || []).map(normalizeId));
    const normalizedTree = normalizeDepartmentNodes(treeData?.items || []);
    const tree = decorateDepartmentTree(cropEnabledDepartmentTree(normalizedTree, enabledIds));
    departmentTree.value = tree;
    departments.value = flattenDepartments(tree, []);
    employees.value = (Array.isArray(employeeData?.items) ? employeeData.items : [])
      .map((item) => normalizeEmployee(item, enabledIds))
      .filter((employee) => employee.id && employee.departments.length);
    expandedDepartmentIds.value = new Set(tree.map((department) => department.id));
    revision.value = normalizeId(permissionData?.revision);
    orgRevision.value = normalizeId(permissionData?.orgRevision);
    rules.value = normalizeRules(permissionData?.rules || []);
    snapshot.value = serializeRules(rules.value);
    conflict.value = false;
    loaded.value = true;
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : `${props.permissionLabel}加载失败`;
  } finally {
    loading.value = false;
  }
}

function refreshData() {
  if (permissionDirty.value) {
    refreshConfirmOpen.value = true;
    return;
  }
  void loadData();
}

function cancelRefresh() {
  refreshConfirmOpen.value = false;
}

function discardAndRefresh() {
  refreshConfirmOpen.value = false;
  void loadData();
}

async function saveRules() {
  if (!permissionDirty.value || saving.value || conflict.value || !loaded.value) return;
  saving.value = true;
  errorMessage.value = "";
  saveSucceeded.value = false;
  try {
    const data = await apiPut(props.apiPath, {
      rules: rulesForApi(rules.value),
      revision: revision.value,
      orgRevision: orgRevision.value,
    });
    revision.value = normalizeId(data?.revision) || revision.value;
    orgRevision.value = normalizeId(data?.orgRevision) || orgRevision.value;
    rules.value = normalizeRules(Array.isArray(data?.rules) ? data.rules : rulesForApi(rules.value));
    snapshot.value = serializeRules(rules.value);
    saveSucceeded.value = true;
    showFeedback(`${props.permissionLabel}已保存`);
  } catch (error) {
    conflict.value = Number(error?.status) === 409;
    errorMessage.value = conflict.value
      ? "权限或组织已更新。当前修改尚未提交，请重新加载后核对配置再保存。"
      : (error instanceof Error ? error.message : `${props.permissionLabel}保存失败`);
  } finally {
    saving.value = false;
  }
}

watch(permissionDirty, (dirty) => emit("dirty-change", dirty), { immediate: true });
watch(saving, (busy) => emit("saving-change", busy), { immediate: true });
watch(() => sourcePicker.open, async (open) => {
  if (open) {
    await nextTick();
    sourcePickerInput.value?.focus?.();
    return;
  }
  await nextTick();
  if (sourcePickerReturnFocus?.isConnected) sourcePickerReturnFocus.focus?.();
  sourcePickerReturnFocus = null;
});

onMounted(loadData);
onBeforeUnmount(() => {
  emit("dirty-change", false);
  emit("saving-change", false);
});

defineExpose({
  hasPendingChanges: () => permissionDirty.value,
  isSaveInProgress: () => saving.value,
  refresh: refreshData,
  focusRoleSelection: () => rolePicker.value?.querySelector('button[aria-pressed="true"]')?.focus(),
});
</script>

<template>
  <div class="permission-workbench h-full min-h-0 w-full">
    <div
      class="flex h-full min-h-0 w-full flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm"
      :inert="sourcePicker.open || refreshConfirmOpen || saving ? true : undefined"
      :aria-busy="saving"
    >
      <header class="flex shrink-0 items-center justify-between gap-3 border-b border-slate-100 bg-white px-5 py-3">
        <div class="min-w-0">
          <h2 class="truncate text-base font-bold text-slate-900">{{ permissionLabel }}</h2>
          <p class="mt-1 text-xs text-slate-500" role="status">{{ statusText }}</p>
        </div>
        <button
          type="button"
          class="inline-flex h-8 min-w-[82px] items-center justify-center gap-1.5 rounded-md bg-blue-600 px-3 text-xs font-semibold text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-300"
          :disabled="loading || saving || !permissionDirty || conflict"
          :aria-busy="saving"
          data-ai-action="auth.platform-permissions.save"
          @click="saveRules"
        >
          <LoaderCircle v-if="saving" class="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          {{ saveButtonText }}
        </button>
      </header>

      <div
        v-if="errorMessage"
        class="shrink-0 border-b border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700"
        role="alert"
      >
        {{ errorMessage }}
        <button type="button" class="ml-3 rounded-md border border-rose-300 bg-white px-3 py-1 text-sm" :disabled="saving" @click="refreshData">重新加载</button>
      </div>

      <div
        v-if="loading && !roleOptions.length"
        class="flex min-h-0 flex-1 items-center justify-center gap-2 bg-slate-50 p-6 text-sm text-slate-500"
        role="status"
      >
        <LoaderCircle class="h-4 w-4 animate-spin text-blue-600" aria-hidden="true" />
        正在加载权限...
      </div>

      <div v-if="roleOptions.length || (!loading && loaded)" class="permission-body min-h-0 flex-1 overflow-auto bg-slate-50">
        <div class="permission-grid">
          <aside class="flex min-h-0 flex-col border-r border-slate-200 bg-white">
            <header class="shrink-0 border-b border-slate-100 px-4 py-3">
              <h3 class="text-sm font-bold text-slate-900">权限选择</h3>
            </header>
            <div class="min-h-0 flex-1 overflow-auto p-3">
              <div v-if="roleOptions.length" ref="rolePicker" class="flex flex-col gap-2" role="group" aria-label="权限角色">
                <button
                  v-for="option in roleOptions"
                  :key="option.id"
                  type="button"
                  class="w-full rounded-md border px-3 py-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60"
                  :class="option.id === activeRoleId ? 'border-blue-300 bg-blue-50 text-blue-700 shadow-sm' : 'border-slate-200 bg-white text-slate-700 hover:border-blue-200 hover:bg-slate-50'"
                  :aria-label="option.label"
                  :aria-pressed="option.id === activeRoleId"
                  :disabled="saving"
                  @click="emit('role-select', option.id)"
                >
                  <span class="flex items-center justify-between gap-2">
                    <span class="flex min-w-0 items-center gap-2">
                      <ShieldCheck class="h-4 w-4 shrink-0" aria-hidden="true" />
                      <span class="truncate text-sm font-bold">{{ option.label }}</span>
                    </span>
                    <span v-if="option.id === activeRoleId && loaded" class="shrink-0 rounded bg-white px-1.5 py-0.5 text-xs font-bold text-slate-500">{{ memberRows.length }} 人</span>
                  </span>
                  <span class="mt-2 block text-xs font-medium leading-5 text-slate-500">{{ option.note }}</span>
                  <span v-if="option.id === activeRoleId && loaded" class="mt-1 block text-xs font-medium text-slate-400">配置来源 {{ sourceTotal }}</span>
                </button>
              </div>
              <div v-else class="w-full rounded-md border border-blue-300 bg-blue-50 px-3 py-3 text-left text-blue-700 shadow-sm">
                <div class="flex items-center justify-between gap-2">
                  <div class="flex min-w-0 items-center gap-2">
                    <ShieldCheck class="h-4 w-4 shrink-0" aria-hidden="true" />
                    <span class="truncate text-sm font-bold">{{ PERMISSION.label }}</span>
                  </div>
                  <span class="shrink-0 rounded bg-white px-1.5 py-0.5 text-xs font-bold text-slate-500">{{ memberRows.length }} 人</span>
                </div>
                <div class="mt-2 text-xs font-medium leading-5 text-slate-500">{{ PERMISSION.note }}</div>
                <div class="mt-1 text-xs font-medium text-slate-400">配置来源 {{ sourceTotal }}</div>
              </div>
            </div>
          </aside>

          <div v-if="loading && roleOptions.length" class="permission-role-state flex items-center justify-center gap-2 p-6 text-sm text-slate-500" role="status">
            <LoaderCircle class="h-4 w-4 animate-spin text-blue-600" aria-hidden="true" />正在加载权限...
          </div>
          <template v-if="loaded && !loading">
          <section class="flex min-h-0 flex-col border-r border-slate-200 bg-white" aria-labelledby="permission-source-heading">
            <header class="shrink-0 border-b border-slate-100 px-4 py-3">
              <h3 id="permission-source-heading" class="text-sm font-bold text-slate-900">人员配置</h3>
              <div class="mt-0.5 truncate text-xs font-medium text-slate-400">{{ PERMISSION.label }}</div>
            </header>
            <div class="min-h-0 flex-1 overflow-auto bg-white">
              <section v-for="group in sourceGroups" :key="group.id" class="border-b border-slate-100">
                <header class="flex items-center justify-between gap-3 bg-slate-50 px-3 py-2.5">
                  <div class="flex min-w-0 items-center gap-2 text-sm font-bold text-slate-800">
                    <component :is="group.icon" class="h-4 w-4 shrink-0 text-slate-500" aria-hidden="true" />
                    <span>{{ group.label }}</span>
                  </div>
                  <button
                    type="button"
                    class="inline-flex h-7 items-center gap-1 rounded-md bg-blue-600 px-2.5 text-xs font-semibold text-white transition-colors hover:bg-blue-700"
                    :aria-label="`添加${group.label}${memberLabel}`"
                    @click.stop="openSourcePicker(group.id)"
                  >
                    <Plus class="h-3.5 w-3.5" aria-hidden="true" />添加
                  </button>
                </header>
                <div class="min-h-[74px] px-3 py-3">
                  <div v-if="group.rows.length" class="flex flex-wrap gap-2">
                    <span
                      v-for="source in group.rows"
                      :key="ruleKey(source)"
                      class="inline-flex min-h-8 max-w-full items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-700"
                    >
                      <span class="min-w-0 truncate">{{ sourceDisplayName(source) }}</span>
                      <span
                        v-if="source.scopeType === SCOPE_DEPARTMENT && source.includeSubDepartments"
                        class="shrink-0 rounded-sm border border-amber-300 bg-amber-100 px-1.5 py-0.5 text-xs font-semibold leading-none text-amber-700"
                      >含下级</span>
                      <button
                        type="button"
                        class="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-sm text-slate-400 hover:bg-rose-50 hover:text-rose-600"
                        :aria-label="`移除${sourceDisplayName(source)}`"
                        @click="removeRule(source)"
                      >
                        <X class="h-3 w-3" aria-hidden="true" />
                      </button>
                    </span>
                  </div>
                  <div v-else class="py-2 text-sm font-medium text-slate-400">{{ group.empty }}</div>
                </div>
              </section>

              <section v-if="excludedRows.length" class="border-b border-slate-100">
                <header class="flex items-center justify-between bg-slate-50 px-3 py-2.5">
                  <div class="text-sm font-bold text-slate-800">已排除人员</div>
                  <div class="text-xs font-semibold text-slate-400">{{ excludedRows.length }} 人</div>
                </header>
                <div class="flex flex-wrap gap-2 px-3 py-3">
                  <span
                    v-for="row in excludedRows"
                    :key="`excluded:${row.userId}`"
                    class="inline-flex min-h-8 max-w-full items-center gap-2 rounded-md border border-slate-200 bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-400 line-through"
                  >
                    <span class="min-w-0 truncate">{{ row.name }}</span>
                    <button
                      type="button"
                      class="inline-flex h-6 shrink-0 items-center justify-center rounded px-1.5 text-blue-600 no-underline hover:bg-blue-50"
                      :aria-label="`恢复${row.name}`"
                      @click="restoreExcludedMember(row)"
                    >恢复</button>
                  </span>
                </div>
              </section>
            </div>
          </section>

          <section class="flex min-h-0 min-w-0 flex-col overflow-hidden bg-white" aria-labelledby="permission-members-heading">
            <header class="flex shrink-0 items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
              <div class="flex min-w-0 items-center gap-2">
                <UserRound class="h-4 w-4 shrink-0 text-blue-600" aria-hidden="true" />
                <div class="min-w-0">
                  <h3 id="permission-members-heading" class="truncate text-sm font-bold text-slate-900">具体人员</h3>
                  <div class="mt-0.5 truncate text-xs font-medium text-slate-400">{{ PERMISSION.label }}</div>
                </div>
              </div>
              <div class="shrink-0 rounded-md bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-500">{{ memberRows.length }} 人</div>
            </header>
            <div class="permission-members min-h-0 flex-1 overflow-auto bg-white" tabindex="0" role="region" aria-label="具体人员列表，可横向滚动">
              <table class="w-full min-w-[460px] table-fixed border-collapse text-sm">
                <caption class="sr-only">{{ permissionLabel }}具体人员</caption>
                <colgroup>
                  <col class="w-[145px]" />
                  <col />
                  <col class="w-[132px]" />
                  <col class="w-[90px]" />
                </colgroup>
                <thead class="sticky top-0 z-10 bg-slate-50">
                  <tr class="text-xs text-slate-500">
                    <th scope="col" class="border-b border-slate-200 px-4 py-2 text-left font-semibold">姓名</th>
                    <th scope="col" class="border-b border-slate-200 px-3 py-2 text-left font-semibold">所在部门</th>
                    <th scope="col" class="border-b border-slate-200 px-3 py-2 text-left font-semibold">权限来源</th>
                    <th scope="col" class="border-b border-slate-200 px-3 py-2 text-center font-semibold">操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="(row, rowIndex) in memberRows"
                    :key="`member:${row.userId}`"
                    class="transition-colors hover:bg-blue-50/50"
                    :class="rowIndex % 2 === 1 ? 'bg-slate-50/45' : 'bg-white'"
                  >
                    <td class="border-b border-slate-100 px-4 py-2">
                      <div class="flex min-w-0 items-center gap-3">
                        <div class="flex h-7 w-7 shrink-0 items-center justify-center overflow-hidden rounded-md bg-blue-50 text-xs font-bold text-blue-700">
                          <img
                            v-if="row.employee.avatarUrl"
                            :src="row.employee.avatarUrl"
                            :alt="row.name"
                            class="h-full w-full object-cover"
                            referrerpolicy="no-referrer"
                          />
                          <span v-else>{{ employeeInitial(row.employee) }}</span>
                        </div>
                        <div class="min-w-0">
                          <div class="truncate text-sm font-semibold leading-5 text-slate-900">{{ row.name }}</div>
                          <div class="truncate text-xs font-medium text-slate-400">{{ row.userId }}</div>
                        </div>
                      </div>
                    </td>
                    <td class="border-b border-slate-100 px-3 py-2">
                      <div class="truncate text-xs font-medium text-slate-600" :title="row.departmentText">{{ row.departmentText }}</div>
                    </td>
                    <td class="border-b border-slate-100 px-3 py-2">
                      <div class="truncate text-xs font-medium text-slate-500" :title="row.sourceText">{{ row.sourceText || "-" }}</div>
                    </td>
                    <td class="border-b border-slate-100 px-3 py-2 text-center">
                      <button
                        type="button"
                        class="inline-flex h-7 items-center gap-1 rounded-md px-2 text-xs font-medium text-slate-500 hover:bg-rose-50 hover:text-rose-600"
                        :aria-label="`排除${row.name}`"
                        @click="excludeMember(row)"
                      >
                        <UserMinus class="h-3.5 w-3.5" aria-hidden="true" />排除
                      </button>
                    </td>
                  </tr>
                  <tr v-if="!memberRows.length">
                    <td colspan="4" class="px-3 py-12 text-center text-sm font-medium text-slate-400">暂无人员</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>
          </template>
        </div>
      </div>
    </div>

    <Teleport to="body">
      <div
        v-if="sourcePicker.open"
        class="fixed inset-0 flex items-center justify-center bg-slate-950/40 p-4"
        :style="{ zIndex: 'var(--mj-layer-dialog, 170)' }"
        v-backdrop-dismiss="closeSourcePicker"
      >
        <div
          ref="sourcePickerPanel"
          class="permission-picker flex max-h-[calc(100dvh-32px)] max-w-[calc(100vw-32px)] flex-col overflow-hidden rounded-lg bg-white shadow-xl"
          :class="sourcePicker.scopeType === SCOPE_DEPARTMENT ? 'h-[640px] w-[760px]' : 'h-[560px] w-[560px]'"
          role="dialog"
          aria-modal="true"
          :aria-label="`添加${sourcePicker.scopeType === SCOPE_DEPARTMENT ? '部门' : '人员'}`"
          @click.stop
          @keydown="handlePickerKeydown"
        >
          <div class="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-4">
            <h2 class="text-base font-semibold text-slate-900">添加{{ sourcePicker.scopeType === SCOPE_DEPARTMENT ? "部门" : "人员" }}</h2>
            <button
              type="button"
              class="inline-flex h-8 w-8 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-700"
              aria-label="关闭"
              @click="closeSourcePicker"
            >
              <X class="h-5 w-5" aria-hidden="true" />
            </button>
          </div>

          <div class="border-b border-slate-100 px-4 py-3">
            <label class="flex h-10 items-center gap-2 rounded-md border border-slate-200 bg-white px-3 focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-100">
              <Search class="h-4 w-4 text-slate-400" aria-hidden="true" />
              <span class="sr-only">{{ sourcePicker.scopeType === SCOPE_DEPARTMENT ? "搜索部门" : "搜索人员" }}</span>
              <input
                ref="sourcePickerInput"
                v-model.trim="sourcePicker.keyword"
                type="search"
                class="min-w-0 flex-1 border-0 bg-transparent text-sm text-slate-900 outline-none placeholder:text-slate-400"
                :placeholder="sourcePicker.scopeType === SCOPE_DEPARTMENT ? '部门名称、ID或拼音' : '姓名、ID或拼音'"
              />
            </label>
          </div>

          <div v-if="sourcePicker.scopeType === SCOPE_DEPARTMENT" class="min-h-0 flex-1 overflow-auto p-3">
            <div class="permission-department-list flex min-h-full min-w-0 flex-col overflow-hidden rounded-md border border-slate-200">
              <div class="grid shrink-0 grid-cols-[minmax(0,1fr)_132px_72px] border-b border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-500">
                <div>部门</div>
                <div class="text-center">包含子部门</div>
                <div class="text-right">人数</div>
              </div>
              <div class="min-h-0 flex-1 overflow-y-auto">
                <div
                  v-for="row in sourceDepartmentRows"
                  :key="row.id"
                  class="grid min-h-10 grid-cols-[minmax(0,1fr)_132px_72px] items-center gap-2 border-b border-slate-100 px-3 py-2 last:border-b-0 hover:bg-blue-50/50"
                  :class="forcedDepartmentIds.has(row.id) ? 'bg-slate-50 text-slate-400' : 'text-slate-700'"
                >
                  <div class="flex min-w-0 items-center gap-2" :style="{ paddingLeft: `${row.depth * 18}px` }">
                    <input
                      type="checkbox"
                      class="h-4 w-4 shrink-0 rounded border-slate-300 text-blue-600 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-60"
                      :aria-label="`${row.name}部门`"
                      :checked="departmentSourceChecked(row.id)"
                      :disabled="forcedDepartmentIds.has(row.id)"
                      @change="toggleDepartmentSource(row)"
                    />
                    <button
                      v-if="row.hasChildren"
                      type="button"
                      class="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded text-slate-500 hover:bg-slate-100"
                      :aria-label="`${row.expanded ? '收起' : '展开'}${row.name}`"
                      :aria-expanded="row.expanded"
                      @click="toggleDepartmentExpanded(row)"
                    >
                      <ChevronDown class="h-4 w-4 transition-transform" :class="row.expanded ? '' : '-rotate-90'" aria-hidden="true" />
                    </button>
                    <span v-else class="h-6 w-6 shrink-0" aria-hidden="true" />
                    <span class="min-w-0 truncate text-sm font-medium">{{ row.name }}</span>
                  </div>
                  <label class="flex items-center justify-center gap-1.5 text-xs text-slate-500">
                    <input
                      type="checkbox"
                      class="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-60"
                      :aria-label="`${row.name}包含子部门`"
                      :checked="departmentSourceMap.get(row.id)?.includeSubDepartments || false"
                      :disabled="forcedDepartmentIds.has(row.id)"
                      @change="setDepartmentIncludeSubDepartments(row, $event.target.checked)"
                    />
                    <span>包含</span>
                  </label>
                  <div class="text-right text-xs text-slate-400">{{ row.memberCount }}</div>
                </div>
                <div v-if="!sourceDepartmentRows.length" class="px-3 py-8 text-center text-sm text-slate-400">无匹配数据</div>
              </div>
            </div>
          </div>

          <div v-else class="min-h-0 flex-1 overflow-auto p-3">
            <div class="permission-employee-list flex min-h-full min-w-0 flex-col overflow-hidden rounded-md border border-slate-200">
              <div class="grid shrink-0 grid-cols-[minmax(0,1fr)_200px] border-b border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-500">
                <div>人员</div>
                <div class="text-right">部门</div>
              </div>
              <div class="min-h-0 flex-1 overflow-y-auto">
                <label
                  v-for="row in sourceEmployeeRows"
                  :key="row.id"
                  class="grid min-h-12 cursor-pointer grid-cols-[minmax(0,1fr)_200px] items-center gap-3 border-b border-slate-100 px-3 py-2.5 last:border-b-0 hover:bg-blue-50/50"
                  :class="row.selected ? 'bg-blue-50 text-blue-700' : 'text-slate-700'"
                >
                  <span class="flex min-w-0 items-center gap-3">
                    <input
                      type="checkbox"
                      class="h-4 w-4 shrink-0 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                      :aria-label="`${row.name}${memberLabel}`"
                      :checked="row.selected"
                      @change="toggleEmployeeSource(row)"
                    />
                    <span class="min-w-0 truncate text-sm font-semibold">{{ row.name }}</span>
                  </span>
                  <span class="truncate text-right text-xs text-slate-400" :title="row.meta">{{ row.meta }}</span>
                </label>
                <div v-if="!sourceEmployeeRows.length" class="px-3 py-8 text-center text-sm text-slate-400">无匹配数据</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <SettingsUnsavedChangesDialog
      :open="refreshConfirmOpen"
      message="当前权限配置尚未保存，重新加载后本次修改不会保留。"
      @cancel="cancelRefresh"
      @confirm="discardAndRefresh"
    />
  </div>
</template>

<style scoped>
.permission-workbench {
  container-type: inline-size;
}

.permission-grid {
  display: grid;
  height: 100%;
  grid-template-columns: 224px minmax(260px, 0.8fr) minmax(460px, 1.2fr);
}

.permission-grid > * {
  min-width: 0;
}

.permission-role-state {
  grid-column: span 2;
}

@container (max-width: 959px) {
  .permission-grid {
    height: auto;
    grid-template-columns: minmax(0, 1fr);
  }

  .permission-grid > * {
    border-right: 0;
    border-bottom: 1px solid #e2e8f0;
  }

  .permission-role-state {
    grid-column: auto;
  }

  .permission-members {
    max-height: 440px;
    flex: auto;
  }
}
</style>
