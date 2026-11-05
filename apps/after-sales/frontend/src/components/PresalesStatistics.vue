<script setup>
import { computed, reactive } from "vue";
import { Layers3, List, Milestone, RotateCcw, Search, UserRound, Users } from "@lucide/vue";
import { ElOption, ElSelect } from "element-plus/es/components/select/index.mjs";
import "element-plus/es/components/select/style/css";
import { PRESALES_STATISTIC_DIMENSIONS } from "@/presalesStatistics";
import { usePresalesStatistics } from "@/composables/usePresalesStatistics";
import PresalesStatisticsGroups from "@/components/PresalesStatisticsGroups.vue";
import PresalesStatisticsProjects from "@/components/PresalesStatisticsProjects.vue";

const props = defineProps({
  session: { type: Object, default: null },
  active: { type: Boolean, default: true },
  refreshKey: { type: Number, default: 0 },
});
const emit = defineEmits(["open-project"]);
const collapsedGroups = reactive({});
const { groupBy, groupKey, search, status, page, pageSize, data, loading, error,
  load, selectDimension, selectGroup } = usePresalesStatistics(props);
const icons = { all: List, nature: Layers3, stage: Milestone, sales: Users, design: UserRound };
const dimension = computed(() => PRESALES_STATISTIC_DIMENSIONS.find(row => row.value === groupBy.value));
const summary = computed(() => data.value?.summary);
const selectedGroup = computed(() => data.value?.groups.find(row => row.key === groupKey.value));
const overlap = computed(() => data.value?.groupMembershipCount > (summary.value?.count || 0));
const notes = {
  all: "按启动时间、金额、面积与负责人查看全部售前项目，向右滚动可查看完整字段。",
  nature: "项目性质取自 CRM 的集成工作类型；未填写的项目单独归类。",
  stage: "项目阶段取自 CRM 销售阶段；服务节点可在项目明细中查看。",
  sales: "销售负责人沿用项目负责人，CRM 来源项目跟随 CRM 更新。",
  design: "设计负责人取自售前立项中已分派的设计负责人。",
};
</script>

<template>
  <div class="as-page as-presales-statistics">
    <header class="as-stat-heading"><h1>售前项目统计</h1></header>

    <div v-if="error" class="as-stat-notice is-error" role="alert"><span>{{ error }}</span><button type="button" class="as-button as-button--secondary" :disabled="loading" @click="load()"><RotateCcw />重试</button></div>
    <div v-if="data?.crmSyncError || data?.crmSyncing" class="as-stat-notice" role="status">{{ data.crmSyncError ? `${data.crmSyncError}；已单独统计可访问的本地项目。` : data.crmScopeReady ? 'CRM 正在后台更新，当前统计可继续查看。' : 'CRM 项目正在同步，当前先展示本地项目统计。' }}</div>

    <section class="as-stat-workspace" aria-label="售前项目分类统计">
      <div class="as-stat-toolbar">
        <nav class="as-stat-dimensions" aria-label="统计分类">
          <button v-for="item in PRESALES_STATISTIC_DIMENSIONS" :key="item.value" type="button" :class="{ active: groupBy === item.value }" :aria-pressed="groupBy === item.value" @click="selectDimension(item.value)"><component :is="icons[item.value]" />{{ item.label }}</button>
        </nav>
        <div class="as-stat-filters"><label class="as-search"><Search /><input v-model="search" type="search" placeholder="搜索项目、客户或销售" aria-label="搜索售前统计项目"></label><ElSelect v-model="status" class="as-table-select as-stat-status-select" popper-class="as-table-select-popper" aria-label="统计项目状态" placeholder="全部状态"><ElOption label="全部状态" value="" /><ElOption label="进行中" value="in_progress" /><ElOption label="已完成" value="completed" /><ElOption label="异常跟进" value="blocked" /><ElOption label="草稿" value="draft" /><ElOption label="已取消" value="cancelled" /></ElSelect></div>
      </div>
      <p class="as-stat-caption">{{ notes[groupBy] }}<span v-if="overlap">多性质或多人项目分别归入各组，汇总项目总数不重复计算。</span></p>
      <PresalesStatisticsGroups v-if="groupBy !== 'all'" v-model:collapsed="collapsedGroups[groupBy]" :groups="data?.groups || []" :selected-key="groupKey" :field="dimension.field" :total="summary?.count || 0" :loading="loading" @select="selectGroup" />
      <PresalesStatisticsProjects :key="groupBy" :view="groupBy" :rows="data?.groupBy === groupBy ? data.items : []" :group-label="selectedGroup?.label || '全部项目'" :page="data?.page || page" :page-size="pageSize" :total="data?.total || 0" :total-pages="data?.totalPages || 1" :loading="loading" @open-project="emit('open-project', $event)" @change-page="page = $event" @update:page-size="pageSize = $event" />
      <p class="as-stat-footnote">金额为项目金额，独立于节点费用和结算。项目总面积、设计面积及等级未维护时显示未填写；工程施工面积不代替项目总面积。任务完成状态跟随所属节点，完成时间由系统记录；需求文档在项目信息页维护，包含原前期立项附件。</p>
    </section>
  </div>
