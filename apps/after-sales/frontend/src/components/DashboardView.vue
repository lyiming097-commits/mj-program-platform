<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import {
  ArrowRight,
  CheckCircle2,
  CircleDollarSign,
  Clock3,
  FolderKanban,
} from "@lucide/vue";
import { collectionRows, serviceApi } from "@/serviceApi";
import { CRM_SYNC_POLL_DELAYS } from "@/projectListCache";
import { projectActiveNodes, projectIsCompleted } from "@/projectActiveNodes";
import GlobalNotice from "@/components/GlobalNotice.vue";
import ProjectName from "@/components/ProjectName.vue";

const emit = defineEmits(["navigate"]);
const loading = ref(true);
const error = ref("");
const dashboard = ref({});
const currentTimestamp = ref(Date.now());
const hasData = ref(false);
let reloadTimer = null;
let loadSequence = 0;
let disposed = false;
let syncAttempt = 0;
const crmIncomplete = computed(() => dashboard.value.crmScopeReady === false);
const syncMessage = computed(() => {
  if (dashboard.value.crmSyncError) {
    return `${dashboard.value.crmSyncError}；${crmIncomplete.value ? '以下统计暂未计入 CRM 售前项目' : '当前显示已有同步数据'}。稍后自动重试。`;
  }
  if (crmIncomplete.value) return "正在后台同步 CRM 售前项目，以下统计暂未计入这些项目，完成后自动更新。";
  if (dashboard.value.crmSyncing) return "正在后台更新 CRM 项目，完成后自动刷新统计。";
  return "";
});

const iconMap = [FolderKanban, Clock3, CheckCircle2, CircleDollarSign];
const metrics = computed(() => {
  const raw = dashboard.value.metrics;
  if (Array.isArray(raw)) return raw;
  const source = raw || dashboard.value.summary || {};
  if (dashboard.value.canManageService === false) return [
    { label: "进行中项目", value: source.activeProjects ?? 0, hint: "售前、售中与售后", tone: "blue" },
    { label: "未完成工单", value: source.openTickets ?? 0, hint: "需要处理或审核", tone: "amber" },
    { label: "待审反馈", value: source.pendingFeedback ?? 0, hint: "现场反馈与建议", tone: "green" },
    { label: "风险提醒", value: dashboard.value.alertTotal ?? 0, hint: "临近到期、逾期与异常项目", tone: "violet" },
  ];
  return [
    { label: "进行中项目", value: source.active_projects ?? source.activeProjects ?? 0, hint: "售前、售中与售后", tone: "blue" },
    { label: "未完成工单", value: source.open_tickets ?? source.openTickets ?? source.pending_nodes ?? source.pendingNodes ?? 0, hint: "需要处理或审核", tone: "amber" },
    { label: "待审反馈", value: source.pending_feedback ?? source.pendingFeedback ?? source.completed_this_month ?? source.completedThisMonth ?? 0, hint: "现场反馈与建议", tone: "green" },
    { label: "待发奖励", value: source.pending_rewards ?? source.pendingRewards ?? source.pending_settlements ?? source.pendingSettlements ?? 0, hint: "审核或等待发放", tone: "violet" },
  ];
});

const projectRows = computed(() => collectionRows(
  dashboard.value.projects || dashboard.value.recent_projects || dashboard.value.recentProjects,
));
const tasks = computed(() => collectionRows(
  dashboard.value.tasks || dashboard.value.pending_tasks || dashboard.value.pendingTasks || dashboard.value.recentTickets,
));
const alerts = computed(() => collectionRows(
  dashboard.value.alerts || dashboard.value.risks,
));
const taskTotal = computed(() => hasData.value ? dashboard.value.taskTotal ?? tasks.value.length : "—");
const alertTotal = computed(() => hasData.value ? dashboard.value.alertTotal ?? alerts.value.length : "—");

function emptyText(message) {
  if (!hasData.value) return "总览暂未加载成功，稍后自动重试";
  return crmIncomplete.value ? `${message}（CRM 售前项目尚未加载）` : message;
}
const dateLabel = new Intl.DateTimeFormat("zh-CN", {
  month: "long",
  day: "numeric",
  weekday: "long",
}).format(new Date());

const serviceLabels = Object.freeze({
  presales: "售前服务",
  midsales: "售中服务",
  aftersales: "售后服务",
});

