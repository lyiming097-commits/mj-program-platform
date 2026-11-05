<script setup>
import { shallowRef } from "vue";
import { Check, Download, ExternalLink, Search } from "lucide-vue-next";

import { useMergeWorkspace, mergeFields } from "@/composables/useMergeWorkspace";
import { useProtectedAttachments } from "@/composables/useProtectedAttachments";
import AppDrawer from "@/shared/AppDrawer.vue";
import MediaPreviewDialog from "@/shared/MediaPreviewDialog.vue";
import CompetitorVersionSelect from "@/shared/CompetitorVersionSelect.vue";
import MergeResolutionPicker from "@/shared/MergeResolutionPicker.vue";
import ParameterMergeComparison from "@/shared/ParameterMergeComparison.vue";
import UnsavedChangesDialog from "@/shared/UnsavedChangesDialog.vue";

const props = defineProps({ submission: { type: Object, default: null } });
const emit = defineEmits(["close", "merged", "notify"]);
const workspace = useMergeWorkspace(props, emit);
const discardOpen = shallowRef(false);
const { mediaPreview, downloadingId, previewAttachment, downloadAttachment } = useProtectedAttachments(
  (message) => emit("notify", message),
);
function requestClose() {
  if (workspace.submitting.value) return;
  if (workspace.dirty.value) discardOpen.value = true;
  else emit("close");
}
function discardAndClose() {
  discardOpen.value = false;
  emit("close");
}
</script>

