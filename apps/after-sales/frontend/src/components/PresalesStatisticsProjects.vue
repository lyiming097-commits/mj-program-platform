<script setup>
import { computed, shallowRef, watch } from "vue";
import { ArrowUpRight, ClipboardList, FileText, LoaderCircle, Paperclip } from "@lucide/vue";
import { presalesStatisticColumns, statisticNumber } from "@/presalesStatistics";
import AttachmentPanel from "@/components/AttachmentPanel.vue";
import ListPagination from "@/components/ListPagination.vue";
import ModalShell from "@/components/ModalShell.vue";
import ProjectName from "@/components/ProjectName.vue";

const props = defineProps({
  rows: { type: Array, default: () => [] },
  view: { type: String, default: "all" },
  groupLabel: { type: String, default: "全部项目" },
  page: { type: Number, default: 1 },
  pageSize: { type: Number, default: 20 },
  total: { type: Number, default: 0 },
  totalPages: { type: Number, default: 1 },
  loading: { type: Boolean, default: false },
});
const emit = defineEmits(["open-project", "change-page", "update:pageSize"]);
const columns = computed(() => presalesStatisticColumns(props.view));
const tableWidth = computed(() => `${columns.value.reduce((sum, column) => sum + column.width, 0)}px`);
const viewer = shallowRef(null);
const attachmentError = shallowRef("");
const attachmentPreviewOpen = shallowRef(false);
const viewedProject = computed(() => props.rows.find(row => row.id === viewer.value?.id));
const viewedColumn = computed(() => columns.value.find(column => column.key === viewer.value?.key));
const viewedTasks = computed(() => viewedProject.value?.[viewer.value?.key] || []);
watch(viewer, value => { if (!value) attachmentPreviewOpen.value = false; });
watch([() => props.rows, () => props.view], () => {
  if (!viewedProject.value || !viewedColumn.value) viewer.value = null;
});
function openViewer(project, column) {
  attachmentError.value = "";
  viewer.value = { id: project.id, key: column.key };
}
function progress(project) {
  return project.taskCount ? `${Math.round(project.completedTaskCount / project.taskCount * 100)}%` : "暂无任务";
}
</script>

