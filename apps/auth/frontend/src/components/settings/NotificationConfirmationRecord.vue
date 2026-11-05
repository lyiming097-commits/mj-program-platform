<script setup>
import RobotMessageContent from "./RobotMessageContent.vue";
defineProps({ record: { type: Object, required: true } });
function time(value) {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "medium", timeZone: "Asia/Shanghai" }).format(new Date(value));
}
</script>

<template>
  <details class="notice-confirmation-record">
    <summary>确认记录</summary>
    <dl>
      <div><dt>确认人</dt><dd>{{ record.name || record.userId }}</dd></div>
      <div v-if="record.actorUserId !== record.userId"><dt>操作人</dt><dd>{{ record.actorName || record.actorUserId }}（代理操作）</dd></div>
      <div><dt>确认时间</dt><dd>{{ time(record.confirmedAt) }}</dd></div>
      <div><dt>确认声明</dt><dd>{{ record.statement }}</dd></div>
      <div v-if="record.enteredStatement"><dt>填写内容</dt><dd>{{ record.enteredStatement }}</dd></div>
      <div><dt>当时的通知标题</dt><dd>{{ record.contentSnapshot?.title }}</dd></div>
      <div><dt>当时的通知正文</dt><dd><RobotMessageContent :html="record.contentSnapshot?.contentHtml || ''" inline-images /></dd></div>
      <div v-if="record.contentSnapshot?.attachments?.length"><dt>当时的附件</dt><dd><ul><li v-for="file in record.contentSnapshot.attachments" :key="file.id">{{ file.name }}</li></ul></dd></div>
    </dl>
  </details>
</template>

<style scoped>
.notice-confirmation-record{margin-top:8px;white-space:normal;color:var(--mj-text,#0f172a);font-size:12px}.notice-confirmation-record summary{cursor:pointer;color:var(--mj-primary,#2563eb)}.notice-confirmation-record dl{display:grid;gap:12px;margin:12px 0 0}.notice-confirmation-record dt{margin-bottom:4px;color:var(--mj-muted,#64748b)}.notice-confirmation-record dd{margin:0;overflow-wrap:anywhere;line-height:1.6}.notice-confirmation-record ul{margin:0;padding-left:16px}
</style>
