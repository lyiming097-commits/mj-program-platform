<script setup>
import { computed, ref } from "vue";
import { ChevronDown, Crown, Search } from "@lucide/vue";

const props = defineProps({
  canManageEmployeeAccountStatus: Boolean,
  organizationActionRunning: String,
  selectedDepartment: { type: Object, default: null },
  selectedDepartmentPath: { type: Array, required: true },
  selectedDepartmentHasChildren: Boolean,
  departmentPickerOptions: { type: Array, required: true },
  allDepartments: { type: Array, required: true },
  departmentEmployees: { type: Array, required: true },
  selectedManager: { type: Object, default: null },
  includeSubDepartments: Boolean,
  departmentKeyword: { type: String, default: "" },
  loadingDepartment: Boolean,
  sortedDepartmentEmployees: { type: Array, required: true },
  canOperateDepartmentEmployee: Boolean,
  accountStatusSavingUserId: { type: String, default: "" },
  proxyActionUserId: { type: String, default: "" },
  primaryDepartmentName: { type: Function, required: true },
});

const departmentSearchKeyword = ref("");
const departmentSearchResults = computed(() => {
  const keyword = departmentSearchKeyword.value.trim().toLowerCase();
  if (!keyword) return [];
  return props.allDepartments.filter((department) => (
    String(department.name || "").toLowerCase().includes(keyword)
    || String(department.deptId || "").toLowerCase().includes(keyword)
    || String(department.pinyinInitials || "").toLowerCase().includes(keyword)
  )).slice(0, 20);
});

const emit = defineEmits([
  "open-organization-action",
  "open-department-sibling-picker",
  "open-department-level-picker",
  "select-department-from-picker",
  "update-include-sub-departments",
  "update-department-keyword",
  "open-employee-action",
]);
</script>

