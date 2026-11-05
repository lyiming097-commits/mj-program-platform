<script setup>
import { computed, ref, watch } from "vue";
import {
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Clock3,
  Headphones,
  LoaderCircle,
  MessageSquareText,
  UserRoundCheck,
} from "@lucide/vue";
import AttachmentPanel from "@/components/AttachmentPanel.vue";
import ModalShell from "@/components/ModalShell.vue";
import { serviceApi } from "@/serviceApi";

const props = defineProps({
  mode: { type: String, required: true },
  records: { type: Array, default: () => [] },
});

const emit = defineEmits(["error"]);
const detailOpen = ref(false);
const detailLoading = ref(false);
const selectedRecord = ref(null);
const ticketDetail = ref(null);

const NODE_LABELS = Object.freeze({
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
const TICKET_STATUS_LABELS = Object.freeze({
  open: "待分配",
  assigned: "已指派",
  in_progress: "正在执行",
  pending_review: "待审核",
  completed: "已完成",
  rejected: "已驳回",
  closed: "已完成",
});

const isTicket = computed(() => props.mode === "ticket");
const currentRecord = computed(() => (
  isTicket.value ? ticketDetail.value || selectedRecord.value : selectedRecord.value
));
const listTitle = computed(() => isTicket.value ? "我的工单" : "我的反馈");
const modalTitle = computed(() => isTicket.value ? "工单处理进度" : "反馈审核进度");
const modalDescription = computed(() => {
  const item = currentRecord.value;
  return [item?.projectName, recordNode(item), item?.code].filter(Boolean).join(" · ");
});

function dateTime(value) {
  return value ? String(value).replace("T", " ").slice(0, 16) : "-";
}

function recordTitle(item) {
  return item?.title || (isTicket.value ? "现场支持工单" : "现场反馈");
}

function recordNode(item) {
  return item?.nodeName || NODE_LABELS[item?.nodeKey] || item?.nodeKey || "未关联节点";
}

function messageContent(message) {
  const content = String(message?.content || "");
  const match = content.match(/^工单状态由 ([a-z_]+) 变更为 ([a-z_]+)$/);
  if (!match) return content;
  const before = TICKET_STATUS_LABELS[match[1]] || match[1];
  const after = TICKET_STATUS_LABELS[match[2]] || match[2];
  return before === after ? `工单状态更新为“${after}”` : `工单状态由“${before}”变更为“${after}”`;
}

function statusClass(item) {
  if (["completed", "accepted"].includes(item?.status)) return "is-done";
  if (item?.status === "rejected") return "is-danger";
  if (["assigned", "in_progress", "under_review", "pending_review"].includes(item?.status)) return "is-active";
  return "";
}

function progressText(item) {
  if (isTicket.value) {
    const labels = {
      open: "等待管理端分派处理人",
      assigned: `已分派给${item?.ownerName || "处理人员"}`,
      in_progress: `${item?.ownerName || "处理人员"}正在处理`,
      pending_review: "等待管理端审核处理结果",
      completed: "工单处理已完成",
      rejected: "工单已驳回，等待重新处理",
    };
    return labels[item?.status] || item?.statusLabel || "等待处理";
  }
  const labels = {
    submitted: "等待管理端审核",
    under_review: "管理端正在审核",
    accepted: item?.reviewNote || "反馈已采纳",
    rejected: item?.reviewNote || "反馈未采纳",
  };
  return labels[item?.status] || item?.statusLabel || "等待审核";
}

async function openDetail(item) {
  selectedRecord.value = item;
  ticketDetail.value = null;
  detailOpen.value = true;
  if (!isTicket.value) return;
  detailLoading.value = true;
  try {
    const response = await serviceApi.getTicket(item.id);
    ticketDetail.value = response?.item || response;
  } catch (reason) {
    emit("error", reason instanceof Error ? reason.message : "工单进度加载失败");
  } finally {
    detailLoading.value = false;
  }
}

function closeDetail() {
  detailOpen.value = false;
  selectedRecord.value = null;
  ticketDetail.value = null;
}

watch(() => props.mode, closeDetail);
</script>

<template>
  <section class="as-field-section as-mobile-submission-history">
    <div class="as-field-section__head">
      <div><p class="as-eyebrow">进度跟踪</p><h2>{{ listTitle }}</h2></div>
      <span class="as-status">{{ records.length }} 条</span>
    </div>
    <div v-if="records.length" class="as-mobile-submission-list">
      <button v-for="item in records" :key="item.id" type="button" @click="openDetail(item)">
        <span class="as-mobile-submission-icon"><Headphones v-if="isTicket" /><MessageSquareText v-else /></span>
        <span class="as-mobile-submission-copy">
          <span><strong>{{ recordTitle(item) }}</strong><em class="as-status" :class="statusClass(item)">{{ item.statusLabel || item.status }}</em></span>
          <small>{{ item.projectName || '服务项目' }} · {{ recordNode(item) }}</small>
          <p>{{ progressText(item) }}</p>
          <time><Clock3 />{{ dateTime(item.updatedAt || item.createdAt) }}</time>
        </span>
        <ChevronRight class="as-mobile-submission-arrow" />
      </button>
    </div>
    <div v-else class="as-empty as-empty--large"><Headphones v-if="isTicket" /><CircleAlert v-else /> 暂无{{ isTicket ? '工单' : '反馈' }}记录</div>

    <ModalShell :open="detailOpen" :title="modalTitle" :description="modalDescription" wide @close="closeDetail">
      <div v-if="detailLoading" class="as-empty as-empty--large"><LoaderCircle class="as-spin" /> 正在加载工单进度...</div>
      <div v-else-if="currentRecord" class="as-mobile-submission-detail">
        <header>
          <div><p class="as-eyebrow">{{ isTicket ? '工单详情' : '反馈详情' }}</p><h3>{{ recordTitle(currentRecord) }}</h3><small>{{ dateTime(currentRecord.createdAt) }} 提交</small></div>
          <span class="as-status" :class="statusClass(currentRecord)">{{ currentRecord.statusLabel || currentRecord.status }}</span>
        </header>
        <dl class="as-mobile-submission-facts">
          <div><dt>所属项目</dt><dd>{{ currentRecord.projectName || '-' }}</dd></div>
          <div><dt>关联节点</dt><dd>{{ recordNode(currentRecord) }}</dd></div>
          <div v-if="isTicket"><dt>处理人员</dt><dd>{{ currentRecord.ownerName || '待分配' }}</dd></div>
          <div v-else><dt>反馈类型</dt><dd>{{ currentRecord.feedbackTypeLabel || currentRecord.feedbackType || '-' }}</dd></div>
          <div><dt>{{ isTicket ? '最后更新' : '服务评分' }}</dt><dd>{{ isTicket ? dateTime(currentRecord.updatedAt) : currentRecord.rating ? currentRecord.rating + ' 分' : '-' }}</dd></div>
        </dl>
        <section class="as-mobile-submission-section">
          <h4>{{ isTicket ? '问题描述' : '反馈内容' }}</h4>
          <p>{{ isTicket ? currentRecord.description : currentRecord.content }}</p>
        </section>
        <section v-if="isTicket && currentRecord.resolution" class="as-mobile-submission-section as-mobile-submission-section--result">
          <h4><CheckCircle2 />处理结果</h4><p>{{ currentRecord.resolution }}</p>
        </section>
        <section v-if="!isTicket" class="as-mobile-submission-section" :class="{ 'as-mobile-submission-section--result': ['accepted', 'rejected'].includes(currentRecord.status) }">
          <h4><UserRoundCheck />审核意见</h4>
          <p>{{ currentRecord.reviewNote || progressText(currentRecord) }}</p>
          <small v-if="currentRecord.reviewedAt">审核时间：{{ dateTime(currentRecord.reviewedAt) }}</small>
        </section>
        <section class="as-mobile-submission-section">
          <h4>提交附件</h4>
          <AttachmentPanel :target-type="isTicket ? 'ticket' : 'feedback'" :target-id="currentRecord.id" :editable="false" compact @error="emit('error', $event)" />
        </section>
        <section v-if="isTicket" class="as-mobile-submission-section">
          <h4>处理记录</h4>
          <div v-if="!(currentRecord.messages || []).length" class="as-empty as-empty--compact">暂无处理记录</div>
          <div v-else class="as-mobile-submission-timeline">
            <article v-for="message in currentRecord.messages" :key="message.id">
              <span></span><div><strong>{{ message.authorName || '系统' }}</strong><time>{{ dateTime(message.createdAt) }}</time><p>{{ messageContent(message) }}</p></div>
            </article>
          </div>
        </section>
      </div>
    </ModalShell>
  </section>
</template>

<style scoped>
.as-mobile-submission-history { max-width: 700px; }
.as-mobile-submission-list { border-top: 1px solid #e4e7ec; }
.as-mobile-submission-list > button { display: grid; width: 100%; min-width: 0; min-height: 88px; grid-template-columns: 36px minmax(0, 1fr) 16px; align-items: center; gap: 10px; border: 0; border-bottom: 1px solid #edf0f2; background: #fff; padding: 11px 4px; color: #344054; text-align: left; }
.as-mobile-submission-list > button:last-child { border-bottom: 0; }
.as-mobile-submission-list > button:hover { background: #f8fbff; }
.as-mobile-submission-list > button:focus-visible { outline: 2px solid #93c5fd; outline-offset: -2px; }
.as-mobile-submission-icon { display: grid; width: 34px; height: 34px; place-items: center; border-radius: 7px; background: #edf3fb; color: #315f9f; }
.as-mobile-submission-icon svg { width: 17px; height: 17px; }
.as-mobile-submission-copy { display: block; min-width: 0; }
.as-mobile-submission-copy > span { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 8px; }
.as-mobile-submission-copy strong { min-width: 0; overflow: hidden; color: #263244; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.as-mobile-submission-copy em { flex: 0 0 auto; font-style: normal; }
.as-mobile-submission-copy small, .as-mobile-submission-copy p, .as-mobile-submission-copy time { display: block; margin-top: 3px; }
.as-mobile-submission-copy small { overflow: hidden; color: #7b8798; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.as-mobile-submission-copy p { overflow: hidden; margin-bottom: 0; color: #526174; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.as-mobile-submission-copy time { display: flex; align-items: center; gap: 4px; color: #98a2b3; font-size: 8px; }
.as-mobile-submission-copy time svg { width: 11px; height: 11px; }
.as-mobile-submission-arrow { width: 15px; height: 15px; color: #98a2b3; }
.as-status.is-danger { border-color: #efc8cd; background: #fff3f4; color: #b42318; }
.as-status.is-active { border-color: #bfd2f7; background: #edf4ff; color: #155eef; }
.as-mobile-submission-detail { display: grid; gap: 14px; }
.as-mobile-submission-detail > header { display: flex; min-width: 0; align-items: flex-start; justify-content: space-between; gap: 12px; }
.as-mobile-submission-detail h3 { margin: 2px 0 0; color: #172033; font-size: 17px; line-height: 24px; }
.as-mobile-submission-detail header small { display: block; margin-top: 3px; color: #7b8798; font-size: 10px; }
.as-mobile-submission-facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); border-top: 1px solid #e1e6ed; border-left: 1px solid #e1e6ed; margin: 0; }
.as-mobile-submission-facts > div { min-width: 0; border-right: 1px solid #e1e6ed; border-bottom: 1px solid #e1e6ed; padding: 10px; }
.as-mobile-submission-facts dt { color: #7b8798; font-size: 9px; }
.as-mobile-submission-facts dd { overflow: hidden; margin: 4px 0 0; color: #344054; font-size: 11px; font-weight: 750; text-overflow: ellipsis; white-space: nowrap; }
.as-mobile-submission-section { border-top: 1px solid #e4e7ec; padding-top: 12px; }
.as-mobile-submission-section h4 { display: flex; align-items: center; gap: 6px; margin: 0; color: #344054; font-size: 12px; }
.as-mobile-submission-section h4 svg { width: 15px; height: 15px; }
.as-mobile-submission-section > p { margin: 7px 0 0; color: #526174; font-size: 11px; line-height: 1.7; white-space: pre-wrap; }
.as-mobile-submission-section > small { display: block; margin-top: 6px; color: #8a96a7; font-size: 9px; }
.as-mobile-submission-section--result { border: 1px solid #b7decf; border-radius: 7px; background: #f2faf6; padding: 11px; }
.as-mobile-submission-timeline { display: grid; gap: 0; margin-top: 8px; }
.as-mobile-submission-timeline article { display: grid; grid-template-columns: 10px minmax(0, 1fr); gap: 8px; }
.as-mobile-submission-timeline article > span { position: relative; width: 8px; height: 8px; border: 2px solid #5e8fe7; border-radius: 50%; margin-top: 4px; background: #fff; }
.as-mobile-submission-timeline article > span::after { position: absolute; top: 8px; left: 2px; width: 1px; height: calc(100% + 36px); background: #d8e0e9; content: ""; }
.as-mobile-submission-timeline article:last-child > span::after { display: none; }
.as-mobile-submission-timeline article > div { border-bottom: 1px solid #edf0f2; padding-bottom: 10px; }
.as-mobile-submission-timeline strong, .as-mobile-submission-timeline time { color: #667085; font-size: 9px; }
.as-mobile-submission-timeline time { float: right; }
.as-mobile-submission-timeline p { margin: 4px 0 0; color: #344054; font-size: 10px; line-height: 1.55; white-space: pre-wrap; }

@media (max-width: 520px) {
  .as-mobile-submission-facts { grid-template-columns: minmax(0, 1fr); }
}
</style>
