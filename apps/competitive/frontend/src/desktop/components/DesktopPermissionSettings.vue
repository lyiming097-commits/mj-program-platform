<script setup>
import { backdropDismiss as vBackdropDismiss } from "@platform-ui/backdrop-dismiss.js";
import {
  Building2,
  ChevronDown,
  ChevronRight,
  LoaderCircle,
  Plus,
  Search,
  ShieldCheck,
  UserMinus,
  UserRound,
  UsersRound,
  X,
} from "lucide-vue-next";
import { watch } from "vue";

import {
  permissionGroups,
  usePermissionSettings,
} from "@/composables/usePermissionSettings";

const emit = defineEmits(["notify", "dirty-change"]);
const state = usePermissionSettings({ notify: (message) => emit("notify", message) });

function sourceRows(type) {
  return state.activeSources.value.filter((rule) => type === "department"
    ? ["department", "departmentSub"].includes(rule.scopeType)
    : rule.scopeType === "employee");
}

function departmentRule(department) {
  return state.activeRules.value.find((rule) =>
    rule.targetId === String(department.deptId)
    && ["department", "departmentSub"].includes(rule.scopeType));
}

function employeeSelected(employee) {
  return state.activeRules.value.some((rule) =>
    rule.scopeType === "employee" && rule.targetId === String(employee.userId));
}

watch(state.dirty, (value) => emit("dirty-change", value), { immediate: true });
</script>

