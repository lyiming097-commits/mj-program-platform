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
  UserRound,
  UsersRound,
  X,
} from "@lucide/vue";

import { apiGet, apiPost } from "@/api";
import UnsavedChangesDialog from "@/components/UnsavedChangesDialog.vue";

const props = defineProps({
  compact: {
    type: Boolean,
    default: false,
  },
  categoryId: {
    type: [String, Number],
    default: "",
  },
  externalSave: {
    type: Boolean,
    default: false,
  },
});
const emit = defineEmits(["dirty-change", "ready-change", "confirm-open-change", "saved"]);

const PERMISSION = {
  id: "admin",
  label: "管理员权限",
  note: "允许进入设置并维护权限。",
};
const SCOPE_DEPARTMENT = "department";
const SCOPE_DEPARTMENT_WITH_SUB = "departmentSub";
const SCOPE_EMPLOYEE = "employee";
const SOURCE_GROUPS = [
  { id: SCOPE_DEPARTMENT, label: "部门", icon: Building2, empty: "未添加部门" },
  { id: SCOPE_EMPLOYEE, label: "人员", icon: UserRound, empty: "未添加人员" },
];
const VALID_SCOPES = new Set([
  SCOPE_DEPARTMENT,
  SCOPE_EMPLOYEE,
]);

const loading = ref(true);
const saving = ref(false);
const loadFailed = ref(false);
const errorMessage = ref("");
const saveSucceeded = ref(false);
const departmentTree = ref([]);
const departments = ref([]);
const employees = ref([]);
const rules = ref([]);
const revision = ref("");
const orgRevision = ref("");
const snapshot = ref("");
const expandedDepartmentIds = ref(new Set());
const sourcePickerInput = ref(null);
const sourcePickerDialog = ref(null);
const refreshConfirmOpen = ref(false);
const activeDataKey = ref("");
let sourcePickerTrigger = null;
let loadSequence = 0;
let saveSequence = 0;

const sourcePicker = reactive({
  open: false,
  scopeType: SCOPE_DEPARTMENT,
  keyword: "",
});

