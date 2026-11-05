<script setup>
import { Check, LoaderCircle, Pencil, Plus, Save, X } from "lucide-vue-next";
import { watch } from "vue";

import {
  fieldSections,
  settingGroups,
  useFieldSettings,
} from "@/composables/useFieldSettings";

const emit = defineEmits(["notify", "dirty-change"]);
const settings = useFieldSettings({ notify: (message) => emit("notify", message) });

function draftFor(item) {
  return settings.drafts.value[item.id] || item;
}

function rowsForSection(section) {
  return settings.items.value.filter((item) => section.codes.includes(item.code));
}

function chooseGroup(group) {
  if (!settings.selectGroup(group)) emit("notify", "请先保存或取消当前修改");
}

watch(settings.dirty, (value) => emit("dirty-change", value), { immediate: true });
</script>

<template>
  <div class="field-settings">
    <aside class="group-list">
      <header>竞品采集设置</header>
      <button
        v-for="group in settingGroups"
        :key="group.id"
        type="button"
        :class="{ active: settings.activeGroup.value === group.id }"
        @click="chooseGroup(group.id)"
      >
        <strong>{{ group.label }}</strong>
        <span>{{ settings.rows.value.filter((item) => item.group === group.id).length }}</span>
      </button>
    </aside>

    <section class="setting-workspace">
      <header class="workspace-head">
        <div>
          <h2>{{ settings.section.value.label }}</h2>
          <p>{{ settings.section.value.description }}</p>
        </div>
        <div v-if="settings.editing.value" class="head-actions">
          <button
            type="button"
            class="btn btn-primary"
            :disabled="settings.saving.value || !settings.dirty.value"
            @click="settings.save"
          >
            <LoaderCircle v-if="settings.saving.value" class="spin" :size="14" />
            <Save v-else :size="14" />保存
          </button>
          <button type="button" class="btn" :disabled="settings.saving.value" @click="settings.cancelEditing">
            <X :size="14" />取消
          </button>
        </div>
        <button v-else-if="settings.activeGroup.value !== 'region'" type="button" class="btn btn-primary" @click="settings.startEditing">
          <Pencil :size="14" />编辑
        </button>
      </header>

      <div class="workspace-body">
        <div v-if="settings.loading.value" class="empty-state">正在加载字段设置...</div>
        <div v-else class="setting-table-wrap">
          <table v-if="settings.activeGroup.value === 'collection_field'" class="setting-table field-table">
            <colgroup><col class="section-col" /><col /><col class="state-col" /><col class="state-col" /></colgroup>
            <thead><tr><th>分组</th><th>字段名称</th><th>显示</th><th>必填</th></tr></thead>
            <tbody>
              <template v-for="section in fieldSections" :key="section.title">
                <tr v-for="(item, index) in rowsForSection(section)" :key="item.id">
                  <td v-if="index === 0" class="section-cell" :rowspan="rowsForSection(section).length">{{ section.title }}</td>
                  <td>
                    <input
                      v-if="settings.editing.value"
                      class="control field-name"
                      :value="draftFor(item).label"
                      :disabled="settings.saving.value"
                      @input="settings.patchDraft(item, { label: $event.target.value })"
                    />
                    <strong v-else>{{ item.label }}</strong>
                  </td>
                  <td class="center">
                    <button
                      type="button"
                      class="state-button"
                      :class="{ active: draftFor(item).enabled }"
                      :disabled="!settings.editing.value || settings.saving.value || settings.lockedFieldCodes.has(item.code)"
                      @click="settings.patchDraft(item, { enabled: !draftFor(item).enabled })"
                    ><Check v-if="draftFor(item).enabled" :size="12" />{{ draftFor(item).enabled ? '启用' : '关闭' }}</button>
                  </td>
                  <td class="center">
                    <button
                      type="button"
                      class="state-button"
                      :class="{ active: draftFor(item).required }"
                      :disabled="!settings.editing.value || settings.saving.value || settings.lockedFieldCodes.has(item.code) || !draftFor(item).enabled"
                      @click="settings.patchDraft(item, { required: !draftFor(item).required })"
                    ><Check v-if="draftFor(item).required" :size="12" />{{ draftFor(item).required ? '启用' : '关闭' }}</button>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>

          <table v-else class="setting-table option-table">
            <colgroup><col /><col class="option-state-col" /></colgroup>
            <thead><tr><th>选项名称</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="item in settings.items.value" :key="item.id">
                <td>
                  <input
                    v-if="settings.editing.value"
                    class="control field-name"
                    :value="draftFor(item).label"
                    :disabled="settings.saving.value"
                    @input="settings.patchDraft(item, { label: $event.target.value })"
                  />
                  <strong v-else>{{ item.label }}</strong>
                </td>
                <td class="center">
                  <button
                    type="button"
                    class="state-button"
                    :class="{ active: draftFor(item).enabled }"
                    :disabled="!settings.editing.value || settings.saving.value || (draftFor(item).enabled && settings.enabledCount.value === 1)"
                    @click="settings.patchDraft(item, { enabled: !draftFor(item).enabled })"
                  ><Check v-if="draftFor(item).enabled" :size="12" />{{ draftFor(item).enabled ? '启用' : '关闭' }}</button>
                </td>
              </tr>
              <tr v-if="settings.editing.value">
                <td><input v-model="settings.newLabel.value" class="control new-option" placeholder="输入新选项名称" /></td>
                <td class="new-hint"><Plus :size="13" />保存时新增</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.field-settings { display: grid; height: 100%; min-height: 0; grid-template-columns: 260px minmax(0, 1fr); overflow: hidden; border: 1px solid #dfe6ee; border-radius: 8px; background: #fff; }
.group-list { display: flex; min-height: 0; flex-direction: column; gap: 8px; border-right: 1px solid #e6ebf1; background: #f8fafc; padding: 10px; }
.group-list header { margin: -10px -10px 2px; border-bottom: 1px solid #e6ebf1; background: #fff; padding: 14px 16px; color: #0f172a; font-size: 13px; font-weight: 800; }
.group-list button { display: flex; min-height: 43px; align-items: center; justify-content: space-between; gap: 10px; border: 1px solid #edf1f5; border-radius: 6px; background: #fff; padding: 0 12px; color: #475569; text-align: left; }
.group-list button.active { border-color: #bfdbfe; background: #eff6ff; color: #1d4ed8; box-shadow: 0 1px 2px rgba(15, 23, 42, .04); }
.group-list strong { overflow: hidden; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.group-list span { color: #94a3b8; font-size: 10px; font-weight: 700; }
.setting-workspace { display: flex; min-width: 0; min-height: 0; flex-direction: column; }
.workspace-head { display: flex; min-height: 62px; align-items: center; justify-content: space-between; gap: 12px; border-bottom: 1px solid #e6ebf1; padding: 10px 16px; }
.workspace-head h2 { margin: 0; font-size: 15px; }
.workspace-head p { margin: 4px 0 0; color: #94a3b8; font-size: 10px; }
.head-actions { display: flex; gap: 7px; }
.workspace-body { min-height: 0; flex: 1; overflow: auto; background: #f8fafc; padding: 14px; }
.setting-table-wrap { overflow: auto; border: 1px solid #dfe6ee; border-radius: 7px; background: #fff; }
.setting-table { width: 100%; min-width: 700px; table-layout: fixed; border-collapse: collapse; font-size: 12px; }
.setting-table th { height: 38px; border-right: 1px solid #dfe6ee; border-bottom: 1px solid #dfe6ee; background: #f8fafc; padding: 0 12px; color: #64748b; font-size: 10px; text-align: left; }
.setting-table td { height: 47px; border-right: 1px solid #edf1f5; border-bottom: 1px solid #edf1f5; padding: 7px 12px; color: #334155; }
.setting-table th:last-child, .setting-table td:last-child { border-right: 0; }
.section-col { width: 136px; }.state-col { width: 128px; }.option-state-col { width: 160px; }
.section-cell { background: #f8fafc; color: #475569; font-weight: 800; }
.center { text-align: center; }.field-name { height: 32px; background: #fff; font-size: 12px; font-weight: 700; }
.state-button { display: inline-flex; width: 64px; height: 28px; align-items: center; justify-content: center; gap: 4px; border: 1px solid #d9e1ea; border-radius: 6px; background: #fff; color: #94a3b8; font-size: 10px; font-weight: 700; }
.state-button.active { border-color: #bfdbfe; background: #eff6ff; color: #1d4ed8; }
.state-button:disabled { cursor: default; opacity: 1; }
.new-option { height: 32px; border-style: dashed; border-color: #93c5fd; background: #eff6ff55; }
.new-hint { color: #2563eb !important; font-size: 10px; font-weight: 700; text-align: center; }
.new-hint svg { margin-right: 3px; vertical-align: -2px; }.spin { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