const nodeLabels = Object.freeze({
  "early-approval": "前期立项",
  "early-plan": "前期方案",
  "budget-match": "预算匹配",
  "project-filing": "项目申报",
  "early-plan-result": "前期方案结果",
  "late-approval": "后期立项",
  "late-plan": "后期方案",
  "device-plan": "设备方案",
  budget: "工程预算",
  "device-budget": "设备预算",
  "cost-control": "工程成本管控",
  "device-cost-control": "设备成本管控",
  rendering: "效果图",
  "tender-plan": "招标方案",
  layout: "平面设计",
  "bid-prep": "投标准备",
  "construction-result": "投标结果",
  construction: "施工图",
  "project-end": "售前项目结束",
  "midsales-project": "项目立项",
  "construction-work": "工程施工",
  "furniture-install": "家具安装",
  "device-install": "设备安装",
  "device-debug": "设备调试",
  "school-support": "开学保障",
  "project-acceptance": "项目验收",
  "midsales-project-end": "售中项目结束",
  "onsite-service": "上门售后",
  "mail-service": "寄件售后",
  "school-inspection": "开学巡检",
});

function text(item, ...keys) {
  for (const key of keys) {
    if (item?.[key] !== undefined && item?.[key] !== null && item?.[key] !== "") return item[key];
  }
  return "-";
}

function serviceType(item) {
  return String(item?.serviceType || item?.service_type || item?.module || "presales");
}

function serviceLabel(item) {
  return text(item, "serviceTypeLabel", "service_type_label", "serviceTypeDisplay", "service_type_display") !== "-"
    ? text(item, "serviceTypeLabel", "service_type_label", "serviceTypeDisplay", "service_type_display")
    : serviceLabels[serviceType(item)] || "服务项目";
}

function currentNodeLabel(project) {
  const direct = text(project, "currentNodeName", "current_node_name", "stage");
  if (direct !== "-") return direct;
  const key = String(project?.currentNodeKey || project?.current_node_key || "");
  return nodeLabels[key] || "待确认";
}

function currentNodeLabels(project) {
  const active = projectActiveNodes(project);
  return active.length ? active.map(node => nodeLabels[node.nodeKey] || node.name) : [currentNodeLabel(project)];
}

function targetPage(item) {
  const module = serviceType(item);
  if (["tickets", "feedback"].includes(module)) return "collaboration";
  return ["presales", "midsales", "aftersales"].includes(module) ? module : "aftersales";
}

function navigationTarget(item) {
  return {
    page: targetPage(item),
    projectId: String(item?.projectId || item?.project_id || item?.id || ""),
    nodeKey: String(item?.nodeKey || item?.node_key || item?.currentNodeKey || item?.current_node_key || ""),
    ticketId: String(item?.ticketId || item?.ticket_id || ""),
  };
}

function taskDueClass(task) {
  const due = String(text(task, "dueText", "due_text", "deadline"));
  return due.includes("超时") ? "is-overdue" : "";
}

function scheduleReload() {
  if (disposed) return;
  clearTimeout(reloadTimer);
  const syncing = dashboard.value.crmSyncing || (crmIncomplete.value && !dashboard.value.crmSyncError);
  reloadTimer = setTimeout(() => {
    if (document.hidden) scheduleReload();
    else {
      if (syncing) syncAttempt += 1;
      load();
    }
  }, syncing ? CRM_SYNC_POLL_DELAYS[Math.min(syncAttempt, CRM_SYNC_POLL_DELAYS.length - 1)] : 30000);
}

async function load() {
  currentTimestamp.value = Date.now();
  const sequence = ++loadSequence;
  clearTimeout(reloadTimer);
  loading.value = !hasData.value;
  error.value = "";
  try {
    const response = await serviceApi.dashboard();
    if (disposed || sequence !== loadSequence) return;
    dashboard.value = response;
    if (!response.crmSyncing && response.crmScopeReady !== false) syncAttempt = 0;
    hasData.value = true;
  } catch (reason) {
    if (disposed || sequence !== loadSequence) return;
    error.value = reason instanceof Error ? reason.message : "总览加载失败";
  } finally {
    if (!disposed && sequence === loadSequence) {
      loading.value = false;
      scheduleReload();
    }
  }
}

onMounted(load);
onBeforeUnmount(() => {
  disposed = true;
  loadSequence += 1;
  clearTimeout(reloadTimer);
});
</script>