<template>
  <div class="space-y-2.5">
    <section class="mobile-panel p-4">
      <div class="flex items-center justify-between gap-3">
        <div>
          <div class="text-base font-semibold text-slate-900">钉钉组织架构</div>
        </div>
        <button
          v-if="canManageEmployeeAccountStatus"
          class="mobile-primary-button inline-flex items-center gap-1 px-3 py-2 text-xs"
          :disabled="Boolean(organizationActionRunning)"
          @click="emit('open-organization-action')"
        >
          操作
        </button>
      </div>

      <div class="mt-3 space-y-2">
        <div class="mobile-field-card flex h-10 items-center gap-2 px-3">
          <Search class="h-4 w-4 shrink-0 text-slate-400" />
          <input
            v-model.trim="departmentSearchKeyword"
            type="search"
            placeholder="搜索部门"
            class="min-w-0 flex-1 bg-transparent text-sm outline-none"
          />
        </div>
        <div v-if="departmentSearchKeyword" class="mobile-field-card px-3 py-2.5">
          <div v-if="departmentSearchResults.length" class="flex flex-wrap gap-2">
            <button
              v-for="department in departmentSearchResults"
              :key="`search-${department.deptId}`"
              class="mobile-dept-option"
              @click="emit('select-department-from-picker', department.deptId); departmentSearchKeyword = ''"
            >
              {{ department.name }}
            </button>
          </div>
          <div v-else class="py-3 text-center text-xs text-slate-400">未找到部门</div>
        </div>
        <div class="flex flex-wrap items-center gap-2 text-sm font-medium text-slate-900">
          <template v-for="(item, index) in selectedDepartmentPath" :key="item.deptId">
            <button
              class="mobile-dept-chip"
              @click="emit('open-department-sibling-picker', item.deptId)"
            >
              <span class="truncate">{{ item.name }}</span>
              <ChevronDown class="h-3.5 w-3.5 shrink-0 text-slate-400" />
            </button>
            <span v-if="index < selectedDepartmentPath.length - 1" class="text-slate-300">&gt;</span>
          </template>
          <template v-if="selectedDepartmentHasChildren">
            <span v-if="selectedDepartmentPath.length" class="text-slate-300">&gt;</span>
            <button
              class="mobile-dept-chip mobile-dept-chip-placeholder"
              @click="emit('open-department-level-picker', String(selectedDepartment?.deptId || ''))"
            >
              <span>请选择</span>
              <ChevronDown class="h-3.5 w-3.5 shrink-0 text-slate-400" />
            </button>
          </template>
        </div>
        <div v-if="departmentPickerOptions.length" class="mobile-field-card px-3 py-2.5">
          <div class="mb-2 text-[11px] font-semibold text-slate-500">当前级别部门</div>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="department in departmentPickerOptions"
              :key="department.deptId"
              class="mobile-dept-option"
              :class="String(department.deptId) === String(selectedDepartment?.deptId || '') ? 'mobile-dept-option-active' : ''"
              @click="emit('select-department-from-picker', department.deptId)"
            >
              {{ department.name }}
            </button>
          </div>
        </div>
      </div>
    </section>

    <section class="mobile-panel p-4">
      <div class="flex items-center justify-between gap-2">
        <div class="flex flex-wrap items-center gap-2">
          <div class="text-base font-semibold text-slate-900">{{ departmentEmployees.length }}人</div>
          <button
            type="button"
            class="mobile-toolbar-chip"
            :class="includeSubDepartments ? 'mobile-toolbar-chip-active' : 'mobile-toolbar-chip-inactive'"
            @click="emit('update-include-sub-departments', !includeSubDepartments)"
          >
            {{ includeSubDepartments ? "☑包含下级部门" : "包含下级部门" }}
          </button>
        </div>
        <div class="mobile-field-card flex h-[34px] w-32 shrink-0 items-center gap-2 px-2.5 py-1">
          <div class="flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-blue-50 text-blue-700">
            <Search class="h-4 w-4" />
          </div>
          <input
            :value="departmentKeyword"
            type="text"
            placeholder=""
            class="w-full bg-transparent text-sm font-medium text-slate-900 outline-none placeholder:text-slate-400"
            @input="emit('update-department-keyword', $event.target.value.trim())"
          />
        </div>
      </div>

      <div v-if="loadingDepartment" class="py-10 text-center text-sm text-slate-400">加载中...</div>
      <div v-else-if="!sortedDepartmentEmployees.length" class="py-10 text-center text-sm text-slate-400">暂无成员</div>
      <div v-else class="mt-3 space-y-2.5">
        <div
          v-for="employee in sortedDepartmentEmployees"
          :key="employee.userId"
          class="mobile-list-card p-4"
          :class="employee.accountStatus === '启用' ? 'mobile-list-card-active' : 'mobile-list-card-disabled'"
        >
          <div class="flex items-start gap-3">
            <div class="flex min-w-0 flex-1 items-start gap-3">
              <div class="relative shrink-0">
              <div
                  class="flex h-10 w-10 items-center justify-center overflow-hidden rounded-lg bg-slate-900 text-sm font-semibold text-white"
                  :class="selectedManager?.userId === employee.userId ? 'mobile-manager-avatar' : ''"
                >
                  <img
                    v-if="employee.avatarUrl"
                    :src="employee.avatarUrl"
                    :alt="employee.name"
                    class="h-full w-full object-cover"
                    loading="lazy"
                    decoding="async"
                    referrerpolicy="no-referrer"
                  />
                  <span v-else>{{ employee.name?.slice(0, 1) || "?" }}</span>
                </div>
                <div
                  v-if="selectedManager?.userId === employee.userId"
                  class="mobile-manager-badge"
                >
                  <Crown class="h-3 w-3" />
                </div>
              </div>
              <div class="min-w-0 flex-1">
                <div class="truncate text-[13px] font-semibold text-slate-900">
                  {{ employee.name }}<span class="ml-1 font-normal text-slate-500">（{{ employee.userId }}）</span>
                </div>
                <div class="mt-1.5 text-xs text-slate-500">{{ primaryDepartmentName(employee) }}</div>
              </div>
            </div>
            <button
              v-if="canOperateDepartmentEmployee"
              class="mobile-secondary-button shrink-0 rounded-lg px-3 py-1.5 text-xs font-medium"
              :disabled="accountStatusSavingUserId === employee.userId || proxyActionUserId === employee.userId"
              @click="emit('open-employee-action', employee)"
            >
              {{ accountStatusSavingUserId === employee.userId || proxyActionUserId === employee.userId ? "处理中..." : "操作" }}
            </button>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>