<template>
  <div class="permission-settings">
    <div v-if="state.error.value" class="message error">{{ state.error.value }}</div>
    <div v-if="!state.directory.value.available && state.directory.value.message" class="message warning">
      {{ state.directory.value.message }}
    </div>
    <div v-if="state.loading.value" class="loading-state"><LoaderCircle class="spin" :size="18" />正在加载权限配置...</div>

    <div v-else class="permission-grid">
      <aside class="permission-list">
        <header><ShieldCheck :size="16" /><strong>权限项</strong></header>
        <button
          v-for="group in permissionGroups"
          :key="group.id"
          type="button"
          :class="{ active: state.activePermission.value === group.id }"
          @click="state.activePermission.value = group.id"
        >
          <span class="role-icon"><UsersRound :size="16" /></span>
          <span class="role-copy">
            <b>{{ group.label }}</b>
            <small>{{ group.note }}</small>
            <span class="role-metrics">
              <span>{{ state.roleSummaries.value[group.id].memberCount }} 人</span>
              <span>{{ state.roleSummaries.value[group.id].sourceCount }} 来源</span>
              <span v-if="state.roleSummaries.value[group.id].excludedCount">{{ state.roleSummaries.value[group.id].excludedCount }} 排除</span>
            </span>
          </span>
        </button>
      </aside>

      <section class="permission-detail">
        <header class="detail-head">
          <div><h2>{{ permissionGroups.find((item) => item.id === state.activePermission.value)?.label }}</h2><p>{{ state.activeMembers.value.filter((item) => !item.excluded).length }} 人有效 · {{ state.activeMembers.value.filter((item) => item.excluded).length }} 人已排除</p></div>
          <span>{{ state.saving.value ? '正在保存...' : `${state.activeSources.value.length} 个来源` }}</span>
        </header>

        <div class="source-grid">
          <section v-for="type in ['department', 'employee']" :key="type" class="source-panel">
            <header>
              <span><Building2 v-if="type === 'department'" :size="15" /><UserRound v-else :size="15" />{{ type === 'department' ? '部门' : '人员' }}</span>
              <button type="button" :disabled="!state.directory.value.available" @click="state.openPicker(type)"><Plus :size="13" />添加</button>
            </header>
            <div class="source-tags">
              <span v-for="rule in sourceRows(type)" :key="`${rule.scopeType}:${rule.targetId}`" class="source-tag">
                <span>{{ rule.targetName || rule.targetId }}</span><em v-if="rule.scopeType === 'departmentSub'">含下级</em>
                <button type="button" :aria-label="`移除${rule.targetName || rule.targetId}`" @click="state.removeRule(rule)"><X :size="12" /></button>
              </span>
              <small v-if="!sourceRows(type).length">未添加{{ type === 'department' ? '部门' : '人员' }}</small>
            </div>
          </section>
        </div>

        <div class="member-table-wrap">
          <table v-if="state.activeMembers.value.length" class="member-table">
            <thead><tr><th>姓名</th><th>所在部门</th><th>权限来源</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="row in state.activeMembers.value" :key="row.employee.userId" :class="{ excluded: row.excluded }">
                <td><div class="employee"><span class="avatar"><img v-if="row.employee.avatarUrl" :src="row.employee.avatarUrl" :alt="row.employee.name" referrerpolicy="no-referrer" /><template v-else>{{ row.employee.name.slice(0, 1) }}</template></span><strong>{{ row.employee.name }}</strong></div></td>
                <td>{{ state.employeeDepartmentText(row.employee) }}</td><td>{{ row.sourceText }}</td>
                <td><span class="member-status" :class="{ excluded: row.excluded }">{{ row.excluded ? '已排除' : '有效' }}</span></td>
                <td><button v-if="row.excluded" type="button" class="text-action" @click="state.restoreMember(row)">恢复</button><button v-else type="button" class="text-action exclude" @click="state.excludeMember(row)"><UserMinus :size="13" />排除</button></td>
              </tr>
            </tbody>
          </table>
          <div v-else class="empty-state">暂无权限成员</div>
        </div>
      </section>
    </div>

    <Teleport to="body">
      <Transition name="picker">
        <div v-if="state.picker.value" class="picker-layer" v-backdrop-dismiss="state.closePicker">
          <section class="picker-panel" role="dialog" aria-modal="true">
            <header><h3>添加{{ state.picker.value === 'department' ? '部门' : '人员' }}</h3><button type="button" aria-label="关闭选择器" @click="state.closePicker"><X :size="17" /></button></header>
            <div class="picker-search"><label><Search :size="15" /><input v-model="state.keyword.value" :placeholder="state.picker.value === 'department' ? '搜索部门名称、编号或首字母' : '搜索姓名、工号或首字母'" /></label></div>
            <div class="picker-list">
              <template v-if="state.picker.value === 'department'">
                <div v-for="row in state.visibleDepartmentRows.value" :key="row.department.deptId" class="department-row" :style="{ paddingLeft: `${10 + row.depth * 20}px` }">
                  <button v-if="row.department.children?.length" type="button" class="tree-toggle" :aria-label="state.isDepartmentExpanded(row.department) ? '收起部门' : '展开部门'" @click="state.toggleDepartmentExpanded(row.department)"><ChevronDown v-if="state.isDepartmentExpanded(row.department)" :size="14" /><ChevronRight v-else :size="14" /></button><span v-else class="tree-spacer" />
                  <input type="checkbox" :checked="Boolean(departmentRule(row.department) || state.inheritedDepartmentRules.value.get(String(row.department.deptId)))" :disabled="Boolean(state.inheritedDepartmentRules.value.get(String(row.department.deptId)) && !departmentRule(row.department))" @change="state.toggleDepartment(row.department)" />
                  <Building2 :size="15" class="row-icon" /><div class="row-copy"><b>{{ row.department.name }}</b><small>{{ row.department.departmentPathText || `部门编号 ${row.department.deptId}` }}</small></div>
                  <label v-if="departmentRule(row.department)" class="include-children"><input type="checkbox" :checked="departmentRule(row.department).scopeType === 'departmentSub'" @change="state.setDepartmentDescendants(row.department, $event.target.checked)" />含下级</label>
                </div>
                <div v-if="!state.visibleDepartmentRows.value.length" class="empty-state">没有匹配结果</div>
              </template>
              <template v-else>
                <label v-for="employee in state.filteredEmployees.value" :key="employee.userId" class="employee-row"><input type="checkbox" :checked="employeeSelected(employee)" @change="state.toggleEmployee(employee)" /><span class="avatar"><img v-if="employee.avatarUrl" :src="employee.avatarUrl" :alt="employee.name" referrerpolicy="no-referrer" /><template v-else>{{ employee.name.slice(0, 1) }}</template></span><span class="row-copy"><b>{{ employee.name }}</b><small>{{ state.employeeDepartmentText(employee) }} · {{ employee.userId }}</small></span></label>
                <div v-if="!state.filteredEmployees.value.length" class="empty-state">没有匹配结果</div>
              </template>
            </div>
            <footer><button type="button" class="btn btn-primary" @click="state.closePicker">完成</button></footer>
          </section>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.permission-settings { height: 100%; min-height: 0; }.message { margin-bottom: 10px; border: 1px solid; border-radius: 6px; padding: 10px 12px; font-size: 11px; }.message.error { border-color: #fecdd3; background: #fff1f2; color: #be123c; }.message.warning { border-color: #fde68a; background: #fffbeb; color: #92400e; }
.loading-state { display: flex; min-height: 360px; align-items: center; justify-content: center; gap: 8px; border: 1px solid #dfe6ee; border-radius: 8px; background: #fff; color: #64748b; font-size: 12px; }.spin { animation: spin .8s linear infinite; }@keyframes spin { to { transform: rotate(360deg); } }
.permission-grid { display: grid; height: 100%; min-height: 0; grid-template-columns: 280px minmax(0, 1fr); gap: 14px; }.permission-list, .permission-detail { overflow: hidden; border: 1px solid #dfe6ee; border-radius: 8px; background: #fff; }
.permission-list > header { display: flex; height: 47px; align-items: center; gap: 8px; border-bottom: 1px solid #edf1f5; padding: 0 14px; font-size: 12px; }.permission-list > header svg { color: #2563eb; }
.permission-list > button { display: flex; width: calc(100% - 16px); align-items: flex-start; gap: 10px; margin: 8px; border: 1px solid transparent; border-radius: 6px; background: transparent; padding: 11px; color: #475569; text-align: left; }.permission-list > button.active { border-color: #bfdbfe; background: #eff6ff; }.role-icon { display: grid; width: 32px; height: 32px; flex: 0 0 auto; place-items: center; border-radius: 6px; background: #f1f5f9; color: #64748b; }.permission-list > button.active .role-icon { background: #2563eb; color: #fff; }.role-copy { min-width: 0; }.role-copy b, .role-copy small { display: block; }.role-copy b { color: #0f172a; font-size: 12px; }.role-copy small { margin-top: 4px; color: #64748b; font-size: 10px; line-height: 1.5; }.role-metrics { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 7px; color: #94a3b8; font-size: 9px; }
.permission-detail { display: flex; min-width: 0; flex-direction: column; }.detail-head { display: flex; min-height: 59px; align-items: center; justify-content: space-between; gap: 10px; border-bottom: 1px solid #edf1f5; padding: 9px 14px; }.detail-head h2 { margin: 0; font-size: 14px; }.detail-head p { margin: 4px 0 0; color: #64748b; font-size: 10px; }.detail-head > span { border-radius: 5px; background: #f1f5f9; padding: 5px 8px; color: #64748b; font-size: 9px; }
.source-grid { display: grid; grid-template-columns: 1fr 1fr; border-bottom: 1px solid #edf1f5; }.source-panel { min-width: 0; padding: 13px; }.source-panel + .source-panel { border-left: 1px solid #edf1f5; }.source-panel > header { display: flex; align-items: center; justify-content: space-between; }.source-panel > header > span { display: flex; align-items: center; gap: 6px; color: #334155; font-size: 11px; font-weight: 700; }.source-panel > header button { display: inline-flex; height: 27px; align-items: center; gap: 4px; border: 0; border-radius: 5px; background: #2563eb; padding: 0 9px; color: #fff; font-size: 9px; font-weight: 700; }.source-panel > header button:disabled { background: #cbd5e1; }.source-tags { display: flex; min-height: 37px; flex-wrap: wrap; gap: 6px; margin-top: 9px; }.source-tags > small { align-self: center; color: #94a3b8; font-size: 9px; }.source-tag { display: inline-flex; max-width: 100%; height: 29px; align-items: center; gap: 6px; border: 1px solid #dfe6ee; border-radius: 5px; background: #f8fafc; padding: 0 7px; color: #475569; font-size: 10px; }.source-tag > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.source-tag em { border-radius: 3px; background: #fef3c7; padding: 2px 4px; color: #a16207; font-size: 8px; font-style: normal; font-weight: 700; }.source-tag button { display: grid; flex: 0 0 auto; place-items: center; border: 0; background: transparent; padding: 0; color: #94a3b8; }
.member-table-wrap { min-height: 0; flex: 1; overflow: auto; }.member-table { width: 100%; min-width: 720px; border-collapse: collapse; font-size: 10px; }.member-table th { position: sticky; z-index: 1; top: 0; height: 36px; border-bottom: 1px solid #dfe6ee; background: #f8fafc; padding: 0 12px; color: #64748b; text-align: left; }.member-table td { border-bottom: 1px solid #edf1f5; padding: 9px 12px; color: #64748b; }.member-table tr.excluded { background: #f8fafc; color: #94a3b8; }.employee { display: flex; align-items: center; gap: 9px; }.avatar { display: grid; width: 30px; height: 30px; flex: 0 0 auto; place-items: center; overflow: hidden; border-radius: 5px; background: #eff6ff; color: #1d4ed8; font-size: 10px; font-weight: 800; }.avatar img { width: 100%; height: 100%; object-fit: cover; }.employee strong { color: #1e293b; }.excluded .employee strong { color: #94a3b8; text-decoration: line-through; }.member-status { border-radius: 4px; background: #ecfdf5; padding: 4px 7px; color: #047857; font-size: 9px; font-weight: 700; }.member-status.excluded { background: #e2e8f0; color: #64748b; }.text-action { display: inline-flex; align-items: center; gap: 3px; border: 0; background: transparent; padding: 0; color: #2563eb; font-size: 10px; }.text-action.exclude { color: #64748b; }
.picker-layer { position: fixed; inset: 0; z-index: 110; display: grid; place-items: center; background: rgba(15, 23, 42, .36); padding: 16px; }.picker-panel { display: flex; width: min(680px, calc(100vw - 32px)); max-height: min(680px, calc(100dvh - 32px)); flex-direction: column; overflow: hidden; border-radius: 8px; background: #fff; box-shadow: 0 24px 64px rgba(15, 23, 42, .24); }.picker-panel > header { display: flex; min-height: 52px; align-items: center; justify-content: space-between; border-bottom: 1px solid #edf1f5; padding: 0 15px; }.picker-panel h3 { margin: 0; font-size: 13px; }.picker-panel > header button { display: grid; width: 30px; height: 30px; place-items: center; border: 0; border-radius: 5px; background: transparent; color: #64748b; }.picker-search { border-bottom: 1px solid #edf1f5; padding: 12px 14px; }.picker-search label { display: flex; height: 38px; align-items: center; gap: 8px; border: 1px solid #d9e1ea; border-radius: 6px; padding: 0 10px; color: #94a3b8; }.picker-search input { min-width: 0; flex: 1; border: 0; outline: 0; font-size: 12px; }.picker-list { min-height: 0; flex: 1; overflow-y: auto; padding: 7px; }.department-row, .employee-row { display: flex; min-height: 49px; align-items: center; gap: 8px; border-radius: 6px; padding: 5px 9px; }.department-row:hover, .employee-row:hover { background: #f8fafc; }.tree-toggle { display: grid; width: 22px; height: 22px; flex: 0 0 auto; place-items: center; border: 0; background: transparent; padding: 0; color: #64748b; }.tree-spacer { width: 22px; flex: 0 0 auto; }.row-icon { flex: 0 0 auto; color: #94a3b8; }.row-copy { min-width: 0; flex: 1; }.row-copy b, .row-copy small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.row-copy b { color: #334155; font-size: 11px; }.row-copy small { margin-top: 3px; color: #94a3b8; font-size: 9px; }.include-children { display: flex; flex: 0 0 auto; align-items: center; gap: 5px; color: #64748b; font-size: 9px; }.employee-row { cursor: pointer; }.picker-panel > footer { display: flex; justify-content: flex-end; border-top: 1px solid #edf1f5; padding: 10px 14px; }.picker-enter-active, .picker-leave-active { transition: opacity .16s ease; }.picker-enter-from, .picker-leave-to { opacity: 0; }
</style>
