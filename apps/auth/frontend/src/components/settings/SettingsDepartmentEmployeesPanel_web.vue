<script setup>
import { computed, ref } from "vue";
import { Crown, Search, Settings2 } from "@lucide/vue";
const props = defineProps({
  selectedDepartmentName: { type: String, required: true },
  departmentEmployees: { type: Array, required: true },
  selectedManager: { type: Object, default: null },
  managers: { type: Array, default: () => [] },
  departmentPath: { type: Array, default: () => [] },
  directEmployeeCount: { type: Number, default: null },
  subtreeEmployeeCount: { type: Number, default: null },
  includeSubDepartments: Boolean,
  departmentKeyword: { type: String, default: "" },
  loadingDepartment: Boolean,
  errorMessage: { type: String, default: "" },
  sortedDepartmentEmployees: { type: Array, required: true },
  canOperateDepartmentEmployee: Boolean,
  accountStatusSavingUserId: { type: String, default: "" },
  proxyActionUserId: { type: String, default: "" },
  primaryDepartmentName: { type: Function, required: true },
  showOrganizationAction: Boolean,
  organizationActionRunning: { type: String, default: "" },
  organizationSettingsSaving: Boolean,
});
const emit = defineEmits([
  "update-include-sub-departments",
  "update-department-keyword",
  "select-department",
  "open-employee-action",
  "retry",
  "open-organization-action",
]);
const brokenAvatars = ref(new Set());
const managerIds = computed(
  () => new Set(props.managers.map((item) => item.userId)),
);
function scrollTable(event) {
  if (
    event.target !== event.currentTarget ||
    !["ArrowLeft", "ArrowRight"].includes(event.key)
  )
    return;
  event.preventDefault();
  event.currentTarget.scrollLeft += event.key === "ArrowRight" ? 120 : -120;
}
</script>
<template>
  <section
    class="department-members-panel flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-lg border border-slate-200 bg-white"
    role="region"
    :aria-label="`${selectedDepartmentName}人员`"
  >
    <header class="shrink-0 space-y-3 border-b border-slate-200 p-3">
      <div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <h3 class="min-w-0 break-words text-lg font-semibold leading-7 text-slate-900">
          {{ selectedDepartmentName }}
        </h3>
        <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
          <span>本部门 {{ directEmployeeCount ?? "—" }} 人 · 含下级 {{ subtreeEmployeeCount ?? "—" }} 人</span>
          <span role="status">{{ loadingDepartment ? "正在加载" : `当前匹配 ${departmentEmployees.length} 人` }}</span>
          <details v-if="managers.length" class="text-amber-700">
            <summary class="flex cursor-pointer items-center gap-1">
              <Crown class="h-3.5 w-3.5" aria-hidden="true" />主管 {{ managers.length }} 人
            </summary>
            <ul class="mt-1 flex flex-wrap gap-2">
              <li v-for="manager in managers" :key="manager.userId" :title="manager.userId">{{ manager.name }}</li>
            </ul>
          </details>
        </div>
      </div>
      <div class="department-member-toolbar flex min-w-0 items-center gap-3">
        <nav v-if="departmentPath.length" class="department-member-path flex min-w-0 items-center gap-1 overflow-hidden text-xs text-slate-500" aria-label="部门路径" :title="departmentPath.map(department => department.name).join(' / ')">
          <template v-for="(department, index) in departmentPath" :key="department.deptId">
            <span v-if="index" class="shrink-0" aria-hidden="true">/</span>
            <button type="button" class="min-w-0 truncate hover:enabled:text-blue-600 disabled:cursor-default"
              :disabled="department.selectable === false" :title="department.name"
              :aria-label="`查看${department.name}部门`" :aria-current="index === departmentPath.length - 1 ? 'location' : undefined"
              @click="emit('select-department', department)">{{ department.name }}</button>
          </template>
        </nav>
        <div class="department-member-actions ml-auto flex items-center justify-end gap-2">
          <label class="flex shrink-0 items-center gap-1.5 whitespace-nowrap text-xs text-slate-500">
            <input :checked="includeSubDepartments" type="checkbox" class="accent-blue-600" @change="emit('update-include-sub-departments', $event.target.checked)" />包含下级部门
          </label>
          <label class="department-member-search flex h-8 items-center gap-2 rounded-lg border border-slate-200 px-2">
            <Search class="h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden="true" />
            <input :value="departmentKeyword" type="search" aria-label="搜索部门成员姓名、ID或拼音" placeholder="姓名、ID或拼音"
              class="min-w-0 flex-1 text-sm outline-none" @input="emit('update-department-keyword', $event.target.value)" />
          </label>
          <button v-if="showOrganizationAction" type="button" class="org-button shrink-0"
            :disabled="Boolean(organizationActionRunning) || organizationSettingsSaving" @click="emit('open-organization-action')">
            <Settings2 class="h-3.5 w-3.5" aria-hidden="true" />操作
          </button>
        </div>
      </div>
    </header>
    <div
      v-if="loadingDepartment"
      class="p-10 text-center text-sm text-slate-500"
      role="status"
    >
      正在加载人员
    </div>
    <div v-else-if="errorMessage" class="p-8 text-center" role="alert">
      <p class="text-sm text-red-700">{{ errorMessage }}</p>
      <button type="button" class="org-button mt-3" @click="emit('retry')">
        重新加载
      </button>
    </div>
    <p
      v-else-if="!sortedDepartmentEmployees.length"
      class="p-10 text-center text-sm text-slate-500"
    >
      {{ departmentKeyword ? "未找到匹配成员，请调整搜索条件" : "暂无成员" }}
    </p>
    <div
      v-else
      class="min-h-0 flex-1 overflow-auto overscroll-contain"
      role="region"
      aria-label="成员表格，可使用方向键横向浏览"
      tabindex="0"
      @keydown="scrollTable"
    >
      <table class="org-table" aria-label="组织成员">
        <thead>
          <tr>
            <th scope="col">姓名 / ID</th>
            <th scope="col">账号状态</th>
            <th scope="col">所属部门</th>
            <th v-if="canOperateDepartmentEmployee" scope="col">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="employee in sortedDepartmentEmployees"
            :key="employee.userId"
          >
            <td>
              <div class="flex items-center gap-3">
                <span class="relative shrink-0">
                  <span
                    class="org-member-avatar flex items-center justify-center overflow-hidden rounded-2xl bg-slate-100 text-sm font-semibold text-slate-600"
                    :class="managerIds.has(employee.userId) ? 'ring-2 ring-amber-400 ring-offset-2 ring-offset-white' : ''"
                  >
                    <img
                      v-if="employee.avatarUrl && !brokenAvatars.has(employee.userId)"
                      :src="employee.avatarUrl"
                      alt=""
                      class="h-full w-full object-cover"
                      loading="lazy"
                      referrerpolicy="no-referrer"
                      @error="brokenAvatars.add(employee.userId)"
                    />
                    <span v-else>{{ employee.name?.slice(0, 1) || "?" }}</span>
                  </span>
                  <span
                    v-if="managerIds.has(employee.userId)"
                    class="absolute -left-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-amber-500 text-white shadow-sm"
                    role="img"
                    :aria-label="`${employee.name}：部门主管`"
                    title="部门主管"
                  >
                    <Crown class="h-3 w-3" aria-hidden="true" />
                  </span>
                </span>
                <div class="min-w-0">
                  <div class="whitespace-nowrap font-semibold">
                    {{ employee.name }}
                  </div>
                  <div
                    class="max-w-40 truncate text-xs tabular-nums text-slate-500"
                    :title="employee.userId"
                  >
                    {{ employee.userId }}
                  </div>
                </div>
              </div>
            </td>
            <td>
              <span
                class="whitespace-nowrap rounded px-2 py-1 text-xs"
                :class="
                  employee.accountStatus === '启用'
                    ? 'bg-emerald-50 text-emerald-700'
                    : 'bg-red-50 text-red-700'
                "
                >{{ employee.accountStatus || "未记录" }}</span
              >
            </td>
            <td>
              <div
                class="min-w-32 max-w-xl break-words"
                :title="primaryDepartmentName(employee)"
              >
                {{ primaryDepartmentName(employee) }}
              </div>
            </td>
            <td v-if="canOperateDepartmentEmployee">
              <button
                type="button"
                class="org-button"
                :disabled="
                  accountStatusSavingUserId === employee.userId ||
                  proxyActionUserId === employee.userId
                "
                :aria-label="`操作${employee.name}`"
                @click="emit('open-employee-action', employee)"
              >
                操作
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.department-members-panel {
  container: department-members / inline-size;
}
.department-member-toolbar {
  --department-actions-width: 400px;
  --department-actions-min-width: 240px;
  --department-search-min-width: 64px;
  --department-path-width: 200px;
}
.department-member-path {
  flex: 1 1 var(--department-path-width);
}
.department-member-actions {
  flex: 0 1 var(--department-actions-width);
  min-width: var(--department-actions-min-width);
}
.department-member-search {
  flex: 1 1 0;
  min-width: var(--department-search-min-width);
}
@container department-members (max-width: 480px) {
  .department-member-toolbar {
    flex-wrap: wrap;
  }
  .department-member-path {
    flex-basis: 100%;
  }
  .department-member-actions {
    flex-basis: 100%;
  }
}
</style>
