<script setup>
import { computed } from "vue";
import { ChevronDown, CircleDollarSign, Clock3, FileText, History, Pencil, RotateCcw, UserRound } from "@lucide/vue";

const props = defineProps({
  record: { type: Object, default: null },
  people: { type: Array, default: () => [] },
  archived: { type: Boolean, default: false },
});

const eventTypes = {
  opening: { label: "历史汇总", icon: History },
  created: { label: "创建结算", icon: FileText },
  receipt: { label: "登记收款", icon: CircleDollarSign },
  invoice: { label: "登记开票", icon: FileText },
  correction: { label: "财务更正", icon: Pencil },
  cancelled: { label: "撤销结算", icon: RotateCcw },
  update: { label: "修改结算", icon: Pencil },
};
const statusLabels = { draft: "草稿", pending: "待结算", settled: "已结算", cancelled: "已撤销" };
const subjectLabels = { company: "公司", person: "个人", customer: "客户" };
const fieldLabels = {
  status: "结算状态", received_amount: "累计已收金额", invoiced_amount: "累计已开票金额",
  invoice_type: "开票类型", invoice_number: "票据单号", subject_type: "主体类型",
  subject_id: "主体编号", subject_name: "承担主体", related_project_id: "关联项目编号", remark: "结算说明",
};
const amountFields = new Set(["received_amount", "invoiced_amount"]);
const peopleById = computed(() => new Map(props.people.map(person => [String(person.userId), person.name])));
const events = computed(() => [...(props.record?.events || [])].sort((a, b) => Number(b.revision) - Number(a.revision)));
const dateFormatter = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
});