<template>
  <AppDrawer :open="Boolean(submission)" title="归并竞品" width="1240px" @close="requestClose">
    <div v-if="submission" class="merge-workspace">
      <MergeResolutionPicker :model-value="workspace.resolutionMode.value" @update:model-value="workspace.selectResolutionMode" />
      <section class="target-section">
        <div><h3>{{ workspace.resolutionMode.value === 'newVersion' ? '选择所属竞品' : '选择归并目标' }}</h3><p>{{ workspace.resolutionMode.value === 'newVersion' ? '新版本会与该竞品的其他版本并列保存' : '仅显示同一我司产品下的竞品档案，点击一个目标后查看归并明细' }}</p></div>
        <label class="target-search"><Search :size="15" /><input v-model="workspace.query.value" class="control" :aria-label="workspace.resolutionMode.value === 'newVersion' ? '搜索所属竞品' : '搜索归并目标'" placeholder="搜索品牌、名称或型号" /></label>
        <p v-if="submission.competitorId" class="notice">该资料已关联竞品，只能更新原竞品。</p>
        <div class="target-list"><button v-for="item in workspace.visibleTargets.value" :key="item.id" type="button" class="target-card" :class="{ active: workspace.targetId.value === item.id }" :disabled="Boolean(submission.competitorId) && workspace.targetId.value !== item.id" @click="workspace.selectTarget(item.id)"><strong>{{ item.brand }} · {{ item.name }}</strong><span>{{ item.model || '型号待补充' }} · {{ item.sources }} 条来源</span></button><p v-if="!workspace.visibleTargets.value.length" class="empty-inline">当前我司产品下暂无可归并竞品</p></div>
      </section>

      <div v-if="workspace.loading.value" class="empty-state">正在加载竞品档案...</div>
      <template v-else-if="workspace.detail.value">
        <section v-if="workspace.resolutionMode.value === 'mergeExisting'" class="version-target"><div><h3>选择归并版本</h3><p>本次来源和审核结果会写入所选版本。</p></div><CompetitorVersionSelect :model-value="workspace.targetVersionId.value" :versions="workspace.detail.value.versions" :loading="workspace.loading.value" @update:model-value="workspace.selectTargetVersion" /></section>
        <section v-else class="parallel-version-note"><div><h3>独立并列版本</h3><p>地区、价格、参数和来源资料均按本次审核结果独立保存，不继承已有版本。</p></div></section>
        <section class="status-summary"><div><strong>{{ workspace.statusCounts.value.new }}</strong><span>新增</span></div><div><strong>{{ workspace.statusCounts.value.conflict }}</strong><span>冲突</span></div><div><strong>{{ workspace.statusCounts.value.same }}</strong><span>无变化</span></div></section>
        <section class="compare-section">
          <header class="compare-head"><span>字段</span><span>{{ workspace.resolutionMode.value === 'newVersion' ? '默认版本（参考）' : '所选版本' }}</span><span>新采集资料</span><span>处理方式</span><span>{{ workspace.resolutionMode.value === 'newVersion' ? '新版本资料' : '归并结果' }}</span></header>
          <article v-for="field in mergeFields" :key="field.key" class="compare-row">
            <strong>{{ field.label }} <em class="status-mark" :class="workspace.fieldStatuses.value[field.key]">{{ workspace.fieldStatuses.value[field.key] === 'new' ? '新增' : workspace.fieldStatuses.value[field.key] === 'conflict' ? '冲突' : '无变化' }}</em></strong>
            <p>{{ workspace.existing.value[field.key] || '-' }}</p>
            <p>{{ submission[field.key] || '-' }}</p>
            <div class="choice-buttons">
              <button type="button" :class="{ active: workspace.choices[field.key] === 'existing' }" @click="workspace.chooseField(field, 'existing')">{{ workspace.resolutionMode.value === 'newVersion' ? '采用参考值' : '保留已有' }}</button>
              <button type="button" :class="{ active: workspace.choices[field.key] === 'source' }" @click="workspace.chooseField(field, 'source')">采用采集值</button>
              <button v-if="field.multiline" type="button" :class="{ active: workspace.choices[field.key] === 'append' }" @click="workspace.chooseField(field, 'append')">追加内容</button>
            </div>
            <textarea v-if="field.multiline" :value="workspace.result[field.key]" class="control result-control" @input="workspace.updateResult(field.key, $event.target.value)" />
            <input v-else :value="workspace.result[field.key]" :type="field.key === 'expires' ? 'date' : 'text'" class="control result-control" @input="workspace.updateResult(field.key, $event.target.value)" />
          </article>
        </section>

        <ParameterMergeComparison
          :rows="workspace.parameterComparisons.value"
          :counts="workspace.parameterDifferenceCounts.value"
          :selected-count="workspace.selectedParameterItems.value.length"
          @select-source="workspace.setParameterSelection"
          @toggle="workspace.toggleParameter"
        />

        <section class="source-section">
          <header><Check :size="16" /><div><h3>来源资料自动加入</h3><p>这些信息不会覆盖竞品主档，会作为本次采集来源保留。</p></div></header>
          <dl><div><dt>客户</dt><dd>{{ submission.customer || '-' }}</dd></div><div><dt>具体地点</dt><dd>{{ submission.location || '-' }}</dd></div><div class="wide"><dt>一线备注</dt><dd>{{ submission.note || '-' }}</dd></div></dl>
          <div class="source-files"><article v-for="file in submission.attachments" :key="file.id"><div><b>{{ file.name }}</b><span>{{ file.category }}</span></div><button type="button" :aria-label="`查看原件：${file.name}`" aria-haspopup="dialog" @click="previewAttachment(submission.id, file)"><ExternalLink :size="14" /></button><button type="button" :aria-label="`下载：${file.name}`" :disabled="Boolean(downloadingId)" @click="downloadAttachment(submission.id, file)"><Download :size="14" /></button></article><p v-if="!submission.attachments.length">本次采集没有附件</p></div>
        </section>
      </template>
    </div>
    <template #footer><button type="button" class="btn" @click="requestClose">取消</button><button type="button" class="btn btn-primary" :disabled="workspace.loading.value || workspace.submitting.value || !workspace.targetReady.value" data-ai-action="competitive.submission.resolve" @click="workspace.submit">{{ workspace.submitting.value ? '处理中...' : workspace.resolutionMode.value === 'newVersion' ? '创建新版本' : '确认归并' }}</button></template>
  </AppDrawer>
  <MediaPreviewDialog :open="Boolean(mediaPreview)" :media="mediaPreview" @close="mediaPreview = null" @notify="emit('notify', $event)" />
  <UnsavedChangesDialog :open="discardOpen" description="当前归并设置尚未提交，退出后将不会保留。" @cancel="discardOpen = false" @confirm="discardAndClose" />
</template>

