<script setup>
import { backdropDismiss as vBackdropDismiss } from "@platform-ui/backdrop-dismiss.js";
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
  UsersRound,
  X,
} from "@lucide/vue";

import { apiGet, apiPost } from "@/api";
import UnsavedChangesDialog from "@/components/UnsavedChangesDialog.vue";

const emit = defineEmits(["dirty-change", "confirm-open-change", "saved"]);

const PERMISSIONS = [
  { id: "admin", label: "系统管理员", note: "拥有迈杰服务全部权限，包括设置和权限分配。" },
  { id: "service", label: "服务管理员", note: "包含业务员全部权限，可审核和管理服务团队、管理服务奖励。" },
  { id: "sales", label: "业务员", note: "使用总览、售前、售中、售后服务、工单与反馈和结算中心，服务团队仅可查看。" },
];
const selectedPermissionId = ref("admin");
const PERMISSION = computed(() => PERMISSIONS.find(item => item.id === selectedPermissionId.value));
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
const errorMessage = ref("");
const saveSucceeded = ref(false);
const versionConflict = ref(false);
const reloadConfirmOpen = ref(false);
const departmentTree = ref([]);
const departments = ref([]);
const employees = ref([]);
const rules = ref([]);
const revision = ref("");
const orgRevision = ref("");
const snapshot = ref("");
const expandedDepartmentIds = ref(new Set());
const sourcePickerInput = ref(null);

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
  !loading.value && snapshot.value !== serializeRules(rules.value)
));
const saveButtonText = computed(() => (
  saveSucceeded.value && !permissionDirty.value ? "已保存" : "保存"
));
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

function collectDepartmentIds(nodes = []) {
  const ids = [];
  nodes.forEach((node) => {
    if (node.id) ids.push(node.id);
    ids.push(...collectDepartmentIds(node.children || []));
  });
  return ids;
}

function normalizeDepartmentTree(nodes = [], depth = 0) {
  return (Array.isArray(nodes) ? nodes : [])
    .map((item) => {
      const id = normalizeId(item?.deptId ?? item?.dept_id ?? item?.id);
      if (!id) return null;
      const children = normalizeDepartmentTree(item?.children || [], depth + 1);
      return {
        id,
        name: normalizeId(item?.name) || id,
        parentId: normalizeId(item?.parentDeptId ?? item?.parent_dept_id ?? item?.parentId),
        pinyinInitials: normalizeId(item?.pinyinInitials ?? item?.pinyin_initials).toLowerCase(),
        departmentPathText: normalizeId(item?.departmentPathText ?? item?.department_path_text),
        sortOrder: normalizeSortOrder(item?.sortOrder ?? item?.sort_order),
        depth,
        childIds: collectDepartmentIds(children),
        children,
      };
    })
    .filter(Boolean)
    .sort((left, right) => (
      left.sortOrder - right.sortOrder
      || left.name.localeCompare(right.name, "zh-Hans-CN")
    ));
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
    return id ? { id, name: departmentById(id)?.name || id, pinyinInitials: "", departmentPathText: "" } : null;
  }
  const id = normalizeId(item?.deptId ?? item?.dept_id ?? item?.id);
  const name = normalizeId(item?.name) || departmentById(id)?.name || id;
  return id || name ? {
    id,
    name,
    pinyinInitials: normalizeId(item?.pinyinInitials ?? item?.pinyin_initials).toLowerCase(),
    departmentPathText: normalizeId(item?.departmentPathText ?? item?.department_path_text),
  } : null;
}

function normalizeEmployee(item) {
  const id = normalizeId(item?.userId ?? item?.user_id ?? item?.id);
  const rawDepartments = Array.isArray(item?.departments)
    ? item.departments
    : (Array.isArray(item?.departmentIds) ? item.departmentIds : []);
  return {
    id,
    name: normalizeId(item?.name ?? item?.rawName) || id,
    avatarUrl: normalizeId(item?.avatarUrl ?? item?.avatar_url),
    pinyinInitials: normalizeId(item?.pinyinInitials ?? item?.pinyin_initials).toLowerCase(),
    departments: rawDepartments.map(normalizeEmployeeDepartment).filter(Boolean),
  };
}