<template>
  <section class="as-panel as-stat-details" aria-label="售前统计项目明细" :aria-busy="loading">
    <header class="as-panel-head"><div><h2><ClipboardList />项目明细<span>{{ groupLabel }}</span></h2><p>共 {{ total }} 个项目 · 点击项目查看服务详情</p></div><LoaderCircle v-if="loading" class="as-spin" /></header>
    <div class="as-project-table-scroll as-stat-detail-scroll" tabindex="0" role="region" aria-label="售前统计项目表格，可横向滚动">
      <table class="as-project-table as-template-table as-stat-detail-table" aria-label="售前统计项目明细" :style="{ minWidth: tableWidth }">
        <colgroup><col v-for="column in columns" :key="column.key" :style="{ width: `${column.width}px` }"></colgroup>
        <thead><tr><th v-for="column in columns" :key="column.key" scope="col">{{ column.label }}</th></tr></thead>
        <tbody>
          <tr v-if="!rows.length"><td :colspan="columns.length" class="as-stat-empty">{{ loading ? '正在读取项目...' : '没有符合条件的项目' }}</td></tr>
          <tr v-for="project in rows" :key="project.id">
            <td v-for="column in columns" :key="column.key">
              <button v-if="column.key === 'name'" type="button" class="as-project-identity as-stat-project-link" :title="project.name" :aria-label="`查看项目 ${project.name}`" @click="emit('open-project', project.id)"><ProjectName :name="project.name" :created-at="project.crmCreatedAt || ''" :now="Date.now()" /><ArrowUpRight /></button>
              <div v-else-if="column.type === 'tags'" class="as-stat-tags"><span v-for="nature in project.natures" :key="nature" class="as-project-stage">{{ nature }}</span><small v-if="!project.natures.length">未填写</small></div>
              <span v-else-if="column.type === 'people'">{{ project[column.key]?.map(row => row.name).join('、') || '未分派' }}</span>
              <span v-else-if="column.type === 'money' || column.type === 'area'" class="as-stat-numeric">{{ statisticNumber(project[column.key], { currency: column.type === 'money', area: column.type === 'area' }) }}</span>
              <template v-else-if="column.type === 'attachments'"><button v-if="project.requirementCount" type="button" class="as-stat-cell-link" @click="openViewer(project, column)"><Paperclip />{{ project.requirementCount }} 个文档</button><small v-else>暂无文档</small></template>
              <template v-else-if="column.type === 'tasks'"><button v-if="project[column.key]?.length" type="button" class="as-stat-cell-link" @click="openViewer(project, column)"><ClipboardList />{{ project[column.key].length }} 项任务</button><small v-else>暂无任务</small></template>
              <div v-else-if="column.type === 'progress'" class="as-stat-task-progress"><div><span>{{ progress(project) }}</span><small v-if="project.taskCount">{{ project.completedTaskCount }} / {{ project.taskCount }} 项完成</small></div><span v-if="project.taskCount" class="as-stat-progress-bar"><span :style="{ width: progress(project) }"></span></span></div>
              <template v-else-if="column.type === 'text'"><button v-if="project[column.key]" type="button" class="as-stat-text-link" :title="project[column.key]" @click="openViewer(project, column)"><span>{{ project[column.key] }}</span><FileText /></button><small v-else>未填写</small></template>
              <span v-else>{{ project[column.key] === 0 ? 0 : project[column.key] || '未填写' }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <ListPagination :page="page" :page-size="pageSize" :total="total" :total-pages="totalPages" :loading="loading" label="售前统计明细分页" @change="emit('change-page', $event)" @update:page-size="emit('update:pageSize', $event)" />
    <ModalShell :open="Boolean(viewer && viewedProject && viewedColumn)" :title="viewedColumn?.label || ''" :description="viewedProject?.name || ''" :suspended="attachmentPreviewOpen" wide manage-focus @close="viewer = null">
      <template v-if="viewedColumn?.type === 'attachments' && viewedProject?.id"><p v-if="attachmentError" class="as-stat-attachment-error" role="alert">{{ attachmentError }}</p><AttachmentPanel :key="viewedProject.id" target-type="presales_project" :target-id="viewedProject.id" :editable="false" title="项目需求文档" compact manage-preview-focus @preview-change="attachmentPreviewOpen = $event" @error="attachmentError = $event" /></template>
      <div v-else-if="viewedColumn?.type === 'tasks'" class="as-stat-task-scroll as-stat-scroll" tabindex="0" role="region" aria-label="售前任务排期表格，可横向滚动"><table class="as-project-table as-template-table as-stat-task-table" aria-label="售前任务排期"><thead><tr><th scope="col">任务</th><th scope="col">计划开始</th><th scope="col">预计完成</th><th scope="col">完成时间</th><th scope="col">状态</th></tr></thead><tbody><tr v-for="task in viewedTasks" :key="`${task.nodeKey}:${task.roundNumber}`"><td>{{ task.name }}</td><td>{{ task.plannedStartDate || '未设置' }}</td><td>{{ task.plannedEndDate || '未设置' }}</td><td>{{ task.actualEndDate || '—' }}</td><td>{{ task.isCompleted ? '已完成' : '未完成' }}</td></tr></tbody></table></div>
      <p v-else class="as-stat-full-text">{{ viewedProject?.[viewedColumn?.key] }}</p>
      <template #footer><button type="button" class="as-button as-button--secondary" @click="viewer = null">关闭</button></template>
    </ModalShell>
  </section>
</template>

<style scoped>
.as-stat-details { display: flex; min-width: 0; min-height: 0; flex-direction: column; }
.as-stat-detail-scroll { max-height: var(--as-stat-detail-max-height); }
.as-panel-head { flex-shrink: 0; }
.as-panel-head h2 { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; }
.as-panel-head h2 svg { width: 16px; height: 16px; color: #64748b; }
.as-panel-head h2 > span { border-left: 1px solid #d8e0ea; margin-left: 3px; padding-left: 10px; color: #6e7c90; font-size: 12px; font-weight: 500; }
.as-stat-detail-table th:first-child, .as-stat-detail-table td:first-child { position: sticky; left: 0; box-shadow: 1px 0 0 var(--as-border); }
.as-stat-detail-table th:first-child { z-index: 3; }
.as-stat-detail-table td { overflow-wrap: anywhere; }
.as-stat-detail-table td:first-child { z-index: 1; }
.as-stat-project-link { display: inline-flex; width: 100%; max-width: 100%; align-items: center; justify-content: center; gap: 5px; overflow: hidden; border: 0; background: none; padding: 0; color: var(--as-primary); font: inherit; }
.as-stat-project-link svg { width: 13px; height: 13px; flex-shrink: 0; }
.as-stat-project-link :deep(.as-project-name) { min-width: 0; overflow: hidden; }
.as-stat-cell-link, .as-stat-text-link { display: inline-flex; align-items: center; justify-content: center; gap: 6px; max-width: 100%; border: 0; background: none; padding: 4px 0; color: var(--as-primary); font: inherit; }
.as-stat-cell-link svg, .as-stat-text-link svg { width: 14px; height: 14px; flex-shrink: 0; }
.as-stat-text-link > span { overflow: hidden; color: var(--as-muted); text-overflow: ellipsis; white-space: nowrap; }
.as-stat-task-progress > div { display: flex; align-items: baseline; justify-content: center; gap: 6px; }
.as-stat-progress-bar { display: block; width: 112px; height: 4px; margin: 5px auto 0; border-radius: 3px; overflow: hidden; background: var(--as-soft); }
.as-stat-progress-bar > span { display: block; height: 100%; background: #6e96de; }
.as-stat-full-text { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.8; color: #35475f; font-size: 14px; }
.as-stat-task-scroll { overflow: auto; }
.as-stat-task-table { min-width: 650px; }
.as-stat-attachment-error { color: #af5454; }
.as-stat-detail-table small { color: var(--as-muted); font-size: 10px; }
.as-stat-tags { display: flex; justify-content: center; flex-wrap: wrap; gap: 4px; }
.as-stat-numeric { white-space: nowrap; font-variant-numeric: tabular-nums; }
.as-stat-empty { text-align: center; color: var(--as-muted); }
</style>
