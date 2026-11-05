<script setup>
import { computed } from "vue";
import { LoaderCircle, Pencil, Save, Search, X } from "@lucide/vue";
import { matchesDirectorySearchKeyword } from "@platform-ui";
import SettingsDepartmentTreeNode from "@/components/settings/SettingsDepartmentTreeNode_web.vue";
import SettingsDepartmentEmployeesPanel from "@/components/settings/SettingsDepartmentEmployeesPanel_web.vue";

const props = defineProps({
  canOpenOrganizationActions: Boolean,
  organizationActionRunning: String,
  departmentTree: { type: Array, required: true },
  selectedDepartment: { type: Object, default: null },
  expandedDeptIds: { type: Array, required: true },
  selectedDepartmentName: { type: String, required: true },
  departmentEmployees: { type: Array, required: true },
  selectedManager: { type: Object, default: null },
  managers: { type: Array, default: () => [] },
  departmentPath: { type: Array, default: () => [] },
  directEmployeeCount: { type: Number, default: null },
  subtreeEmployeeCount: { type: Number, default: null },
  errorMessage: { type: String, default: "" },
  treeError: { type: String, default: "" },
  treeKeyword: { type: String, default: "" },
  loadingTree: Boolean,
  includeSubDepartments: Boolean,
  departmentKeyword: { type: String, default: "" },
  loadingDepartment: Boolean,
  sortedDepartmentEmployees: { type: Array, required: true },
  canOperateDepartmentEmployee: Boolean,
  accountStatusSavingUserId: { type: String, default: "" },
  proxyActionUserId: { type: String, default: "" },
  primaryDepartmentName: { type: Function, required: true },
  showDisabledDepartments: Boolean,
  canManageEnabledDepartments: Boolean,
  editingEnabledDepartments: Boolean,
  enabledDepartmentIds: { type: Array, required: true },
  enabledDepartmentsDirty: Boolean,
  loadingEnabledDepartments: Boolean,
  savingEnabledDepartments: Boolean,
});

const departmentTreeKeyword = computed({ get: () => props.treeKeyword, set: (value) => emit("update-tree-keyword", value) });

function departmentMatches(department, keyword) {
  return matchesDirectorySearchKeyword(keyword, {
    names: department?.name,
    ids: department?.deptId,
    pinyin: department?.pinyin,
    pinyinInitials: department?.pinyinInitials,
  });
}

function filterDepartmentNodes(nodes, keyword) {
  return (nodes || []).flatMap((node) => {
    const children = filterDepartmentNodes(node.children || [], keyword);
    if (!departmentMatches(node, keyword) && !children.length) return [];
    return [{ ...node, children }];
  });
}

function collectDepartmentIds(nodes, result = []) {
  (nodes || []).forEach((node) => {
    result.push(node.deptId);
    collectDepartmentIds(node.children || [], result);
  });
  return result;
}

const visibleDepartmentTree = computed(() => {
  const keyword = departmentTreeKeyword.value.trim();
  return keyword ? filterDepartmentNodes(props.departmentTree, keyword) : props.departmentTree;
});
const visibleExpandedDeptIds = computed(() => (
  departmentTreeKeyword.value.trim()
    ? collectDepartmentIds(visibleDepartmentTree.value)
    : props.expandedDeptIds
));

const emit = defineEmits([
  "open-organization-action", "update-tree-keyword", "retry", "retry-tree",
  "select-department",
  "toggle-department",
  "update-include-sub-departments",
  "update-department-keyword",
  "open-employee-action",
  "update-show-disabled-departments",
  "update-department-enabled",
  "start-enabled-departments-edit",
  "cancel-enabled-departments-edit",
  "save-enabled-departments",
]);
</script>

