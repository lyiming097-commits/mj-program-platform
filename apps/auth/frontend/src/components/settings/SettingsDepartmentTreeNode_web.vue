<script setup>
import { nextTick } from "vue";
import { Building2, ChevronDown, ChevronRight } from "@lucide/vue";

defineOptions({ name: "SettingsDepartmentTreeNodeWeb" });

const props = defineProps({
  nodes: {
    type: Array,
    default: () => [],
  },
  selectedDeptId: {
    type: [Number, String],
    default: null,
  },
  expandedDeptIds: {
    type: Array,
    default: () => [],
  },
  enabledDepartmentIds: {
    type: Array,
    default: () => [],
  },
  canManageEnabledDepartments: Boolean,
  editingEnabledDepartments: Boolean,
  enabledDepartmentsBusy: Boolean,
  depth: {
    type: Number,
    default: 0,
  },
});

const emit = defineEmits(["select", "toggle", "update-enabled"]);

function isExpanded(deptId) {
  return props.expandedDeptIds.includes(deptId);
}

function isEnabled(deptId) {
  const normalizedDeptId = String(deptId ?? "").trim();
  return props.enabledDepartmentIds.some((item) => String(item ?? "").trim() === normalizedDeptId);
}
async function handleDepartmentKey(event, node) {
  if (!["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault(); event.stopPropagation();
  const button = event.currentTarget;
  const tree = button.closest('[role="tree"]');
  const buttons = [...tree.querySelectorAll('[data-department-name]')];
  const index = buttons.indexOf(button);
  if (event.key === "ArrowDown") buttons[Math.min(index + 1, buttons.length - 1)]?.focus();
  if (event.key === "ArrowUp") buttons[Math.max(index - 1, 0)]?.focus();
  if (event.key === "Home") buttons[0]?.focus();
  if (event.key === "End") buttons.at(-1)?.focus();
  if (event.key === "ArrowRight" && node.children?.length) {
    if (!isExpanded(node.deptId)) { emit("toggle", node.deptId); await nextTick(); }
    else buttons[index + 1]?.focus();
  }
  if (event.key === "ArrowLeft") {
    if (node.children?.length && isExpanded(node.deptId)) emit("toggle", node.deptId);
    else button.closest('[role="treeitem"]')?.parentElement?.closest('[role="treeitem"]')?.querySelector('[data-department-name]')?.focus();
  }
}

</script>

<template>
  <ul :role="depth === 0 ? 'tree' : 'group'" :aria-label="depth === 0 ? '部门列表' : undefined">
    <li
      v-for="node in nodes"
      :key="node.deptId"
      role="treeitem"
      :aria-selected="selectedDeptId === node.deptId"
      :aria-expanded="node.children?.length ? isExpanded(node.deptId) : undefined"
    >
      <div
        class="department-tree-row group grid min-h-11 w-full items-center gap-1.5 border-b border-slate-200 pr-2 text-left text-sm transition-colors"
        :class="[
          editingEnabledDepartments
            ? 'grid-cols-[24px_28px_minmax(0,1fr)_32px]'
            : 'grid-cols-[28px_minmax(0,1fr)_32px]',
          selectedDeptId === node.deptId
            ? 'bg-blue-50 text-blue-700'
            : 'bg-white text-slate-700 hover:bg-slate-50',
        ]"
        :style="{ paddingLeft: `${8 + depth * 18}px` }"
      >
        <input
          v-if="editingEnabledDepartments"
          type="checkbox"
          class="h-4 w-4 justify-self-center accent-blue-600"
          :checked="isEnabled(node.deptId)"
          :disabled="!canManageEnabledDepartments || enabledDepartmentsBusy"
          :aria-label="`${isEnabled(node.deptId) ? '停用' : '启用'}${node.name}`"
          @change="emit('update-enabled', { department: node, checked: $event.target.checked })"
        />
        <span
          class="department-tree-icon inline-flex h-7 w-7 items-center justify-center rounded-md transition-colors"
          :class="selectedDeptId === node.deptId
            ? 'bg-blue-100 text-blue-700'
            : 'bg-slate-100 text-slate-500 group-hover:bg-slate-200 group-hover:text-slate-700'"
          aria-hidden="true"
        >
          <Building2 class="h-3.5 w-3.5" />
        </span>
        <button
          type="button"
          class="h-full min-w-0 truncate rounded-sm text-left font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-inset"
          data-department-name
          @keydown="handleDepartmentKey($event, node)"
          :title="[node.pathText || node.name, node.parentDisabled ? '上级部门未启用' : ''].filter(Boolean).join(' · ')"
          :aria-current="selectedDeptId === node.deptId ? 'true' : undefined"
          @click="emit('select', node)"
        ><span class="block truncate">{{ node.name }}</span><span v-if="node.parentDisabled && !editingEnabledDepartments" class="block truncate text-xs font-normal text-amber-700">上级部门未启用</span></button>
        <button
          v-if="node.children?.length"
          type="button"
          class="inline-flex h-8 w-8 items-center justify-center rounded-md text-slate-400 transition hover:bg-white hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          :aria-label="`${isExpanded(node.deptId) ? '收起' : '展开'}${node.name}`"
          @click="emit('toggle', node.deptId)"
        >
          <ChevronDown v-if="isExpanded(node.deptId)" class="h-4 w-4" aria-hidden="true" />
          <ChevronRight v-else class="h-4 w-4" aria-hidden="true" />
        </button>
        <span v-else class="h-8 w-8" aria-hidden="true"></span>
      </div>

      <SettingsDepartmentTreeNodeWeb
        v-if="node.children?.length && isExpanded(node.deptId)"
        :nodes="node.children"
        :selected-dept-id="selectedDeptId"
        :expanded-dept-ids="expandedDeptIds"
        :enabled-department-ids="enabledDepartmentIds"
        :can-manage-enabled-departments="canManageEnabledDepartments"
        :editing-enabled-departments="editingEnabledDepartments"
        :enabled-departments-busy="enabledDepartmentsBusy"
        :depth="depth + 1"
        @select="emit('select', $event)"
        @toggle="emit('toggle', $event)"
        @update-enabled="emit('update-enabled', $event)"
      />
    </li>
  </ul>
</template>