function normalizeRule(item, fallbackOrder = 0) {
  const permission = normalizeId(item?.permission);
  const rawScopeType = normalizeId(item?.scopeType ?? item?.scope_type);
  const includeSubDepartments = rawScopeType === SCOPE_DEPARTMENT_WITH_SUB
    || normalizeBoolean(item?.includeSubDepartments ?? item?.include_sub_departments);
  const scopeType = rawScopeType === SCOPE_DEPARTMENT_WITH_SUB
    ? SCOPE_DEPARTMENT
    : rawScopeType;
  return {
    permission,
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
  if (!keyword) return true;
  return [
    department?.name,
    department?.id,
    department?.pinyinInitials,
    department?.departmentPathText,
  ].filter(Boolean).join(" ").toLowerCase().includes(keyword);
}

function employeeMatches(employee, keyword) {
  if (!keyword) return true;
  const departmentKeywords = (employee?.departments || []).map((department) => [
    department.name,
    department.id,
    department.pinyinInitials,
    department.departmentPathText,
  ].filter(Boolean).join(" ")).join(" ");
  return [employee?.name, employee?.id, employee?.pinyinInitials, departmentKeywords]
    .filter(Boolean)
    .join(" ")
    .toLowerCase()
    .includes(keyword);
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

function normalizeRules(items = rules.value) {
  const normalized = [];
  const seen = new Set();
  (Array.isArray(items) ? items : []).forEach((item, index) => {
    const rule = normalizeRule(item, index);
    if (!PERMISSIONS.some(item => item.id === rule.permission) || !VALID_SCOPES.has(rule.scopeType) || !rule.targetId) return;
    const key = ruleKey(rule);
    if (seen.has(key)) return;
    seen.add(key);
    normalized.push({
      ...rule,
      targetName: targetNameForRule(rule),
      includeSubDepartments: rule.scopeType === SCOPE_DEPARTMENT && rule.includeSubDepartments,
    });
  });

  return normalized;
}

function rulesFor(scopeType, items = rules.value, permission = selectedPermissionId.value) {
  return items
    .filter((rule) => rule.permission === permission && rule.scopeType === scopeType)
    .sort((left, right) => (
      left.sortOrder - right.sortOrder
      || targetNameForRule(left).localeCompare(targetNameForRule(right), "zh-Hans-CN")
    ));
}

function departmentIdsForRules(items, permission = selectedPermissionId.value) {
  const ids = new Set();
  rulesFor(SCOPE_DEPARTMENT, items, permission).forEach((rule) => {
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

function baseMemberRows(items, permission = selectedPermissionId.value) {
  const departmentIds = departmentIdsForRules(items, permission);
  const directIds = new Set(rulesFor(SCOPE_EMPLOYEE, items, permission).map((rule) => rule.targetId));
  return employees.value.map((employee) => {
    const matchedDepartments = employee.departments.filter((department) => departmentIds.has(department.id));
    const includedByDepartment = matchedDepartments.length > 0;
    const includedByEmployee = directIds.has(employee.id);
    if (!includedByDepartment && !includedByEmployee) return null;
    return {
      userId: employee.id,
      name: employee.name,
      employee,
      departmentText: employeeDepartmentText(employee),
      sourceText: [
        ...(includedByEmployee ? ["人员"] : []),
        ...matchedDepartments.map((department) => department.name),
      ].join(" / "),
      includedByDepartment,
    };
  }).filter(Boolean).sort((left, right) => (
    left.name.localeCompare(right.name, "zh-Hans-CN") || left.userId.localeCompare(right.userId)
  ));
}

function excludedUserIds(items, permission = selectedPermissionId.value) {
  return new Set(rulesFor(SCOPE_EXCLUDED_EMPLOYEE, items, permission).map((rule) => rule.targetId));
}

function memberRowsForRules(items, permission = selectedPermissionId.value) {
  const excluded = excludedUserIds(items, permission);
  return baseMemberRows(items, permission).filter((row) => !excluded.has(row.userId));
}

function excludedRowsForRules(items) {
  const rows = new Map(baseMemberRows(items).map(row => [row.userId, row]));
  return rulesFor(SCOPE_EXCLUDED_EMPLOYEE, items).map(rule => rows.get(rule.targetId) || {
    userId: rule.targetId, name: targetNameForRule(rule),
    employee: employeeById(rule.targetId) || { name: rule.targetName, id: rule.targetId },
    departmentText: employeeDepartmentText(employeeById(rule.targetId)), sourceText: "已排除",
  });
}

function rulesForApi(items = rules.value) {
  return normalizeRules(items).map((rule) => {
    const scopeType = rule.scopeType === SCOPE_DEPARTMENT && rule.includeSubDepartments
      ? SCOPE_DEPARTMENT_WITH_SUB
      : rule.scopeType;
    return {
      permission: rule.permission,
      scopeType,
      targetId: rule.targetId,
      targetName: targetNameForRule(rule),
      sortOrder: rule.sortOrder,
      ...(scopeType === SCOPE_DEPARTMENT_WITH_SUB ? { includeSubDepartments: true } : {}),
    };
  });
}

function serializeRules(items) {
  return JSON.stringify(rulesForApi(items).map((rule) => ({
    permission: rule.permission,
    scopeType: rule.scopeType,
    targetId: rule.targetId,
    targetName: rule.targetName,
    sortOrder: rule.sortOrder,
  })).sort((left, right) => (
    `${left.permission}:${left.scopeType}:${left.targetId}`.localeCompare(
      `${right.permission}:${right.scopeType}:${right.targetId}`,
    )
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
    permission: selectedPermissionId.value,
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
    rule.permission !== selectedPermissionId.value || rule.scopeType !== SCOPE_DEPARTMENT || !childIds.has(rule.targetId)
  ));
}

function toggleDepartmentSource(row) {
  if (saving.value) return;
  if (!row?.id || forcedDepartmentIds.value.has(row.id)) return;
  const existing = departmentSourceMap.value.get(row.id);
  const next = existing
    ? rules.value.filter((rule) => ruleKey(rule) !== ruleKey(existing))
    : [...rules.value, makeDepartmentSource(row)];
  rules.value = normalizeRules(next);
}

function setDepartmentIncludeSubDepartments(row, checked) {
  if (saving.value) return;
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
}

function toggleEmployeeSource(row) {
  if (saving.value) return;
  if (!row?.id) return;
  const existing = employeeSourceMap.value.get(row.id);
  if (existing) {
    rules.value = normalizeRules(rules.value.filter((rule) => !(
      rule.permission === selectedPermissionId.value && rule.scopeType === SCOPE_EMPLOYEE && rule.targetId === row.id
    )));
    return;
  }
  const withoutExclusion = rules.value.filter((rule) => !(
    rule.permission === selectedPermissionId.value && rule.scopeType === SCOPE_EXCLUDED_EMPLOYEE && rule.targetId === row.id
  ));
  rules.value = normalizeRules([
    ...withoutExclusion,
    {
      permission: selectedPermissionId.value,
      scopeType: SCOPE_EMPLOYEE,
      targetId: row.id,
      targetName: row.name,
      sortOrder: employeeSources.value.length,
      includeSubDepartments: false,
    },
  ]);
}

function removeRule(ruleToRemove) {
  if (saving.value) return;
  rules.value = normalizeRules(rules.value.filter((rule) => ruleKey(rule) !== ruleKey(ruleToRemove)));
}

function excludeMember(row) {
  if (saving.value) return;
  const withoutDirectAndExistingExclusion = rules.value.filter((rule) => (
    rule.permission !== selectedPermissionId.value || (
      !(rule.scopeType === SCOPE_EMPLOYEE && rule.targetId === row.userId)
      && !(rule.scopeType === SCOPE_EXCLUDED_EMPLOYEE && rule.targetId === row.userId)
    )
  ));
  const next = row.includedByDepartment ? [
    ...withoutDirectAndExistingExclusion,
    {
      permission: selectedPermissionId.value,
      scopeType: SCOPE_EXCLUDED_EMPLOYEE,
      targetId: row.userId,
      targetName: row.name,
      sortOrder: 0,
      includeSubDepartments: false,
    },
  ] : withoutDirectAndExistingExclusion;
  rules.value = normalizeRules(next);
}

function restoreExcludedMember(row) {
  if (saving.value) return;
  rules.value = normalizeRules(rules.value.filter((rule) => !(
    rule.permission === selectedPermissionId.value && rule.scopeType === SCOPE_EXCLUDED_EMPLOYEE && rule.targetId === row.userId
  )));
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
  if (saving.value) return;
  sourcePicker.open = true;
  sourcePicker.scopeType = scopeType;
  sourcePicker.keyword = "";
  if (scopeType === SCOPE_DEPARTMENT) expandDepartmentPickerDefaults();
  nextTick(() => sourcePickerInput.value?.focus?.());
}

function closeSourcePicker() {
  sourcePicker.open = false;
}

function handleSourceKeydown(event) {
  if (event.key === "Escape") {
    closeSourcePicker();
    return;
  }
  if (event.key !== "Enter") return;
  const first = sourcePicker.scopeType === SCOPE_DEPARTMENT
    ? sourceDepartmentRows.value[0]
    : sourceEmployeeRows.value[0];
  if (!first) return;
  event.preventDefault();
  if (sourcePicker.scopeType === SCOPE_DEPARTMENT) toggleDepartmentSource(first);
  else toggleEmployeeSource(first);
}

function handleWindowKeydown(event) {
  if (event.key === "Escape" && sourcePicker.open) closeSourcePicker();
}

async function loadData() {
  loading.value = true;
  errorMessage.value = "";
  saveSucceeded.value = false;
  try {
    const [permissionData, directoryData] = await Promise.all([
      apiGet("/api/after-sales/permissions"),
      apiGet("/api/after-sales/permissions/directory"),
    ]);
    const tree = normalizeDepartmentTree(directoryData?.departments || []);
    departmentTree.value = tree;
    departments.value = flattenDepartments(tree, []);
    employees.value = (Array.isArray(directoryData?.employees) ? directoryData.employees : [])
      .map(normalizeEmployee)
      .filter((employee) => employee.id);
    expandedDepartmentIds.value = new Set(tree.map((department) => department.id));
    revision.value = normalizeId(permissionData?.revision);
    orgRevision.value = normalizeId(directoryData?.orgRevision);
    rules.value = normalizeRules(permissionData?.items || []);
    snapshot.value = serializeRules(rules.value);
    versionConflict.value = false;
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "权限加载失败";
  } finally {
    loading.value = false;
  }
}

async function saveRules() {
  if (!permissionDirty.value || saving.value || versionConflict.value) return;
  saving.value = true;
  errorMessage.value = "";
  saveSucceeded.value = false;
  try {
    const data = await apiPost("/api/after-sales/permissions", {
      items: rulesForApi(rules.value),
      revision: revision.value,
      orgRevision: orgRevision.value,
    });
    revision.value = normalizeId(data?.revision) || revision.value;
    orgRevision.value = normalizeId(data?.orgRevision) || orgRevision.value;
    rules.value = normalizeRules(
      Array.isArray(data?.items) ? data.items : rulesForApi(rules.value),
    );
    snapshot.value = serializeRules(rules.value);
    saveSucceeded.value = true;
    emit("saved", data);
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "权限保存失败";
    versionConflict.value = error?.status === 409;
  } finally {
    saving.value = false;
  }
}

watch(permissionDirty, (dirty) => emit("dirty-change", dirty), { immediate: true });
watch(reloadConfirmOpen, open => emit("confirm-open-change", open));

onMounted(() => {
  window.addEventListener("keydown", handleWindowKeydown);
  loadData();
});

onBeforeUnmount(() => {
  window.removeEventListener("keydown", handleWindowKeydown);
  emit("confirm-open-change", false);
  emit("dirty-change", false);
});

defineExpose({
  hasPendingChanges: () => permissionDirty.value,
  refresh: loadData,
});
</script>

<template>
  <div class="mx-auto flex min-h-full w-full max-w-7xl flex-col gap-4">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <h1 class="truncate text-xl font-semibold text-slate-950">权限分配</h1>
      <div class="flex shrink-0 items-center gap-2">
        <button
          type="button"
          class="inline-flex h-9 min-w-[82px] items-center justify-center gap-2 rounded-md bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-300"
          :disabled="loading || saving || !permissionDirty || versionConflict"
          @click="saveRules"
        >
          <LoaderCircle v-if="saving" class="h-4 w-4 animate-spin" />
          {{ saveButtonText }}
        </button>
      </div>
    </div>

    <div
      v-if="errorMessage"
      class="rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700"
      role="alert"
    >
      {{ errorMessage }}
      <button v-if="versionConflict" type="button" class="ml-3 underline" :disabled="saving" @click="reloadConfirmOpen = true">重新加载权限</button>
    </div>

    <div
      v-if="loading"
      class="flex min-h-[112px] items-center justify-center gap-2 rounded-md border border-slate-200 bg-white p-6 text-sm text-slate-500 shadow-sm"
      role="status"
    >
      <LoaderCircle class="h-4 w-4 animate-spin text-blue-600" />
      正在加载权限...
    </div>

    <div v-else class="permission-layout grid min-h-[620px] gap-4 lg:grid-cols-[300px_minmax(0,1fr)]" :inert="saving || undefined">
      <section aria-label="权限项" class="flex min-h-0 flex-col rounded-md border border-slate-200 bg-white shadow-sm">
        <div class="border-b border-slate-100 px-4 py-3">
          <div class="flex items-center gap-2">
            <ShieldCheck class="h-4 w-4 text-blue-600" />
            <h2 class="text-sm font-semibold text-slate-900">权限项</h2>
          </div>
        </div>
        <div class="min-h-0 flex-1 overflow-auto p-3">
          <div class="grid gap-2">
            <button v-for="permission in PERMISSIONS" :key="permission.id" type="button"
              class="flex w-full items-start gap-3 rounded-md border px-3 py-3 text-left"
              :class="selectedPermissionId === permission.id ? 'border-blue-200 bg-blue-50' : 'border-slate-200 bg-white hover:bg-slate-50'"
              :aria-pressed="selectedPermissionId === permission.id" :disabled="saving || sourcePicker.open"
              @click="selectedPermissionId = permission.id">
              <span class="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-blue-600 text-white">
                <UsersRound class="h-4 w-4" />
              </span>
              <span class="min-w-0 flex-1">
                <span class="block truncate text-sm font-semibold text-blue-900">{{ permission.label }}</span>
                <span class="mt-1 block text-xs leading-5 text-slate-500">{{ permission.note }}</span>
                <span class="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-400">
                  <span>{{ memberRowsForRules(rules, permission.id).length }} 人</span>
                  <span>{{ rules.filter(rule => rule.permission === permission.id && rule.scopeType !== SCOPE_EXCLUDED_EMPLOYEE).length }} 来源</span>
                </span>
              </span>
            </button>
          </div>
        </div>
      </section>

      <section class="flex min-h-0 flex-col overflow-hidden rounded-md border border-slate-200 bg-white shadow-sm">
        <div class="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-4 py-3">
          <div class="min-w-0">
            <div class="flex items-center gap-2">
              <UsersRound class="h-4 w-4 text-blue-600" />
              <h2 class="truncate text-sm font-semibold text-slate-900">{{ PERMISSION.label }}</h2>
            </div>
            <p class="mt-1 text-xs text-slate-500">
              {{ PERMISSION.note }} 同一人员可以叠加多项权限，排除规则只影响当前权限项。
            </p>
          </div>
          <div class="flex items-center gap-2 rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-500">
            <ShieldCheck class="h-3.5 w-3.5" />
            <span>{{ sourceTotal }} 个来源</span>
          </div>
        </div>

        <div class="grid gap-3 border-b border-slate-100 p-4 xl:grid-cols-2">
          <div
            v-for="group in sourceGroups"
            :key="group.id"
            class="overflow-hidden rounded-md border border-slate-200 bg-white"
          >
            <div class="flex items-center justify-between gap-3 border-b border-slate-100 bg-slate-50 px-3 py-2">
              <div class="flex min-w-0 items-center gap-2">
                <component :is="group.icon" class="h-4 w-4 shrink-0 text-slate-500" />
                <span class="text-sm font-semibold text-slate-800">{{ group.label }}</span>
              </div>
              <button
                type="button"
                class="inline-flex h-7 items-center gap-1 rounded-md bg-blue-600 px-2.5 text-xs font-medium text-white hover:bg-blue-700"
                @click.stop="openSourcePicker(group.id)"
              >
                <Plus class="h-3.5 w-3.5" />
                添加
              </button>
            </div>
            <div class="min-h-[64px] p-3">
              <div v-if="group.rows.length" class="flex flex-wrap gap-2">
                <span
                  v-for="source in group.rows"
                  :key="ruleKey(source)"
                  class="inline-flex h-8 max-w-full items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-2.5 text-xs font-medium text-slate-700"
                >
                  <span class="min-w-0 truncate">{{ sourceDisplayName(source) }}</span>
                  <span
                    v-if="source.scopeType === SCOPE_DEPARTMENT && source.includeSubDepartments"
                    class="shrink-0 rounded-sm border border-amber-300 bg-amber-100 px-1.5 py-0.5 text-[11px] font-semibold leading-none text-amber-700"
                  >
                    含下级
                  </span>
                  <button
                    type="button"
                    class="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-sm text-slate-400 hover:bg-rose-50 hover:text-rose-600"
                    :aria-label="`移除${sourceDisplayName(source)}`"
                    @click="removeRule(source)"
                  >
                    <X class="h-3 w-3" />
                  </button>
                </span>
              </div>
              <div v-else class="flex h-10 items-center text-sm text-slate-400">{{ group.empty }}</div>
            </div>
          </div>
        </div>

        <div class="min-h-0 flex-1 overflow-auto">
          <table v-if="memberRows.length || excludedRows.length" class="as-template-table w-full min-w-[720px] table-fixed border-collapse text-sm">
            <colgroup>
              <col style="width: 24%" />
              <col style="width: 30%" />
              <col style="width: 26%" />
              <col style="width: 10%" />
              <col style="width: 10%" />
            </colgroup>
            <thead class="sticky top-0 z-20 bg-slate-50">
              <tr class="text-left text-xs text-slate-500">
                <th class="border-b border-slate-200 px-4 py-2 font-semibold">姓名</th>
                <th class="border-b border-slate-200 px-4 py-2 font-semibold">所在部门</th>
                <th class="border-b border-slate-200 px-4 py-2 font-semibold">权限来源</th>
                <th class="border-b border-slate-200 px-4 py-2 text-center font-semibold">状态</th>
                <th class="border-b border-slate-200 px-4 py-2 text-center font-semibold">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in memberRows" :key="`member:${row.userId}`" class="hover:bg-slate-50">
                <td class="border-b border-slate-100 px-4 py-3">
                  <div class="flex min-w-0 items-center gap-3">
                    <div class="flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-md bg-blue-50 text-xs font-semibold text-blue-700">
                      <img
                        v-if="row.employee.avatarUrl"
                        :src="row.employee.avatarUrl"
                        :alt="row.name"
                        class="h-full w-full object-cover"
                        referrerpolicy="no-referrer"
                      />
                      <span v-else>{{ employeeInitial(row.employee) }}</span>
                    </div>
                    <span class="min-w-0 truncate font-medium text-slate-900">{{ row.name }}</span>
                  </div>
                </td>
                <td class="border-b border-slate-100 px-4 py-3 text-slate-500">
                  <div class="truncate" :title="row.departmentText">{{ row.departmentText }}</div>
                </td>
                <td class="border-b border-slate-100 px-4 py-3 text-slate-500">
                  <div class="truncate" :title="row.sourceText">{{ row.sourceText || "-" }}</div>
                </td>
                <td class="border-b border-slate-100 px-4 py-3 text-center">
                  <span class="permission-valid rounded-md px-2 py-1 text-xs font-medium">有效</span>
                </td>
                <td class="border-b border-slate-100 px-4 py-3 text-center">
                  <button
                    type="button"
                    class="inline-flex h-7 items-center gap-1 rounded-md px-2 text-xs font-medium text-slate-500 hover:bg-rose-50 hover:text-rose-600"
                    @click="excludeMember(row)"
                  >
                    <UserMinus class="h-3.5 w-3.5" />
                    排除
                  </button>
                </td>
              </tr>

              <tr v-for="row in excludedRows" :key="`excluded:${row.userId}`" class="bg-slate-50 text-slate-400">
                <td class="border-b border-slate-100 px-4 py-3">
                  <div class="flex min-w-0 items-center gap-3">
                    <div class="flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-md bg-slate-100 text-xs font-semibold text-slate-400">
                      <img
                        v-if="row.employee.avatarUrl"
                        :src="row.employee.avatarUrl"
                        :alt="row.name"
                        class="h-full w-full object-cover opacity-50"
                        referrerpolicy="no-referrer"
                      />
                      <span v-else>{{ employeeInitial(row.employee) }}</span>
                    </div>
                    <span class="min-w-0 truncate font-medium line-through">{{ row.name }}</span>
                  </div>
                </td>
                <td class="border-b border-slate-100 px-4 py-3">
                  <div class="truncate" :title="row.departmentText">{{ row.departmentText }}</div>
                </td>
                <td class="border-b border-slate-100 px-4 py-3">
                  <div class="truncate" :title="row.sourceText">{{ row.sourceText || "-" }}</div>
                </td>
                <td class="border-b border-slate-100 px-4 py-3 text-center">
                  <span class="rounded-md bg-slate-200 px-2 py-1 text-xs font-medium text-slate-500">已排除</span>
                </td>
                <td class="border-b border-slate-100 px-4 py-3 text-center">
                  <button
                    type="button"
                    class="inline-flex h-7 items-center rounded-md px-2 text-xs font-medium text-blue-600 hover:bg-blue-50"
                    @click="restoreExcludedMember(row)"
                  >
                    恢复
                  </button>
                </td>
              </tr>
            </tbody>
          </table>

          <div v-else class="flex h-full min-h-[220px] items-center justify-center text-sm text-slate-400">
            暂无权限成员
          </div>
        </div>
      </section>
    </div>

    <div
      v-if="sourcePicker.open"
      class="fixed inset-0 z-[170] flex items-center justify-center bg-slate-950/40 p-4"
      v-backdrop-dismiss="closeSourcePicker"
    >
      <div
        class="permission-picker flex max-h-[calc(100dvh-32px)] max-w-[calc(100vw-32px)] flex-col overflow-hidden rounded-md bg-white shadow-xl"
        :class="sourcePicker.scopeType === SCOPE_DEPARTMENT ? 'h-[640px] w-[760px]' : 'h-[560px] w-[560px]'"
        role="dialog"
        aria-modal="true"
        :aria-label="`添加${sourcePicker.scopeType === SCOPE_DEPARTMENT ? '部门' : '人员'}`"
        @click.stop
      >
        <div class="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-4">
          <h2 class="text-base font-semibold text-slate-900">
            添加{{ sourcePicker.scopeType === SCOPE_DEPARTMENT ? "部门" : "人员" }}
          </h2>
          <button
            type="button"
            class="inline-flex h-8 w-8 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-700"
            aria-label="关闭"
            @click="closeSourcePicker"
          >
            <X class="h-5 w-5" />
          </button>
        </div>

        <div class="border-b border-slate-100 px-4 py-3">
          <div class="flex h-10 items-center gap-2 rounded-md border border-slate-200 bg-white px-3 focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-100">
            <Search class="h-4 w-4 text-slate-400" />
            <input
              ref="sourcePickerInput"
              v-model.trim="sourcePicker.keyword"
              class="min-w-0 flex-1 border-0 bg-transparent text-sm text-slate-900 outline-none placeholder:text-slate-400"
              :placeholder="sourcePicker.scopeType === SCOPE_DEPARTMENT ? '搜索部门或者首字母' : '搜索姓名或者首字母'"
              @keydown="handleSourceKeydown"
            />
          </div>
        </div>

        <div v-if="sourcePicker.scopeType === SCOPE_DEPARTMENT" class="min-h-0 flex-1 overflow-auto p-3">
          <div class="permission-department-list flex min-h-full min-w-[560px] flex-col overflow-hidden rounded-md border border-slate-200">
            <div class="grid shrink-0 grid-cols-[minmax(0,1fr)_132px_72px] border-b border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-500">
              <div>部门</div>
              <div class="text-center">包含子部门</div>
              <div class="text-right">人数</div>
            </div>
            <div class="min-h-0 flex-1 overflow-y-auto">
              <div
                v-for="row in sourceDepartmentRows"
                :key="row.id"
                class="grid min-h-10 cursor-pointer grid-cols-[minmax(0,1fr)_132px_72px] items-center gap-2 border-b border-slate-100 px-3 py-2 last:border-b-0 hover:bg-blue-50/50"
                :class="forcedDepartmentIds.has(row.id) ? 'bg-slate-50 text-slate-400' : 'text-slate-700'"
                @click="toggleDepartmentExpanded(row)"
              >
                <div class="flex min-w-0 items-center gap-2" :style="{ paddingLeft: `${row.depth * 18}px` }">
                  <input
                    type="checkbox"
                    class="h-4 w-4 shrink-0 rounded border-slate-300 text-blue-600 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-60"
                    :checked="departmentSourceChecked(row.id)"
                    :disabled="forcedDepartmentIds.has(row.id)"
                    @click.stop
                    @change="toggleDepartmentSource(row)"
                  />
                  <ChevronDown
                    class="h-4 w-4 shrink-0 text-slate-400 transition-transform"
                    :class="[
                      row.hasChildren && row.expanded ? 'rotate-0' : '-rotate-90',
                      row.hasChildren ? '' : 'opacity-0',
                    ]"
                  />
                  <span class="min-w-0 truncate text-sm font-medium">{{ row.name }}</span>
                </div>
                <label class="flex items-center justify-center gap-1.5 text-xs text-slate-500" @click.stop>
                  <input
                    type="checkbox"
                    class="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-60"
                    :checked="departmentSourceMap.get(row.id)?.includeSubDepartments || false"
                    :disabled="forcedDepartmentIds.has(row.id)"
                    @change="setDepartmentIncludeSubDepartments(row, $event.target.checked)"
                  />
                  <span>包含</span>
                </label>
                <div class="text-right text-xs text-slate-400">{{ row.memberCount }}</div>
              </div>
              <div v-if="!sourceDepartmentRows.length" class="px-3 py-8 text-center text-sm text-slate-400">
                无匹配数据
              </div>
            </div>
          </div>
        </div>

        <div v-else class="min-h-0 flex-1 overflow-auto p-3">
          <div class="permission-employee-list flex min-h-full min-w-[420px] flex-col overflow-hidden rounded-md border border-slate-200">
            <div class="grid shrink-0 grid-cols-[minmax(0,1fr)_200px] border-b border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-500">
              <div>人员</div>
              <div class="text-right">部门</div>
            </div>
            <div class="min-h-0 flex-1 overflow-y-auto">
              <div
                v-for="row in sourceEmployeeRows"
                :key="row.id"
                class="grid min-h-12 cursor-pointer grid-cols-[minmax(0,1fr)_200px] items-center gap-3 border-b border-slate-100 px-3 py-2.5 last:border-b-0 hover:bg-blue-50/50"
                :class="row.selected ? 'bg-blue-50 text-blue-700' : 'text-slate-700'"
                @click="toggleEmployeeSource(row)"
              >
                <div class="flex min-w-0 items-center gap-3">
                  <input
                    type="checkbox"
                    class="h-4 w-4 shrink-0 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                    :checked="row.selected"
                    @click.stop
                    @change="toggleEmployeeSource(row)"
                  />
                  <span class="min-w-0 truncate text-sm font-semibold">{{ row.name }}</span>
                </div>
                <div class="truncate text-right text-xs text-slate-400" :title="row.meta">{{ row.meta }}</div>
              </div>
              <div v-if="!sourceEmployeeRows.length" class="px-3 py-8 text-center text-sm text-slate-400">
                无匹配数据
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <UnsavedChangesDialog :open="reloadConfirmOpen" message="重新加载会放弃当前权限草稿，请加载最新配置后重新核对。" @cancel="reloadConfirmOpen = false" @confirm="reloadConfirmOpen = false; loadData()" />
  </div>
</template>

<style scoped>
.permission-valid { background: #ecfdf5; color: #047857; }

@media (max-width: 1023px) {
  .permission-layout {
    min-height: 0;
  }
}

@media (max-width: 639px) {
  .permission-picker {
    height: min(720px, calc(100dvh - 24px)) !important;
    max-width: calc(100vw - 24px);
  }
}
</style>