<template>
  <div class="flex h-full min-h-0 min-w-0 flex-1 gap-4">
    <section
      class="organization-department-tree flex min-h-0 w-[300px] shrink-0 flex-col rounded-lg border border-slate-200 bg-white"
      aria-label="部门设置"
    >
      <div class="flex min-h-12 flex-wrap items-center justify-between gap-2 border-b border-slate-200 p-3">
        <span class="text-sm font-semibold text-slate-700">部门目录</span>
        <div class="flex items-center gap-2">
          <button
            v-if="canManageEnabledDepartments && !editingEnabledDepartments"
            type="button"
            class="inline-flex h-8 min-w-[64px] items-center justify-center gap-1 rounded-md border border-slate-200 bg-white px-2 text-xs font-semibold text-slate-700 transition hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
            :disabled="loadingEnabledDepartments || savingEnabledDepartments"
            @click="emit('start-enabled-departments-edit')"
          >
            <Pencil class="h-3.5 w-3.5" aria-hidden="true" />
            启用范围
          </button>
          <button
            v-if="canManageEnabledDepartments && editingEnabledDepartments"
            type="button"
            class="inline-flex h-8 min-w-[54px] items-center justify-center gap-1 rounded-md border border-slate-200 bg-white px-2 text-xs font-semibold text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
            :disabled="savingEnabledDepartments"
            @click="emit('cancel-enabled-departments-edit')"
          >
            <X class="h-3.5 w-3.5" aria-hidden="true" />
            取消
          </button>
          <button
            v-if="canManageEnabledDepartments && editingEnabledDepartments"
            type="button"
            class="organization-enabled-save inline-flex h-8 min-w-[64px] items-center justify-center gap-1 rounded-md bg-blue-600 px-2 text-xs font-semibold text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-blue-300"
            :disabled="loadingEnabledDepartments || savingEnabledDepartments || !enabledDepartmentsDirty"
            :aria-busy="savingEnabledDepartments"
            aria-label="保存"
            title="保存启用部门"
            data-ai-action="auth.enabled-departments.save"
            @click="emit('save-enabled-departments')"
          >
            <LoaderCircle v-if="savingEnabledDepartments" class="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            <Save v-else class="h-3.5 w-3.5" aria-hidden="true" />
            <span class="organization-save-label">{{ savingEnabledDepartments ? "保存中" : "保存" }}</span>
          </button>
        </div>
      </div>
      <div v-if="canManageEnabledDepartments && editingEnabledDepartments" class="flex items-center justify-between gap-2 border-b border-slate-100 px-3 py-2">
        <label class="flex w-fit cursor-pointer select-none items-center gap-1.5 whitespace-nowrap text-xs text-slate-500">
          <input
            :checked="showDisabledDepartments"
            type="checkbox"
            class="h-4 w-4 accent-blue-600"
            :disabled="loadingEnabledDepartments || savingEnabledDepartments"
            @change="emit('update-show-disabled-departments', $event.target.checked)"
          />
          查看未启用部门
        </label>
        <span v-if="enabledDepartmentsDirty" class="text-xs text-amber-700" role="status">未保存</span>
      </div>
      <div class="border-b border-slate-100 p-2.5">
        <label class="flex h-9 items-center gap-2 rounded-lg border border-slate-200 px-3">
          <Search class="h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden="true" />
          <input
            v-model.trim="departmentTreeKeyword"
            type="search"
            aria-label="搜索部门名称、ID或拼音"
            placeholder="部门名称、ID或拼音"
            class="min-w-0 flex-1 bg-transparent text-sm outline-none"
          />
        </label>
      </div>
      <div class="scrollbar-hidden min-h-0 flex-1 overflow-y-auto overscroll-contain">
        <p v-if="loadingTree" class="p-6 text-center text-sm text-slate-500" role="status">正在加载部门</p>
        <div v-else-if="treeError" class="p-4 text-sm" role="alert"><p class="text-red-700">{{ treeError }}</p><button type="button" class="org-button mt-2" @click="emit('retry-tree')">重新加载部门</button></div>
        <SettingsDepartmentTreeNode
          v-else-if="visibleDepartmentTree.length"
          :nodes="visibleDepartmentTree"
          :selected-dept-id="selectedDepartment?.deptId"
          :expanded-dept-ids="visibleExpandedDeptIds"
          :enabled-department-ids="enabledDepartmentIds"
          :can-manage-enabled-departments="canManageEnabledDepartments"
          :editing-enabled-departments="editingEnabledDepartments"
          :enabled-departments-busy="loadingEnabledDepartments || savingEnabledDepartments"
          @select="emit('select-department', $event)"
          @toggle="emit('toggle-department', $event)"
          @update-enabled="emit('update-department-enabled', $event)"
        />
        <div v-else class="px-3 py-8 text-center text-sm text-slate-400">{{ departmentTreeKeyword ? "未找到匹配部门" : "暂无已启用部门，可在启用范围中配置" }}</div>
      </div>
    </section>

    <SettingsDepartmentEmployeesPanel
      :selected-department-name="selectedDepartmentName"
      :department-employees="departmentEmployees"
      :selected-manager="selectedManager"
      :managers="managers"
      :department-path="departmentPath"
      :direct-employee-count="directEmployeeCount"
      :subtree-employee-count="subtreeEmployeeCount"
      :error-message="errorMessage"
      @select-department="emit('select-department', $event)"
      @retry="emit('retry')"
      :include-sub-departments="includeSubDepartments"
      :department-keyword="departmentKeyword"
      :loading-department="loadingDepartment"
      :sorted-department-employees="sortedDepartmentEmployees"
      :can-operate-department-employee="canOperateDepartmentEmployee"
      :account-status-saving-user-id="accountStatusSavingUserId"
      :proxy-action-user-id="proxyActionUserId"
      :primary-department-name="primaryDepartmentName"
      :show-organization-action="canOpenOrganizationActions"
      :organization-action-running="organizationActionRunning"
      :organization-settings-saving="savingEnabledDepartments"
      @update-include-sub-departments="emit('update-include-sub-departments', $event)"
      @update-department-keyword="emit('update-department-keyword', $event)"
      @open-employee-action="emit('open-employee-action', $event)"
      @open-organization-action="emit('open-organization-action')"
    />
  </div>
</template>

<style scoped>
@media (min-width: 768px) and (max-width: 1100px) {
  .organization-department-tree {
    width: 240px;
  }
}
</style>
