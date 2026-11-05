import { computed, onBeforeUnmount, onMounted, shallowRef, watch } from "vue";

import {
  fetchPermissionDirectory,
  fetchPermissionRules,
  savePermissionRules,
} from "@/features/competitiveApi";
import { matchesSearch } from "@/features/search";

export const permissionGroups = [
  { id: "admin", label: "竞品系统管理员", note: "维护权限、系统设置和全部竞品资料。" },
  { id: "reviewer", label: "审核人员", note: "审核采集资料并新建或归并竞品档案。" },
  { id: "collector", label: "采集人员", note: "新增采集、维护本人资料并查看竞品看板。" },
];

const emptyDirectory = {
  departments: [],
  employees: [],
  orgRevision: 0,
  directorySource: "unconfigured",
  available: false,
  message: "",
};

function normalizeId(value) {
  return String(value ?? "").trim();
}

function normalizeRules(items = []) {
  const seen = new Set();
  return items.map((item, index) => ({
    permission: item.permission,
    scopeType: item.scopeType,
    targetId: normalizeId(item.targetId),
    targetName: normalizeId(item.targetName),
    sortOrder: Number.isFinite(item.sortOrder) ? item.sortOrder : index,
  })).filter((item) => {
    const key = `${item.permission}:${item.scopeType}:${item.targetId}`;
    if (!item.targetId || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function serializeRules(items) {
  return JSON.stringify(
    normalizeRules(items).sort((left, right) =>
      `${left.permission}:${left.scopeType}:${left.targetId}`.localeCompare(
        `${right.permission}:${right.scopeType}:${right.targetId}`,
      ),
    ),
  );
}

function flattenDepartments(nodes, depth = 0, result = []) {
  for (const department of nodes || []) {
    result.push({ department, depth });
    flattenDepartments(department.children || [], depth + 1, result);
  }
  return result;
}

function descendantIds(department) {
  return new Set(flattenDepartments([department]).map((row) => normalizeId(row.department.deptId)));
}

function employeeDepartmentIds(employee) {
  return new Set((employee.departments || []).map((item) => normalizeId(item.deptId ?? item.id)));
}

export function employeeDepartmentText(employee) {
  const names = (employee.departments || []).map((item) => item.name).filter(Boolean);
  return names.length ? names.join(" / ") : "未分配部门";
}

function departmentMatches(department, keyword) {
  return matchesSearch(keyword, [
    department.name,
    department.deptId,
    department.pinyinInitials,
    department.departmentPathText,
  ]);
}

function filterDepartmentTree(nodes, keyword) {
  if (!keyword) return nodes;
  return (nodes || []).map((node) => {
    const children = filterDepartmentTree(node.children || [], keyword);
    return departmentMatches(node, keyword) || children.length
      ? { ...node, children }
      : null;
  }).filter(Boolean);
}

export function usePermissionSettings({ notify = () => {} } = {}) {
  const loading = shallowRef(true);
  const saving = shallowRef(false);
  const error = shallowRef("");
  const directory = shallowRef(emptyDirectory);
  const rules = shallowRef([]);
  const revision = shallowRef(0);
  const snapshot = shallowRef("[]");
  const activePermission = shallowRef("admin");
  const picker = shallowRef("");
  const keyword = shallowRef("");
  const expandedDepartments = shallowRef(new Set());
  let saveTimer;

  const allDepartmentRows = computed(() => flattenDepartments(directory.value.departments));
  const departmentById = computed(() => new Map(
    allDepartmentRows.value.map(({ department }) => [normalizeId(department.deptId), department]),
  ));
  const employeeById = computed(() => new Map(
    directory.value.employees.map((employee) => [normalizeId(employee.userId), employee]),
  ));
  const activeRules = computed(() => rules.value.filter(
    (rule) => rule.permission === activePermission.value,
  ));
  const activeSources = computed(() => activeRules.value.filter(
    (rule) => rule.scopeType !== "excludedEmployee",
  ));
  const serialized = computed(() => serializeRules(rules.value));
  const dirty = computed(() => !loading.value && serialized.value !== snapshot.value);

  const inheritedDepartmentRules = computed(() => {
    const inherited = new Map();
    for (const rule of activeRules.value) {
      if (rule.scopeType !== "departmentSub") continue;
      const parent = departmentById.value.get(rule.targetId);
      if (!parent) continue;
      for (const departmentId of descendantIds(parent)) {
        if (departmentId !== parent.deptId && !inherited.has(departmentId)) {
          inherited.set(departmentId, rule);
        }
      }
    }
    return inherited;
  });

  function memberRowsFor(permission) {
    const permissionRules = rules.value.filter((rule) => rule.permission === permission);
    const excludedIds = new Set(permissionRules
      .filter((rule) => rule.scopeType === "excludedEmployee")
      .map((rule) => rule.targetId));
    const sourcesByEmployee = new Map();
    const addSource = (employeeId, source) => {
      const sources = sourcesByEmployee.get(employeeId) || new Set();
      sources.add(source);
      sourcesByEmployee.set(employeeId, sources);
    };

    for (const rule of permissionRules) {
      if (rule.scopeType === "employee") {
        addSource(rule.targetId, rule.targetName || rule.targetId);
        continue;
      }
      if (!["department", "departmentSub"].includes(rule.scopeType)) continue;
      const department = departmentById.value.get(rule.targetId);
      const allowedIds = department && rule.scopeType === "departmentSub"
        ? descendantIds(department)
        : new Set([rule.targetId]);
      for (const employee of directory.value.employees) {
        if ([...employeeDepartmentIds(employee)].some((id) => allowedIds.has(id))) {
          addSource(
            normalizeId(employee.userId),
            `${rule.targetName || department?.name || rule.targetId}${rule.scopeType === "departmentSub" ? "（含下级）" : ""}`,
          );
        }
      }
    }

    return [...sourcesByEmployee.entries()].map(([employeeId, sources]) => {
      const employee = employeeById.value.get(employeeId);
      return employee ? {
        employee,
        sourceText: [...sources].join("、"),
        excluded: excludedIds.has(employeeId),
      } : null;
    }).filter(Boolean).sort((left, right) => {
      if (left.excluded !== right.excluded) return left.excluded ? 1 : -1;
      return left.employee.name.localeCompare(right.employee.name, "zh-Hans-CN");
    });
  }

  const activeMembers = computed(() => memberRowsFor(activePermission.value));
  const roleSummaries = computed(() => Object.fromEntries(permissionGroups.map((group) => {
    const members = memberRowsFor(group.id);
    return [group.id, {
      memberCount: members.filter((row) => !row.excluded).length,
      excludedCount: members.filter((row) => row.excluded).length,
      sourceCount: rules.value.filter(
        (rule) => rule.permission === group.id && rule.scopeType !== "excludedEmployee",
      ).length,
    }];
  })));

  const filteredDepartmentTree = computed(() => filterDepartmentTree(
    directory.value.departments,
    keyword.value,
  ));
  const visibleDepartmentRows = computed(() => {
    const result = [];
    const searching = Boolean(keyword.value.trim());
    function walk(nodes, depth = 0) {
      for (const department of nodes || []) {
        result.push({ department, depth });
        if (searching || expandedDepartments.value.has(normalizeId(department.deptId))) {
          walk(department.children || [], depth + 1);
        }
      }
    }
    walk(filteredDepartmentTree.value);
    return result;
  });
  const filteredEmployees = computed(() => {
    return directory.value.employees.filter((employee) => matchesSearch(
      keyword.value,
      [
        employee.name,
        employee.userId,
        employee.pinyinInitials,
        employeeDepartmentText(employee),
        ...(employee.departments || []).flatMap((department) => [
          department.deptId,
          department.pinyinInitials,
          department.departmentPathText,
        ]),
      ],
    ));
  });

  async function load() {
    loading.value = true;
    error.value = "";
    try {
      const [permissionData, directoryData] = await Promise.all([
        fetchPermissionRules(),
        fetchPermissionDirectory(),
      ]);
      const nextRules = normalizeRules(permissionData.items);
      rules.value = nextRules;
      snapshot.value = serializeRules(nextRules);
      revision.value = permissionData.revision;
      directory.value = { ...emptyDirectory, ...directoryData };
      expandedDepartments.value = new Set((directoryData.departments || []).map(
        (department) => normalizeId(department.deptId),
      ));
    } catch (reason) {
      error.value = reason.message || "权限配置加载失败";
    } finally {
      loading.value = false;
    }
  }

  async function save() {
    if (!dirty.value || loading.value || saving.value) return;
    const sentRules = normalizeRules(rules.value);
    const sentSnapshot = serializeRules(sentRules);
    saving.value = true;
    error.value = "";
    try {
      const data = await savePermissionRules(
        sentRules,
        revision.value,
        directory.value.orgRevision,
      );
      const nextRules = normalizeRules(data.items);
      if (serialized.value === sentSnapshot) rules.value = nextRules;
      snapshot.value = serializeRules(nextRules);
      revision.value = data.revision;
      directory.value = { ...directory.value, orgRevision: data.orgRevision };
    } catch (reason) {
      const message = reason.message || "权限配置保存失败";
      if (message.includes("已更新")) {
        await load();
        error.value = `${message}，页面数据已刷新，请重新确认`;
      } else {
        error.value = message;
      }
      notify(error.value);
    } finally {
      saving.value = false;
    }
  }

  function replaceRule(nextRule) {
    rules.value = normalizeRules([
      ...rules.value.filter((item) => !(
        item.permission === nextRule.permission
        && item.targetId === nextRule.targetId
        && (["department", "departmentSub"].includes(item.scopeType)
          === ["department", "departmentSub"].includes(nextRule.scopeType))
      )),
      nextRule,
    ]);
  }

  function removeRule(rule) {
    rules.value = rules.value.filter((item) => !(
      item.permission === rule.permission
      && item.scopeType === rule.scopeType
      && item.targetId === rule.targetId
    ));
  }

  function toggleDepartment(department) {
    const id = normalizeId(department.deptId);
    const existing = activeRules.value.find((rule) =>
      rule.targetId === id && ["department", "departmentSub"].includes(rule.scopeType));
    if (existing) removeRule(existing);
    else replaceRule({
      permission: activePermission.value,
      scopeType: "department",
      targetId: id,
      targetName: department.name,
      sortOrder: activeSources.value.length,
    });
  }

  function setDepartmentDescendants(department, include) {
    const id = normalizeId(department.deptId);
    const existing = activeRules.value.find((rule) =>
      rule.targetId === id && ["department", "departmentSub"].includes(rule.scopeType));
    if (!existing) return;
    const descendants = descendantIds(department);
    rules.value = rules.value.filter((rule) => !(
      include
      && rule.permission === activePermission.value
      && descendants.has(rule.targetId)
      && rule.targetId !== id
      && ["department", "departmentSub"].includes(rule.scopeType)
    ));
    replaceRule({ ...existing, scopeType: include ? "departmentSub" : "department" });
  }

  function toggleEmployee(employee) {
    const id = normalizeId(employee.userId);
    const existing = activeRules.value.find(
      (rule) => rule.scopeType === "employee" && rule.targetId === id,
    );
    if (existing) removeRule(existing);
    else replaceRule({
      permission: activePermission.value,
      scopeType: "employee",
      targetId: id,
      targetName: employee.name,
      sortOrder: activeSources.value.length,
    });
  }

  function excludeMember(row) {
    const employeeId = normalizeId(row.employee.userId);
    rules.value = rules.value.filter((rule) => !(
      rule.permission === activePermission.value
      && rule.scopeType === "employee"
      && rule.targetId === employeeId
    ));
    replaceRule({
      permission: activePermission.value,
      scopeType: "excludedEmployee",
      targetId: employeeId,
      targetName: row.employee.name,
      sortOrder: 0,
    });
  }

  function restoreMember(row) {
    const rule = activeRules.value.find((item) =>
      item.scopeType === "excludedEmployee"
      && item.targetId === normalizeId(row.employee.userId));
    if (rule) removeRule(rule);
  }

  function openPicker(type) {
    picker.value = type;
    keyword.value = "";
  }

  function closePicker() {
    picker.value = "";
    keyword.value = "";
  }

  function toggleDepartmentExpanded(department) {
    const id = normalizeId(department.deptId);
    const next = new Set(expandedDepartments.value);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    expandedDepartments.value = next;
  }

  watch(dirty, (isDirty) => {
    window.clearTimeout(saveTimer);
    if (isDirty && !saving.value) saveTimer = window.setTimeout(save, 400);
  });
  watch(saving, (isSaving) => {
    if (!isSaving && dirty.value) {
      window.clearTimeout(saveTimer);
      saveTimer = window.setTimeout(save, 400);
    }
  });
  onMounted(load);
  onBeforeUnmount(() => window.clearTimeout(saveTimer));

  return {
    loading,
    saving,
    error,
    directory,
    activePermission,
    picker,
    keyword,
    activeRules,
    activeSources,
    activeMembers,
    roleSummaries,
    inheritedDepartmentRules,
    visibleDepartmentRows,
    filteredEmployees,
    dirty,
    replaceRule,
    removeRule,
    toggleDepartment,
    setDepartmentDescendants,
    toggleEmployee,
    excludeMember,
    restoreMember,
    openPicker,
    closePicker,
    toggleDepartmentExpanded,
    isDepartmentExpanded: (department) => expandedDepartments.value.has(normalizeId(department.deptId)),
    employeeDepartmentText,
  };
}