<template>
  <div class="as-page as-dashboard-page">
    <header class="as-page-head as-dashboard-head">
      <div>
        <p class="as-eyebrow">服务运营总览</p>
        <h1>今日工作台</h1>
        <p>{{ dateLabel }} · 集中查看项目推进、现场待办与风险状态。</p>
      </div>
    </header>

    <GlobalNotice v-model:error="error" />
    <div v-if="syncMessage" class="as-panel-head" :role="dashboard.crmSyncError ? 'alert' : 'status'"><p>{{ syncMessage }}</p></div>

    <section class="as-metric-grid as-dashboard-metrics" aria-label="关键指标">
      <article v-for="(metric, index) in metrics" :key="metric.label" class="as-metric as-dashboard-metric" :class="'is-' + (metric.tone || 'blue')">
        <header><span>{{ metric.label }}</span><span class="as-metric__icon" :class="'is-' + (metric.tone || 'blue')"><component :is="iconMap[index] || FolderKanban" /></span></header>
        <strong v-if="!loading">{{ hasData ? metric.value ?? 0 : '—' }}</strong>
        <span v-else class="as-dashboard-metric__skeleton" aria-label="正在加载"></span>
        <small>{{ metric.hint || "" }}</small>
      </article>
    </section>

    <div class="as-dashboard-workspace">
      <section class="as-panel as-dashboard-projects">
        <div class="as-panel-head">
          <div><h2>最近项目</h2><p>最近更新的 {{ projectRows.length }} 个服务项目</p></div>
        </div>
        <div v-if="loading" class="as-dashboard-table-skeleton" aria-label="正在读取项目"><span v-for="index in 5" :key="index"></span></div>
        <div v-else-if="!projectRows.length" class="as-empty">{{ emptyText('暂无最近项目') }}</div>
        <div v-else class="as-table-wrap">
          <table class="as-table as-dashboard-project-table as-template-table">
            <thead><tr><th>项目</th><th>服务阶段</th><th>当前节点</th><th>负责人</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="project in projectRows" :key="project.id" tabindex="0" @click="emit('navigate', navigationTarget(project))" @keydown.enter="emit('navigate', navigationTarget(project))">
                <td><ProjectName :name="text(project, 'name', 'project_name', 'projectName')" :created-at="project.crmCreatedAt || ''" :now="currentTimestamp" /><small>{{ text(project, 'customer_name', 'customerName', 'customer') }}</small></td>
                <td><span class="as-dashboard-service-badge" :class="'is-' + serviceType(project)">{{ serviceLabel(project) }}</span></td>
                <td><span class="as-project-active-stages"><span v-for="(label, index) in currentNodeLabels(project)" :key="index" class="as-dashboard-node">{{ label }}</span></span></td>
                <td>{{ text(project, 'owner_name', 'ownerName', 'owner') }}</td>
                <td><span class="as-status" :class="{ 'is-done': projectIsCompleted(project) }">{{ text(project, 'statusLabel', 'status_display', 'statusDisplay', 'status') }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <aside class="as-dashboard-rail">
        <section class="as-panel as-dashboard-tasks">
          <div class="as-panel-head"><div><h2>我的待办</h2><p>{{ taskTotal }} 项待处理<span v-if="taskTotal > tasks.length"> · 显示前 {{ tasks.length }} 项，其余请进入服务页查看</span></p></div><span class="as-dashboard-count">{{ taskTotal }}</span></div>
          <div class="as-dashboard-task-list">
            <div v-if="loading" class="as-dashboard-list-skeleton"><span v-for="index in 4" :key="index"></span></div>
            <div v-else-if="!tasks.length" class="as-empty as-empty--compact">{{ emptyText('当前没有待办') }}</div>
            <button v-for="task in tasks" v-else :key="task.id" type="button" class="as-task-row" @click="emit('navigate', navigationTarget(task))">
              <span class="as-task-row__icon"><Clock3 /></span>
              <span><strong>{{ text(task, 'title', 'nodeName', 'node_name') }}</strong><small>{{ text(task, 'projectName', 'project_name', 'project') }}</small><em v-if="task.deadline" :class="taskDueClass(task)">{{ text(task, 'dueText', 'due_text', 'deadline') }}</em></span>
              <ArrowRight />
            </button>
          </div>
        </section>

        <section class="as-panel as-dashboard-risks">
          <div class="as-panel-head"><div><h2>风险提醒</h2><p>临近到期、超时与异常<span v-if="alertTotal > alerts.length"> · 显示前 {{ alerts.length }} 条，其余请进入服务页查看</span></p></div><span class="as-dashboard-count" :class="{ 'is-danger': alerts.length }">{{ alertTotal }}</span></div>
          <div v-if="loading" class="as-dashboard-list-skeleton" aria-label="正在读取风险"><span v-for="index in 4" :key="index"></span></div>
          <div v-else-if="!alerts.length" class="as-empty as-empty--compact"><CheckCircle2 /> {{ emptyText('暂无风险提醒') }}</div>
          <div v-else class="as-alert-list">
            <button v-for="item in alerts" :key="item.id || item.title" type="button" class="as-alert-row" @click="emit('navigate', navigationTarget(item))">
              <span class="as-severity" :class="'is-' + (item.level || item.severity || 'medium')"></span>
              <span><strong>{{ text(item, 'title', 'projectName', 'project_name') }}</strong><small>{{ text(item, 'description', 'message', 'detail') }}</small></span>
              <time>{{ text(item, 'dueText', 'due_text', 'time') }}</time>
            </button>
          </div>
        </section>
      </aside>
    </div>
  </div>
</template>