</template>

<style scoped>
.as-presales-statistics { --as-stat-group-max-height: clamp(240px, 40dvh, 420px); --as-stat-detail-max-height: clamp(420px, 65dvh, 720px); display: grid; grid-template-columns: minmax(0, 1fr); align-content: start; gap: var(--as-group-gap); }
.as-stat-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.as-stat-heading h1 { margin: 0; color: #1b2e48; font-size: 22px; font-weight: 650; line-height: 1.4; }
.as-stat-workspace { display: grid; min-width: 0; grid-template-columns: minmax(0, 1fr); align-content: start; gap: var(--as-group-gap); }
.as-stat-toolbar { display: flex; min-width: 0; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; }
.as-stat-dimensions { display: flex; gap: 4px; overflow-x: auto; border: 1px solid #dce4ee; border-radius: 7px; background: #fff; padding: 4px; }
.as-stat-dimensions button { display: flex; min-height: 34px; align-items: center; justify-content: center; gap: 6px; border: 0; border-radius: 5px; background: transparent; padding: 0 11px; color: #7b879a; font-size: 12px; white-space: nowrap; }
.as-stat-dimensions button.active { background: #edf3fc; color: #285fb2; }
.as-stat-dimensions button svg { width: 14px; height: 14px; }
.as-stat-filters { display: flex; min-width: 0; align-items: center; gap: 10px; }
.as-stat-filters .as-search { width: 232px; }
.as-stat-status-select { width: 130px; flex-shrink: 0; }
.as-stat-caption { margin: -4px 0 0; color: #8d99aa; font-size: 11px; line-height: 1.7; }
.as-stat-caption > span { margin-left: 8px; }
.as-stat-notice { display: flex; align-items: center; justify-content: space-between; gap: 12px; border: 1px solid #eadfbd; border-radius: 6px; background: #fffcf4; padding: 10px 13px; color: #957b41; font-size: 12px; line-height: 1.6; }
.as-stat-notice.is-error { border-color: #f0cccc; background: #fff7f7; color: #af5454; }
.as-stat-notice .as-button { flex-shrink: 0; }
.as-stat-footnote { margin: 0; color: #98a2b3; font-size: 10px; line-height: 1.7; }
@media (max-width: 600px) { .as-stat-heading h1 { font-size: 19px; } .as-stat-dimensions { width: 100%; } .as-stat-dimensions button { flex: 1 0 auto; padding: 0 8px; font-size: 11px; } .as-stat-filters { width: 100%; } .as-stat-filters .as-search { flex: 1; width: auto; } }
</style>

<style>
#app .as-stat-workspace > .as-panel { margin-top: 0; }
#app .as-stat-workspace .as-project-table-scroll { flex: 0 0 auto; }
/* Shared by the report's tables, including its teleported task dialog. */
.as-stat-scroll { overscroll-behavior-x: contain; scrollbar-width: thin; scrollbar-color: #94a3b8 #f1f5f9; scrollbar-gutter: auto; }
.as-stat-scroll::-webkit-scrollbar { display: block; height: 10px; width: 8px; }
.as-stat-scroll::-webkit-scrollbar-track { background: #f1f5f9; }
.as-stat-scroll::-webkit-scrollbar-thumb { border: 2px solid #f1f5f9; border-radius: 999px; background: #94a3b8; }
</style>