const normalizedCategoryId = computed(() => normalizeId(props.categoryId));
const permissionsEndpoint = computed(() => (
  props.compact
    ? `/api/approval-center/categories/${encodeURIComponent(normalizedCategoryId.value)}/permissions`
    : "/api/approval-center/permissions"
));
const dataReady = computed(() => (
  !loading.value
  && !loadFailed.value
  && Boolean(revision.value)
  && Boolean(orgRevision.value)
));
const canEdit = computed(() => dataReady.value && !saving.value);
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
  label: props.compact
    ? (group.id === SCOPE_DEPARTMENT ? "权限部门" : "权限人员")
    : group.label,
  rows: rulesFor(group.id),
})));
const memberRows = computed(() => baseMemberRows(rules.value));
const sourceTotal = computed(() => departmentSources.value.length + employeeSources.value.length);
const permissionDirty = computed(() => (
  dataReady.value && snapshot.value !== serializeRules(rules.value)
));
const canSave = computed(() => permissionDirty.value && canEdit.value);
const saveButtonText = computed(() => (
  saving.value
    ? "保存中"
    : (saveSucceeded.value && !permissionDirty.value
      ? "已保存"
      : (props.compact ? "保存权限" : "保存"))
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

  return normalized;
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

function baseMemberRows(items) {
  const departmentIds = departmentIdsForRules(items);
  const directIds = new Set(rulesFor(SCOPE_EMPLOYEE, items).map((rule) => rule.targetId));
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

function rulesForApi(items = rules.value) {
  return normalizeRules(items).map((rule) => {
    const scopeType = rule.scopeType === SCOPE_DEPARTMENT && rule.includeSubDepartments
      ? SCOPE_DEPARTMENT_WITH_SUB
      : rule.scopeType;
    return {
      permission: PERMISSION.id,
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
  if (!canEdit.value || !row?.id || forcedDepartmentIds.value.has(row.id)) return;
  const existing = departmentSourceMap.value.get(row.id);
  const next = existing
    ? rules.value.filter((rule) => ruleKey(rule) !== ruleKey(existing))
    : [...rules.value, makeDepartmentSource(row)];
  rules.value = normalizeRules(next);
}

function setDepartmentIncludeSubDepartments(row, checked) {
  if (!canEdit.value || !row?.id || forcedDepartmentIds.value.has(row.id)) return;
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
  if (!canEdit.value || !row?.id) return;
  const existing = employeeSourceMap.value.get(row.id);
  if (existing) {
    rules.value = normalizeRules(rules.value.filter((rule) => !(
      rule.scopeType === SCOPE_EMPLOYEE && rule.targetId === row.id
    )));
    return;
  }
  rules.value = normalizeRules([
    ...rules.value,
    {
      permission: PERMISSION.id,
      scopeType: SCOPE_EMPLOYEE,
      targetId: row.id,
      targetName: row.name,
      sortOrder: employeeSources.value.length,
      includeSubDepartments: false,
    },
  ]);
}

function removeRule(ruleToRemove) {
  if (!canEdit.value) return;
  rules.value = normalizeRules(rules.value.filter((rule) => ruleKey(rule) !== ruleKey(ruleToRemove)));
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
  if (!canEdit.value) return;
  sourcePickerTrigger = document.activeElement;
  sourcePicker.open = true;
  sourcePicker.scopeType = scopeType;
  sourcePicker.keyword = "";
  if (scopeType === SCOPE_DEPARTMENT) expandDepartmentPickerDefaults();
  nextTick(() => sourcePickerInput.value?.focus?.());
}

function closeSourcePicker() {
  sourcePicker.open = false;
  const trigger = sourcePickerTrigger;
  sourcePickerTrigger = null;
  nextTick(() => trigger?.focus?.());
}

function handleSourceKeydown(event) {
  if (event.key !== "Enter") return;
  const first = sourcePicker.scopeType === SCOPE_DEPARTMENT
    ? sourceDepartmentRows.value[0]
    : sourceEmployeeRows.value[0];
  if (!first) return;
  event.preventDefault();
  if (sourcePicker.scopeType === SCOPE_DEPARTMENT) toggleDepartmentSource(first);
  else toggleEmployeeSource(first);
}

function sourcePickerFocusableElements() {
  const dialog = sourcePickerDialog.value;
  if (!dialog) return [];
  return [...dialog.querySelectorAll(
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
  )].filter((element) => element.getAttribute("aria-hidden") !== "true" && element.getClientRects().length);
}

function handleSourcePickerKeydown(event) {
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    closeSourcePicker();
    return;
  }
  if (event.key !== "Tab") return;
  const dialog = sourcePickerDialog.value;
  const focusable = sourcePickerFocusableElements();
  if (!focusable.length) {
    event.preventDefault();
    dialog?.focus?.();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const activeElement = document.activeElement;
  if (!dialog?.contains(activeElement)) {
    event.preventDefault();
    first.focus();
  } else if (event.shiftKey && activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function handleWindowKeydown(event) {
  if (event.key === "Escape" && sourcePicker.open) closeSourcePicker();
}

async function loadData() {
  const requestSequence = ++loadSequence;
  const requestCategoryId = normalizedCategoryId.value;
  const requestDataKey = props.compact ? `category:${requestCategoryId}` : "global";
  const requestEndpoint = permissionsEndpoint.value;

  ++saveSequence;
  saving.value = false;
  loading.value = true;
  loadFailed.value = false;
  errorMessage.value = "";
  saveSucceeded.value = false;
  if (sourcePicker.open) closeSourcePicker();
  if (requestDataKey !== activeDataKey.value) {
    departmentTree.value = [];
    departments.value = [];
    employees.value = [];
    rules.value = [];
    revision.value = "";
    orgRevision.value = "";
    snapshot.value = "";
    expandedDepartmentIds.value = new Set();
  }
  try {
    if (props.compact && !requestCategoryId) {
      throw new Error("请选择审批分类后再设置权限");
    }
    const [permissionData, directoryData] = await Promise.all([
      apiGet(requestEndpoint),
      apiGet("/api/approval-center/permissions/directory"),
    ]);
    if (requestSequence !== loadSequence) return;
    const nextRevision = normalizeId(permissionData?.revision);
    const nextOrgRevision = normalizeId(directoryData?.orgRevision);
    if (!nextRevision || !nextOrgRevision) {
      throw new Error("权限数据缺少修订信息，请刷新后重试");
    }
    const tree = normalizeDepartmentTree(directoryData?.departments || []);
    departmentTree.value = tree;
    departments.value = flattenDepartments(tree, []);
    employees.value = (Array.isArray(directoryData?.employees) ? directoryData.employees : [])
      .map(normalizeEmployee)
      .filter((employee) => employee.id);
    expandedDepartmentIds.value = new Set(tree.map((department) => department.id));
    revision.value = nextRevision;
    orgRevision.value = nextOrgRevision;
    rules.value = normalizeRules(permissionData?.items || []);
    snapshot.value = serializeRules(rules.value);
    activeDataKey.value = requestDataKey;
  } catch (error) {
    if (requestSequence !== loadSequence) return;
    loadFailed.value = true;
    errorMessage.value = error instanceof Error ? error.message : "权限加载失败";
  } finally {
    if (requestSequence === loadSequence) loading.value = false;
  }
}

function refreshData() {
  if (permissionDirty.value) {
    refreshConfirmOpen.value = true;
    emit("confirm-open-change", true);
    return;
  }
  loadData();
}

function cancelRefresh() {
  refreshConfirmOpen.value = false;
  emit("confirm-open-change", false);
}

function discardAndRefresh() {
  refreshConfirmOpen.value = false;
  emit("confirm-open-change", false);
  loadData();
}

async function saveRules() {
  if (!canSave.value) {
    return { ok: !permissionDirty.value, skipped: true };
  }
  const requestSequence = ++saveSequence;
  const requestCategoryId = normalizedCategoryId.value;
  const requestDataKey = props.compact ? `category:${requestCategoryId}` : "global";
  const requestEndpoint = permissionsEndpoint.value;
  const submittedItems = rulesForApi(rules.value);
  saving.value = true;
  errorMessage.value = "";
  saveSucceeded.value = false;
  try {
    const data = await apiPost(requestEndpoint, {
      items: submittedItems,
      revision: revision.value,
      orgRevision: orgRevision.value,
    });
    if (requestSequence !== saveSequence || requestDataKey !== activeDataKey.value) {
      return { ok: false, stale: true };
    }
    revision.value = normalizeId(data?.revision) || revision.value;
    orgRevision.value = normalizeId(data?.orgRevision) || orgRevision.value;
    rules.value = normalizeRules(
      Array.isArray(data?.items) ? data.items : submittedItems,
    );
    snapshot.value = serializeRules(rules.value);
    saveSucceeded.value = true;
    emit("saved", {
      ...(data && typeof data === "object" ? data : {}),
      categoryId: requestCategoryId,
      count: rulesForApi(rules.value).length,
    });
    return { ok: true, data };
  } catch (error) {
    if (requestSequence !== saveSequence || requestDataKey !== activeDataKey.value) {
      return { ok: false, stale: true, error };
    }
    if (!props.externalSave) {
      errorMessage.value = error instanceof Error ? error.message : "权限保存失败";
    }
    return { ok: false, error };
  } finally {
    if (requestSequence === saveSequence) saving.value = false;
  }
}

watch(permissionDirty, (dirty) => emit("dirty-change", dirty), { immediate: true });
watch(dataReady, (ready) => emit("ready-change", ready), { immediate: true });
watch(
  () => [props.compact, normalizedCategoryId.value],
  ([nextCompact, nextCategoryId], [previousCompact, previousCategoryId]) => {
    if (nextCompact === previousCompact && nextCategoryId === previousCategoryId) return;
    if (refreshConfirmOpen.value) {
      refreshConfirmOpen.value = false;
      emit("confirm-open-change", false);
    }
    loadData();
  },
);

onMounted(() => {
  window.addEventListener("keydown", handleWindowKeydown);
  loadData();
});

onBeforeUnmount(() => {
  ++loadSequence;
  ++saveSequence;
  window.removeEventListener("keydown", handleWindowKeydown);
  emit("confirm-open-change", false);
  emit("dirty-change", false);
  emit("ready-change", false);
});

defineExpose({
  hasPendingChanges: () => permissionDirty.value,
  refresh: refreshData,
  save: saveRules,
});
</script>

<template>
  <div
    class="permission-workbench flex min-h-0 w-full flex-col overflow-hidden bg-white"
    :class="compact ? 'h-auto flex-1' : 'h-full rounded-md border border-slate-200 shadow-sm'"
  >
    <header class="flex shrink-0 items-center justify-between gap-3 border-b border-slate-100 bg-white px-5 py-3">
      <div class="min-w-0">
        <h2 class="truncate text-base font-bold text-slate-900">{{ compact ? "管理权限" : "权限分配" }}</h2>
        <p v-if="!compact" class="mt-1 text-xs text-slate-500" role="status">{{ saving ? "正在保存..." : permissionDirty ? "有未保存的修改" : saveSucceeded ? "已保存" : "按部门和人员配置管理员权限" }}</p>
      </div>
      <button
        v-if="!externalSave"
        type="button"
        class="permission-save-action inline-flex h-8 min-w-[82px] items-center justify-center gap-1.5 rounded-md bg-blue-600 px-3 text-xs font-semibold text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-300"
        :disabled="!canSave"
        :aria-busy="saving"
        :data-ai-action="compact ? 'approval.category.permissions.save' : 'approval-center.settings.permissions.save'"
        @click="saveRules"
      >
        <LoaderCircle v-if="saving" class="h-3.5 w-3.5 animate-spin" />
        {{ saveButtonText }}
      </button>
    </header>

    <div
      v-if="errorMessage"
      class="flex shrink-0 items-center justify-between gap-3 border-b border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700"
      role="alert"
    >
      <span class="min-w-0 flex-1">{{ errorMessage }}</span>
      <button
        v-if="loadFailed"
        type="button"
        class="permission-error-retry-action inline-flex min-h-8 shrink-0 items-center justify-center rounded-md border border-rose-300 bg-white px-3 text-xs font-semibold text-rose-700 hover:bg-rose-100"
        @click="loadData"
      >
        重试
      </button>
    </div>

    <div
      v-if="loading"
      class="flex min-h-0 flex-1 items-center justify-center gap-2 bg-slate-50 p-6 text-sm text-slate-500"
      role="status"
    >
      <LoaderCircle class="h-4 w-4 animate-spin text-blue-600" />
      正在加载权限...
    </div>

    <div v-else class="min-h-0 flex-1 overflow-auto" :class="compact ? 'bg-white' : 'bg-slate-50'">
      <div
        class="h-full overflow-hidden"
        :class="compact
          ? 'min-h-0 bg-white'
          : 'permission-grid min-h-[520px]'"
      >
        <aside v-if="!compact" class="flex min-h-0 flex-col border-r border-slate-200 bg-white">
          <header class="shrink-0 border-b border-slate-100 px-4 py-3">
            <h3 class="text-sm font-bold text-slate-900">权限选择</h3>
          </header>
          <div class="min-h-0 flex-1 overflow-auto p-3">
            <div class="w-full rounded-md border border-blue-300 bg-blue-50 px-3 py-3 text-left text-blue-700 shadow-sm">
              <div class="flex items-center justify-between gap-2">
                <div class="flex min-w-0 items-center gap-2">
                  <ShieldCheck class="h-4 w-4 shrink-0" />
                  <span class="truncate text-sm font-bold">{{ PERMISSION.label }}</span>
                </div>
                <span class="shrink-0 rounded bg-white px-1.5 py-0.5 text-[11px] font-bold text-slate-500">
                  {{ memberRows.length }} 人
                </span>
              </div>
              <div class="mt-2 text-xs font-medium leading-5 text-slate-500">{{ PERMISSION.note }}</div>
              <div class="mt-1 text-[11px] font-medium text-slate-400">配置来源 {{ sourceTotal }}</div>
            </div>
          </div>
        </aside>

        <section
          class="flex min-h-0 flex-col bg-white"
          :class="compact ? 'h-full' : 'border-r border-slate-200'"
        >
          <header v-if="!compact" class="shrink-0 border-b border-slate-100 px-4 py-3">
            <h3 class="text-sm font-bold text-slate-900">人员配置</h3>
            <div class="mt-0.5 truncate text-xs font-medium text-slate-400">{{ PERMISSION.label }}</div>
          </header>
          <div class="min-h-0 flex-1 overflow-auto bg-white">
            <section
              v-for="group in sourceGroups"
              :key="group.id"
              class="border-b border-slate-100"
            >
              <header class="flex items-center justify-between gap-3 bg-slate-50 px-3 py-2.5">
                <div class="flex min-w-0 items-center gap-2 text-sm font-bold text-slate-800">
                  <component :is="group.icon" class="h-4 w-4 shrink-0 text-slate-500" />
                  <span>{{ group.label }}</span>
                </div>
                <button
                  type="button"
                  class="permission-source-add-action inline-flex h-7 items-center gap-1 rounded-md bg-blue-600 px-2.5 text-xs font-semibold text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-300"
                  :aria-label="`添加${group.id === SCOPE_DEPARTMENT ? '部门' : '人员'}管理员`"
                  :disabled="!canEdit"
                  @click.stop="openSourcePicker(group.id)"
                >
                  <Plus class="h-3.5 w-3.5" />
                  添加
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
                      class="shrink-0 rounded-sm border border-amber-300 bg-amber-100 px-1.5 py-0.5 text-[11px] font-semibold leading-none text-amber-700"
                    >
                      含下级
                    </span>
                    <button
                      type="button"
                      class="permission-source-remove-action inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-sm text-slate-400 hover:bg-rose-50 hover:text-rose-600 disabled:cursor-not-allowed disabled:opacity-50"
                      :aria-label="`移除${sourceDisplayName(source)}`"
                      :disabled="!canEdit"
                      @click="removeRule(source)"
                    >
                      <X class="h-3 w-3" />
                    </button>
                  </span>
                </div>
                <div v-else class="py-2 text-sm font-medium text-slate-400">{{ group.empty }}</div>
              </div>
            </section>

          </div>
        </section>

        <section v-if="!compact" class="permission-members flex min-h-0 min-w-0 flex-col overflow-hidden bg-white">
          <header class="flex shrink-0 items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
            <div class="flex min-w-0 items-center gap-2">
              <UserRound class="h-4 w-4 shrink-0 text-blue-600" />
              <div class="min-w-0">
                <h3 class="truncate text-sm font-bold text-slate-900">具体人员</h3>
                <div class="mt-0.5 truncate text-xs font-medium text-slate-400">{{ PERMISSION.label }}</div>
              </div>
            </div>
            <div class="shrink-0 rounded-md bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-500">
              {{ memberRows.length }} 人
            </div>
          </header>
          <div class="min-h-0 flex-1 overflow-auto bg-white">
            <table class="w-full min-w-[540px] table-fixed border-collapse text-sm">
              <caption class="sr-only">管理员权限具体人员</caption>
              <colgroup>
                <col class="w-[145px]" />
                <col />
                <col class="w-[100px]" />
              </colgroup>
              <thead class="sticky top-0 z-10 bg-slate-50">
                <tr class="text-xs text-slate-500">
                  <th class="border-b border-slate-200 px-4 py-2 text-left font-semibold">姓名</th>
                  <th class="border-b border-slate-200 px-3 py-2 text-left font-semibold">所在部门</th>
                  <th class="border-b border-slate-200 px-3 py-2 text-left font-semibold">权限来源</th>
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
                        <div class="truncate text-[14px] font-semibold leading-5 text-slate-900">{{ row.name }}</div>
                        <div class="truncate text-[11px] font-medium text-slate-400">{{ row.userId }}</div>
                      </div>
                    </div>
                  </td>
                  <td class="border-b border-slate-100 px-3 py-2">
                    <div class="truncate text-xs font-medium text-slate-600" :title="row.departmentText">
                      {{ row.departmentText }}
                    </div>
                  </td>
                  <td class="border-b border-slate-100 px-3 py-2">
                    <div class="truncate text-xs font-medium text-slate-500" :title="row.sourceText">
                      {{ row.sourceText || "-" }}
                    </div>
                  </td>
                </tr>
                <tr v-if="!memberRows.length">
                  <td colspan="3" class="px-3 py-12 text-center text-sm font-medium text-slate-400">暂无人员</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>

    <div
      v-if="sourcePicker.open"
      class="fixed inset-0 z-[170] flex items-center justify-center bg-slate-950/40 p-4"
      v-backdrop-dismiss="closeSourcePicker"
    >
      <div
        ref="sourcePickerDialog"
        class="permission-picker flex max-h-[calc(100dvh-32px)] max-w-[calc(100vw-32px)] flex-col overflow-hidden rounded-md bg-white shadow-xl"
        :class="sourcePicker.scopeType === SCOPE_DEPARTMENT ? 'h-[640px] w-[760px]' : 'h-[560px] w-[560px]'"
        role="dialog"
        aria-modal="true"
        :aria-label="`添加${sourcePicker.scopeType === SCOPE_DEPARTMENT ? '部门' : '人员'}`"
        tabindex="-1"
        @click.stop
        @keydown="handleSourcePickerKeydown"
      >
        <div class="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-4">
          <h2 class="text-base font-semibold text-slate-900">
            添加{{ sourcePicker.scopeType === SCOPE_DEPARTMENT ? "部门" : "人员" }}
          </h2>
          <button
            type="button"
            class="permission-picker-close-action inline-flex h-8 w-8 items-center justify-center rounded-md text-slate-400 hover:bg-slate-100 hover:text-slate-700"
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
              :aria-label="sourcePicker.scopeType === SCOPE_DEPARTMENT ? '搜索部门' : '搜索人员'"
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
                class="permission-department-row grid min-h-10 cursor-pointer grid-cols-[minmax(0,1fr)_132px_72px] items-center gap-2 border-b border-slate-100 px-3 py-2 last:border-b-0 hover:bg-blue-50/50"
                :class="forcedDepartmentIds.has(row.id) ? 'bg-slate-50 text-slate-400' : 'text-slate-700'"
                @click="toggleDepartmentExpanded(row)"
              >
                <div class="flex min-w-0 items-center gap-2" :style="{ paddingLeft: `${row.depth * 18}px` }">
                  <label class="permission-department-select-target inline-flex shrink-0 items-center justify-center" @click.stop>
                    <input
                      type="checkbox"
                      class="h-4 w-4 shrink-0 rounded border-slate-300 text-blue-600 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-60"
                      :aria-label="`${row.name}部门`"
                      :checked="departmentSourceChecked(row.id)"
                      :disabled="!canEdit || forcedDepartmentIds.has(row.id)"
                      @change="toggleDepartmentSource(row)"
                    />
                  </label>
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
                    :aria-label="`${row.name}包含子部门`"
                    :checked="departmentSourceMap.get(row.id)?.includeSubDepartments || false"
                    :disabled="!canEdit || forcedDepartmentIds.has(row.id)"
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
                class="permission-employee-row grid min-h-12 cursor-pointer grid-cols-[minmax(0,1fr)_200px] items-center gap-3 border-b border-slate-100 px-3 py-2.5 last:border-b-0 hover:bg-blue-50/50"
                :class="row.selected ? 'bg-blue-50 text-blue-700' : 'text-slate-700'"
                @click="toggleEmployeeSource(row)"
              >
                <div class="flex min-w-0 items-center gap-3">
                  <input
                    type="checkbox"
                    class="h-4 w-4 shrink-0 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                    :aria-label="`${row.name}管理员`"
                    :checked="row.selected"
                    :disabled="!canEdit"
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

    <UnsavedChangesDialog
      :open="refreshConfirmOpen"
      message="当前权限配置尚未保存，刷新后本次修改不会保留。"
      @cancel="cancelRefresh"
      @confirm="discardAndRefresh"
    />
  </div>
</template>

<style scoped>
.permission-workbench { container-type: inline-size; }
.permission-grid { display: grid; grid-template-columns: 200px minmax(260px, .8fr) minmax(460px, 1.2fr); }
.permission-grid > * { min-width: 0; }
@container (max-width: 959px) {
  .permission-grid { height: auto; min-height: 100%; grid-template-columns: minmax(0, 1fr); overflow: visible; }
  .permission-grid > * { border-right: 0; border-bottom: 1px solid #e2e8f0; }
  .permission-grid > aside { min-height: 150px; max-height: 210px; }
  .permission-grid > section { min-height: 180px; max-height: 360px; }
  .permission-grid > .permission-members { min-height: 260px; max-height: 440px; }
}
@media (max-width: 639px) {
  .permission-picker {
    height: min(720px, calc(100dvh - 24px)) !important;
    max-width: calc(100vw - 24px);
  }

  .permission-save-action,
  .permission-source-add-action,
  .permission-source-remove-action,
  .permission-source-restore-action,
  .permission-error-retry-action,
  .permission-picker-close-action {
    min-width: 44px;
    min-height: 44px;
  }

  .permission-department-list,
  .permission-employee-list {
    min-width: 0;
  }

  .permission-department-list > :first-child,
  .permission-department-row {
    grid-template-columns: minmax(0, 1fr) 88px 32px;
  }

  .permission-employee-list > :first-child,
  .permission-employee-row {
    grid-template-columns: minmax(0, 1fr) minmax(88px, 34%);
  }

  .permission-department-row {
    min-height: 44px;
  }

  .permission-department-select-target {
    width: 44px;
    height: 44px;
  }
}
</style>
