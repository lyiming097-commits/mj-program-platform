<script setup>
import { ElOption, ElSelect } from "element-plus/es/components/select/index.mjs";
import "element-plus/es/components/select/style/css";
import PresalesProjectFees from "@/components/PresalesProjectFees.vue";
import DateField from "@/components/DateField.vue";
import PresalesRequirementDocuments from "@/components/PresalesRequirementDocuments.vue";
import { PRESALES_PROJECT_LEVELS, PRESALES_PROJECT_URGENCIES } from "@/presalesProjectInfo";

defineProps({
  values: { type: Object, required: true },
  editable: Boolean,
  errors: { type: Object, required: true },
  projectId: { type: [String, Number], default: "" },
  sourceCrmId: { type: [String, Number], default: "" },
  identityKey: { type: String, default: "" },
});
defineEmits(["change", "documents-busy-change"]);
const fields = { totalArea: "项目总面积", designArea: "设计面积" };
</script>

<template>
  <section class="as-presales-project-info" role="tabpanel" aria-label="项目信息">
    <PresalesProjectFees :source-crm-id="sourceCrmId" :identity-key="identityKey" embedded />
    <section class="as-panel as-project-info-metadata" aria-label="项目资料">
      <header class="as-panel-head"><h3>项目资料</h3></header>
      <div class="as-project-info-fields">
        <label v-for="(label, key) in fields" :key="key" class="as-field as-project-info-area">
          <span>{{ label }}</span>
          <div class="as-area-input"><input :value="values[key]" type="text" inputmode="decimal" :aria-label="label" :aria-invalid="Boolean(errors[key])" :aria-describedby="errors[key] ? `as-area-error-${key}` : undefined" :readonly="!editable" placeholder="未填写" @input="$emit('change', key, $event.target.value)"><span aria-hidden="true">㎡</span></div>
          <small v-if="errors[key]" :id="`as-area-error-${key}`" class="as-area-error" role="alert">{{ errors[key] }}</small>
        </label>
        <label class="as-field">
          <span>项目等级</span>
          <ElSelect :model-value="values.projectLevel" class="as-searchable-select" popper-class="as-searchable-select-popper as-project-level-popper" clearable value-on-clear="" placeholder="请选择项目等级" aria-label="项目等级" :disabled="!editable" :aria-invalid="Boolean(errors.projectLevel)" :aria-describedby="errors.projectLevel ? 'as-project-level-error' : undefined" @update:model-value="$emit('change', 'projectLevel', $event)">
            <ElOption v-for="level in PRESALES_PROJECT_LEVELS" :key="level" :label="level" :value="level" />
          </ElSelect>
          <small v-if="errors.projectLevel" id="as-project-level-error" class="as-area-error" role="alert">{{ errors.projectLevel }}</small>
        </label>
        <label class="as-field">
          <span>紧急程度</span>
          <ElSelect :model-value="values.urgency" class="as-searchable-select" popper-class="as-searchable-select-popper as-project-level-popper" clearable value-on-clear="" placeholder="请选择紧急程度" aria-label="紧急程度" :disabled="!editable" :aria-invalid="Boolean(errors.urgency)" :aria-describedby="errors.urgency ? 'as-project-urgency-error' : undefined" @update:model-value="$emit('change', 'urgency', $event)">
            <ElOption v-for="urgency in PRESALES_PROJECT_URGENCIES" :key="urgency" :label="urgency" :value="urgency" />
          </ElSelect>
          <small v-if="errors.urgency" id="as-project-urgency-error" class="as-area-error" role="alert">{{ errors.urgency }}</small>
        </label>
        <label class="as-field">
          <span>预计招标时间</span>
          <DateField :model-value="values.expectedBidAt" aria-label="预计招标时间" :disabled="!editable" :aria-invalid="Boolean(errors.expectedBidAt)" :aria-describedby="errors.expectedBidAt ? 'as-project-expected-bid-error' : undefined" @update:model-value="$emit('change', 'expectedBidAt', $event)" />
          <small v-if="errors.expectedBidAt" id="as-project-expected-bid-error" class="as-area-error" role="alert">{{ errors.expectedBidAt }}</small>
        </label>
      </div>
    </section>
    <PresalesRequirementDocuments v-if="projectId" :key="projectId" :project-id="projectId" :editable="editable" @busy-change="$emit('documents-busy-change', $event)" />
  </section>
</template>

<style scoped>
.as-presales-project-info { display: grid; min-width: 0; gap: var(--as-section-gap, 16px); }
.as-project-info-metadata { container-type: inline-size; }
.as-project-info-fields { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); align-items: start; gap: var(--as-section-gap, 16px); padding: var(--as-section-gap, 16px); }
.as-project-info-fields > .as-field { grid-column: span 2; }
.as-project-info-fields > .as-project-info-area { grid-column: span 3; }
@container (min-width: 1040px) {
  .as-project-info-fields { grid-template-columns: repeat(5, minmax(0, 1fr)); }
  .as-project-info-fields > .as-field { grid-column: auto; }
}
@container (max-width: 639px) {
  .as-project-info-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .as-project-info-fields > .as-field { grid-column: auto; }
  .as-project-info-fields > .as-field:last-child { grid-column: 1 / -1; }
}
@container (max-width: 399px) {
  .as-project-info-fields { grid-template-columns: minmax(0, 1fr); }
}
.as-area-input { position: relative; }
.as-area-input input { padding-right: 42px; font-variant-numeric: tabular-nums; }
.as-area-input > span { position: absolute; right: 12px; top: 50%; transform: translateY(-50%); color: var(--as-muted); font-size: 12px; pointer-events: none; }
.as-area-input input[readonly] { background: var(--as-soft); color: var(--as-muted); }
.as-field .as-area-error { color: var(--as-danger, #d92d20); font-size: 12px; }
:global(.as-project-level-popper .el-select-dropdown__item) { font-size: var(--el-font-size-base, 14px); }
</style>