<style scoped>
.merge-workspace { display: grid; gap: 18px; }.target-section { display: grid; gap: 10px; border-bottom: 1px solid #dfe6ee; padding-bottom: 16px; }.target-section h3, .source-section h3 { margin: 0; font-size: 14px; }.target-section p, .source-section header p { margin: 4px 0 0; color: #64748b; font-size: 11px; }.notice { color: #b45309 !important; }.target-list { display: grid; max-height: 190px; grid-template-columns: 1fr; gap: 8px; overflow-y: auto; padding-right: 3px; }.target-card { display: grid; gap: 5px; border: 1px solid #dbe3ec; border-radius: 6px; background: #fff; padding: 11px 12px; text-align: left; }.target-card.active { border-color: #2563eb; background: #eff6ff; box-shadow: 0 0 0 2px #dbeafe; }.target-card:disabled { cursor: default; opacity: .6; }.target-card strong { overflow: hidden; color: #1e3a5f; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.target-card span { color: #64748b; font-size: 11px; }.status-summary { display: flex; width: fit-content; border: 1px solid #dbe3ec; border-radius: 6px; overflow: hidden; }.status-summary div { display: grid; min-width: 82px; gap: 2px; justify-items: center; border-right: 1px solid #dbe3ec; padding: 7px 12px; }.status-summary div:last-child { border-right: 0; }.status-summary strong { font-size: 15px; }.status-summary span { color: #64748b; font-size: 11px; }.status-summary div:nth-child(1) strong { color: #059669; }.status-summary div:nth-child(2) strong { color: #d97706; }.status-summary div:nth-child(3) strong { color: #64748b; }.status-mark { display: inline-block; margin-left: 4px; border: 1px solid currentColor; border-radius: 3px; padding: 1px 4px; font-size: 9px; font-style: normal; font-weight: 700; }.status-mark.new { color: #059669; }.status-mark.conflict { color: #d97706; }.status-mark.same { color: #64748b; }
.version-target{display:flex;min-height:58px;align-items:center;justify-content:space-between;gap:16px;border-block:1px solid #dfe6ee;padding:11px 0}.version-target h3{margin:0;color:#17345e;font-size:12px}.version-target p{margin:4px 0 0;color:#64748b;font-size:10px}.parallel-version-note{border-block:1px solid #bfdbfe;background:#f8fbff;padding:12px}.parallel-version-note h3{margin:0;color:#1d4ed8;font-size:12px}.parallel-version-note p{margin:4px 0 0;color:#52647a;font-size:10px}.compare-section{overflow-x:auto;border:1px solid #dfe6ee;border-radius:6px}.compare-head,.compare-row{display:grid;min-width:920px;grid-template-columns:88px minmax(135px,.85fr) minmax(135px,.85fr) 116px minmax(270px,1.6fr);gap:8px}.compare-head{border-bottom:1px solid #dfe6ee;background:#f8fafc;padding:10px;color:#64748b;font-size:10px;font-weight:700}.compare-row{align-items:start;border-bottom:1px solid #edf1f5;padding:9px 10px}.compare-row:last-child{border-bottom:0}.compare-row>strong{font-size:11px}.compare-row>p{min-height:42px;margin:0;border:1px solid #edf1f5;border-radius:5px;background:#f8fafc;padding:8px;color:#475569;font-size:10px;line-height:1.45;white-space:pre-wrap}.result-control{width:100%;min-height:42px;line-height:1.55}.compare-row textarea.result-control{min-height:86px;resize:vertical}
.choice-buttons { display: grid; gap: 4px; }.choice-buttons button { min-height: 26px; border: 1px solid #dbe3ec; border-radius: 4px; background: #fff; color: #64748b; font-size: 9px; }.choice-buttons button.active { border-color: #2563eb; background: #eff6ff; color: #1d4ed8; font-weight: 700; }
.source-section { border: 1px solid #bfdbfe; border-radius: 6px; background: #f8fbff; padding: 13px; }.source-section > header { display: flex; align-items: flex-start; gap: 8px; color: #1d4ed8; }.source-section dl { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 12px 0; }.source-section dl .wide { grid-column: 1 / -1; }.source-section dt { color: #64748b; font-size: 9px; }.source-section dd { margin: 3px 0 0; font-size: 11px; white-space: pre-wrap; }.source-files article { display: grid; grid-template-columns: minmax(0,1fr) 30px 30px; gap: 6px; align-items: center; border-top: 1px solid #dbeafe; padding: 8px 0; }.source-files b, .source-files span { display: block; overflow: hidden; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }.source-files span { margin-top: 2px; color: #64748b; }.source-files button { display: grid; width: 30px; height: 30px; place-items: center; border: 0; background: transparent; color: #475569; }.source-files button:disabled { opacity: .5; }.source-files > p { color: #94a3b8; font-size: 10px; }
/* readability overrides */
.target-search { position: relative; display: block; max-width: 360px; }
.target-search svg { position: absolute; z-index: 1; top: 11px; left: 11px; color: #94a3b8; }
.target-search input { padding-left: 34px; }
.target-list { display: grid; max-height: none; grid-auto-columns: 220px; grid-auto-flow: column; grid-template-columns: none; gap: 8px; overflow-x: auto; overflow-y: hidden; padding: 2px 2px 10px; }
.target-card { min-width: 0; padding: 9px 10px; }
.target-card strong { font-size: 11px; }
.target-card span { font-size: 10px; }
.compare-head { font-size: 11px; }
.compare-row { padding-top: 11px; padding-bottom: 11px; }
.compare-row > strong { font-size: 12px; }
.compare-row > p { min-height: 42px; font-size: 11px; line-height: 1.5; }
.choice-buttons button { min-height: 29px; font-size: 10px; }
</style>
