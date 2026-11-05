<script setup>
defineOptions({ name: "SettingsDepartmentTreeNodePhone" });

const props = defineProps({
  nodes: {
    type: Array,
    default: () => [],
  },
  selectedDeptId: {
    type: Number,
    default: null,
  },
  expandedDeptIds: {
    type: Array,
    default: () => [],
  },
});

const emit = defineEmits(["select", "toggle"]);

function isExpanded(deptId) {
  return props.expandedDeptIds.includes(deptId);
}
</script>

<template>
  <ul class="space-y-1">
    <li v-for="node in nodes" :key="node.deptId">
      <button
        class="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm transition"
        :class="
          selectedDeptId === node.deptId
            ? 'bg-sky-50 text-sky-700'
            : 'text-slate-700 hover:bg-slate-100'
        "
        @click="emit('select', node)"
      >
        <span
          class="inline-flex h-5 w-5 items-center justify-center rounded-md border border-slate-200 bg-white text-slate-500"
          @click.stop="emit('toggle', node.deptId)"
        >
          <span v-if="node.children?.length">{{ isExpanded(node.deptId) ? "−" : "+" }}</span>
          <span v-else class="text-[10px]">•</span>
        </span>
        <span class="truncate">{{ node.name }}</span>
      </button>

      <div v-if="node.children?.length && isExpanded(node.deptId)" class="ml-4 border-l border-slate-200 pl-3">
        <SettingsDepartmentTreeNodePhone
          :nodes="node.children"
          :selected-dept-id="selectedDeptId"
          :expanded-dept-ids="expandedDeptIds"
          @select="emit('select', $event)"
          @toggle="emit('toggle', $event)"
        />
      </div>
    </li>
  </ul>
</template>
