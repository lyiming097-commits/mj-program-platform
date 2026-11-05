<script setup>
import PersonnelSelectButton from "@/components/PersonnelSelectButton.vue";

defineProps({ rows: { type: Array, required: true } });
const emit = defineEmits(["select", "change", "commit"]);

function updateNote(row, userId, note) {
  emit("change", row.nodeKey, row.members.map(member => member.userId === userId ? { ...member, note } : member));
}
</script>

<template>
  <div class="as-presales-assignees" role="group" aria-label="项目人员与工作说明">
    <div class="as-presales-assignee-head" aria-hidden="true"><span>执行节点</span><span>钉钉项目人员</span><span>管理端工作说明</span></div>
    <div v-for="row in rows" :key="row.nodeKey" class="as-presales-assignee" role="group" :aria-label="`${row.name}项目人员`">
      <div class="as-presales-assignee-node"><span class="as-presales-mobile-label">执行节点</span><strong>{{ row.name }}</strong></div>
      <div class="as-presales-assignee-people">
        <div v-for="member in row.members.length ? row.members : [{ userId: '', name: '', note: '' }]" :key="member.userId" class="as-presales-personnel-row">
          <div class="as-presales-assignee-member"><span class="as-presales-mobile-label">钉钉项目人员</span><PersonnelSelectButton :name="member.name" :detail="member.userId ? '钉钉组织人员' : '未配置人员'" :label="`${row.name}项目人员`" :disabled="row.disabled" @select="emit('select', row.nodeKey)" /></div>
          <label class="as-presales-assignee-remark"><span>管理端工作说明</span><input :value="member.note" :disabled="row.disabled || !member.userId" :aria-label="`${row.name}${member.name || '未选人员'}的工作说明`" :placeholder="member.userId ? '填写该人员的工作说明' : '请先选择项目人员'" @input="updateNote(row, member.userId, $event.target.value)" @blur="emit('commit')"></label>
        </div>
      </div>
    </div>
  </div>
</template>