function typeFor(event) { return eventTypes[event.kind] || eventTypes.update; }
function money(value) { return "￥" + Number(value || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function dateTime(value) { const date = new Date(value); return value && !Number.isNaN(date.getTime()) ? dateFormatter.format(date) : "时间未记录"; }
function operatorName(event) { return event.operatorName || peopleById.value.get(String(event.createdBy)) || (event.createdBy ? "历史经办人" : "系统记录"); }
function actorName(event) { return event.actorName || peopleById.value.get(String(event.createdActorId)) || "历史操作人"; }
function hasActor(event) { return event.createdActorId && event.createdActorId !== event.createdBy; }
function amounts(event) {
  const opening = event.kind === "opening";
  return [
    { key: "receipt", value: Number(event.receiptDelta || 0), label: opening ? "期初已收" : Number(event.receiptDelta) < 0 ? "冲减收款" : "新增收款" },
    { key: "invoice", value: Number(event.invoiceDelta || 0), label: opening ? "期初已开票" : Number(event.invoiceDelta) < 0 ? "冲减开票" : "新增开票" },
  ].filter(item => opening || item.value !== 0).map(item => ({
    ...item, tone: opening ? "opening" : item.value < 0 ? "decrease" : "increase",
    display: (opening ? "" : item.value < 0 ? "−" : "+") + money(Math.abs(item.value)),
  }));
}
function valueLabel(field, value) {
  if (value == null || String(value).trim() === "") return "未填写";
  if (field === "status") return statusLabels[value] || value;
  if (field === "subject_type") return subjectLabels[value] || value;
  if (amountFields.has(field)) return money(value);
  return String(value);
}
function changes(event) {
  const before = event.before || {}, after = event.after || {};
  return [...new Set([...Object.keys(after), ...Object.keys(before)])]
    .filter(field => valueLabel(field, before[field]) !== valueLabel(field, after[field]))
    .map(field => ({ field, label: fieldLabels[field] || field, before: valueLabel(field, before[field]), after: valueLabel(field, after[field]) }));
}
</script>

<template>
  <section class="as-settlement-audit" aria-label="结算版本与留痕">
    <header class="as-settlement-audit__header">
      <div>
        <h2>{{ archived ? '已撤销结算的留痕' : '结算版本与留痕' }}</h2>
        <p><template v-if="record">{{ record.code }} · {{ statusLabels[record.status] || '待结算' }} · 共 {{ events.length }} 条记录</template><template v-else>收款、开票及结算信息的修改记录</template></p>
      </div>
      <span v-if="record" class="as-settlement-audit__version">版本 {{ record.revision }}</span>
    </header>

    <div v-if="!events.length" class="as-settlement-audit__empty">
      <History aria-hidden="true" />
      <strong>暂无结算留痕</strong>
      <p>{{ record ? '此结算暂无已记录的操作。' : '保存结算后，收款、开票与修改记录会显示在这里。' }}</p>
    </div>
    <ol v-else class="as-settlement-audit__timeline" aria-label="财务流水">
      <li v-for="event in events" :key="event.id" class="as-settlement-audit__event" :class="`is-${event.kind}`">
        <span class="as-settlement-audit__marker" aria-hidden="true"><component :is="typeFor(event).icon" /></span>
        <article class="as-settlement-audit__entry" :aria-label="`${typeFor(event).label} · 版本 ${event.revision}`">
          <div class="as-settlement-audit__event-head">
            <div><h3>{{ typeFor(event).label }}</h3><span class="as-settlement-audit__revision">版本 {{ event.revision }}</span></div>
            <time :datetime="event.createdAt"><Clock3 aria-hidden="true" />{{ dateTime(event.createdAt) }}</time>
          </div>
          <p class="as-settlement-audit__operator"><UserRound aria-hidden="true" /><span>经办人</span><strong>{{ operatorName(event) }}</strong><span v-if="hasActor(event)" class="as-settlement-audit__actor">实际操作：{{ actorName(event) }}</span></p>
          <dl v-if="amounts(event).length" class="as-settlement-audit__amounts">
            <div v-for="item in amounts(event)" :key="item.key" :class="`is-${item.tone}`"><dt>{{ item.label }}</dt><dd>{{ item.display }}</dd></div>
          </dl>
          <div v-if="event.reason" class="as-settlement-audit__reason"><span>{{ event.kind === 'opening' ? '历史说明' : ['correction', 'cancelled'].includes(event.kind) ? '更正原因' : '操作说明' }}</span><p>{{ event.reason }}</p></div>
          <details v-if="changes(event).length || event.createdBy || hasActor(event)" class="as-settlement-audit__changes">
            <summary><ChevronDown aria-hidden="true" /><span>{{ event.kind === 'opening' ? '查看期初记录' : '查看变更明细与票据' }}</span><small v-if="changes(event).length">{{ changes(event).length }} 项</small></summary>
            <table v-if="changes(event).length" :aria-label="`${typeFor(event).label} · 版本 ${event.revision} · 明细`">
              <thead><tr><th scope="col">字段</th><th v-if="event.kind !== 'opening'" scope="col">变更前</th><th scope="col">{{ event.kind === 'opening' ? '期初记录' : '变更后' }}</th></tr></thead>
              <tbody><tr v-for="row in changes(event)" :key="row.field"><th scope="row">{{ row.label }}</th><td v-if="event.kind !== 'opening'" class="as-settlement-audit__before">{{ row.before }}</td><td>{{ row.after }}</td></tr></tbody>
            </table>
            <p v-if="event.createdBy" class="as-settlement-audit__account">经办账号：{{ event.createdBy }}<template v-if="hasActor(event)"><br>实际操作账号：{{ event.createdActorId }}</template></p>
          </details>
        </article>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.as-settlement-audit {
  --ledger-space: var(--as-section-gap, 16px);
  --ledger-gap: var(--as-group-gap, 12px);
  --ledger-marker-size: 28px;
  --ledger-icon-size: 14px;
  --ledger-text-size: 13px;
  --ledger-caption-size: 12px;
  --ledger-radius: 8px;
  --ledger-line: var(--as-border);
  --ledger-soft: var(--as-soft);
  --ledger-text: var(--as-text);
  --ledger-muted: var(--as-muted);
  min-width: 0;
  border: 1px solid var(--ledger-line);
  border-radius: var(--ledger-radius);
  background: var(--as-panel);
  color: var(--ledger-text);
  font-size: var(--ledger-text-size);
  line-height: 1.6;
}
.as-settlement-audit__header { display: flex; min-width: 0; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--ledger-gap); border-bottom: 1px solid var(--ledger-line); padding: var(--ledger-space); }
.as-settlement-audit__header > div { min-width: 0; }
.as-settlement-audit__header h2 { margin: 0; font-size: 15px; font-weight: 700; }
.as-settlement-audit__header p { margin: 3px 0 0; color: var(--ledger-muted); font-size: var(--ledger-caption-size); overflow-wrap: anywhere; }
.as-settlement-audit__version, .as-settlement-audit__revision { flex-shrink: 0; border-radius: 4px; background: var(--ledger-soft); padding: 2px 8px; color: var(--ledger-muted); font-size: var(--ledger-caption-size); font-variant-numeric: tabular-nums; white-space: nowrap; }
.as-settlement-audit__timeline { margin: 0; padding: var(--ledger-space); list-style: none; }
.as-settlement-audit__event { position: relative; display: grid; min-width: 0; grid-template-columns: var(--ledger-marker-size) minmax(0, 1fr); column-gap: var(--ledger-gap); }
.as-settlement-audit__event::before { position: absolute; top: 0; bottom: 0; left: calc(var(--ledger-marker-size) / 2); width: 1px; background: var(--ledger-line); content: ""; }
.as-settlement-audit__event:first-child::before { top: calc(var(--ledger-marker-size) / 2); }
.as-settlement-audit__event:last-child::before { bottom: auto; height: calc(var(--ledger-space) + var(--ledger-marker-size) / 2); }
.as-settlement-audit__event:only-child::before { display: none; }
.as-settlement-audit__marker { z-index: 1; display: grid; width: var(--ledger-marker-size); height: var(--ledger-marker-size); place-items: center; border: 1px solid var(--ledger-line); border-radius: 50%; background: var(--ledger-soft); color: var(--ledger-muted); }
.as-settlement-audit__marker svg { width: var(--ledger-icon-size); height: var(--ledger-icon-size); }
.as-settlement-audit__event:first-child:not(.is-opening) .as-settlement-audit__marker { border-color: var(--as-primary); color: var(--as-primary); }
.as-settlement-audit__entry { min-width: 0; padding: 2px 0 var(--ledger-space); }
.as-settlement-audit__event + .as-settlement-audit__event .as-settlement-audit__entry { padding-top: var(--ledger-space); border-top: 1px solid var(--ledger-line); }
.as-settlement-audit__event + .as-settlement-audit__event .as-settlement-audit__marker { margin-top: var(--ledger-space); }
.as-settlement-audit__event:last-child .as-settlement-audit__entry { padding-bottom: 0; }
.as-settlement-audit__event-head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 4px var(--ledger-gap); }
.as-settlement-audit__event-head > div { display: flex; flex-wrap: wrap; align-items: center; gap: var(--ledger-gap); }
.as-settlement-audit__event-head h3 { margin: 0; font-size: 14px; font-weight: 700; }
.as-settlement-audit__event-head time { display: inline-flex; align-items: center; gap: 4px; color: var(--ledger-muted); font-size: var(--ledger-caption-size); font-variant-numeric: tabular-nums; }
.as-settlement-audit__operator { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 6px; margin: 6px 0 0; color: var(--ledger-muted); font-size: var(--ledger-caption-size); overflow-wrap: anywhere; }
.as-settlement-audit__operator strong { color: var(--ledger-text); font-weight: 500; }
.as-settlement-audit__actor { margin-left: 6px; }
.as-settlement-audit__event-head time svg, .as-settlement-audit__operator svg { width: var(--ledger-icon-size); height: var(--ledger-icon-size); flex-shrink: 0; }
.as-settlement-audit__amounts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--ledger-gap); margin: var(--ledger-gap) 0 0; padding: var(--ledger-gap); border-radius: 6px; background: var(--ledger-soft); }
.as-settlement-audit__amounts dt { color: var(--ledger-muted); font-size: var(--ledger-caption-size); }
.as-settlement-audit__amounts dd { margin: 2px 0 0; color: var(--ledger-text); font-size: 18px; font-weight: 650; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.as-settlement-audit__amounts .is-increase dd { color: var(--as-success); }
.as-settlement-audit__amounts .is-decrease dd { color: var(--as-danger); }
.as-settlement-audit__reason { margin-top: var(--ledger-gap); }
.as-settlement-audit__reason > span { color: var(--ledger-muted); font-size: var(--ledger-caption-size); }
.as-settlement-audit__reason p { margin: 2px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.as-settlement-audit__changes { margin-top: var(--ledger-gap); }
.as-settlement-audit__changes summary { display: flex; width: fit-content; max-width: 100%; min-height: 32px; align-items: center; gap: 6px; border-radius: 4px; color: var(--as-primary); font-size: var(--ledger-caption-size); cursor: pointer; list-style: none; }
.as-settlement-audit__changes summary::-webkit-details-marker { display: none; }
.as-settlement-audit__changes summary:focus-visible { outline: 2px solid var(--as-primary); outline-offset: 2px; }
.as-settlement-audit__changes summary > svg { width: var(--ledger-icon-size); height: var(--ledger-icon-size); flex-shrink: 0; transform: rotate(-90deg); }
.as-settlement-audit__changes[open] summary > svg { transform: none; }
.as-settlement-audit__changes summary small { color: var(--ledger-muted); font-size: inherit; }
.as-settlement-audit__changes table { width: 100%; margin-top: 6px; border-collapse: collapse; table-layout: fixed; font-size: var(--ledger-caption-size); }
.as-settlement-audit__changes th, .as-settlement-audit__changes td { border-bottom: 1px solid var(--ledger-line); padding: 8px; text-align: left; vertical-align: top; white-space: pre-wrap; overflow-wrap: anywhere; }
.as-settlement-audit__changes thead th { background: var(--ledger-soft); color: var(--ledger-muted); font-weight: 500; }
.as-settlement-audit__changes th:first-child { width: 28%; }
.as-settlement-audit__changes tbody th { color: var(--ledger-muted); font-weight: 400; }
.as-settlement-audit__before { color: var(--ledger-muted); }
.as-settlement-audit__account { margin: var(--ledger-gap) 0 0; color: var(--ledger-muted); font-size: var(--ledger-caption-size); overflow-wrap: anywhere; }
.as-settlement-audit__empty { display: grid; justify-items: center; gap: 6px; padding: calc(var(--ledger-space) * 3) var(--ledger-space); color: var(--ledger-muted); text-align: center; }
.as-settlement-audit__empty > svg { width: var(--ledger-marker-size); height: var(--ledger-marker-size); margin-bottom: 6px; }
.as-settlement-audit__empty strong { color: var(--ledger-text); font-size: 14px; font-weight: 500; }
.as-settlement-audit__empty p { margin: 0; font-size: var(--ledger-caption-size); }
</style>
