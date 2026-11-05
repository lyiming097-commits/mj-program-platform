import { computed, onMounted, shallowRef } from "vue";

import { createSetting, fetchSettings, patchSetting } from "@/features/competitiveApi";

export const settingGroups = [
  { id: "collection_field", label: "采集字段", description: "名称、显示状态和必填规则" },
  { id: "region", label: "采集地区", description: "全国 34 个省级行政区，统一固定选项" },
  { id: "material_category", label: "资料归属", description: "附件资料分类" },
  { id: "validity", label: "资料有效期", description: "资料有效期限" },
  { id: "reminder_owner", label: "提醒责任人", description: "到期提醒对象" },
];

export const fieldSections = [
  { title: "基础信息", codes: ["brand", "name", "model", "price", "attachments"] },
  { title: "产品关联", codes: ["product_id"] },
  { title: "渠道与现场", codes: ["dealer", "customer", "note"] },
  { title: "竞争分析", codes: ["competitor_parameters", "advantage", "weakness", "tactic"] },
  { title: "资料与提交", codes: ["material_category", "region", "location", "validity", "reminder_owner"] },
];

const lockedFieldCodes = new Set([
  "brand",
  "name",
  "product_id",
  "material_category",
  "region",
  "location",
]);

function itemDraft(item) {
  return { label: item.label, enabled: item.enabled, required: item.required };
}

export function useFieldSettings({ notify = () => {} } = {}) {
  const loading = shallowRef(true);
  const rows = shallowRef([]);
  const activeGroup = shallowRef("collection_field");
  const editing = shallowRef(false);
  const saving = shallowRef(false);
  const drafts = shallowRef({});
  const newLabel = shallowRef("");

  const items = computed(() => rows.value
    .filter((item) => item.group === activeGroup.value)
    .sort((left, right) => left.position - right.position));
  const section = computed(() => settingGroups.find(
    (item) => item.id === activeGroup.value,
  ) || settingGroups[0]);
  const dirty = computed(() => editing.value && (
    Boolean(newLabel.value.trim())
    || items.value.some((item) => {
      const draft = drafts.value[item.id];
      return Boolean(draft && (
        draft.label.trim() !== item.label
        || draft.enabled !== item.enabled
        || draft.required !== item.required
      ));
    })
  ));
  const enabledCount = computed(() => items.value.filter(
    (item) => (drafts.value[item.id] || item).enabled,
  ).length);

  async function load() {
    loading.value = true;
    try {
      rows.value = await fetchSettings();
    } catch (reason) {
      notify(reason.message || "字段设置加载失败");
    } finally {
      loading.value = false;
    }
  }

  function startEditing() {
    drafts.value = Object.fromEntries(items.value.map((item) => [item.id, itemDraft(item)]));
    newLabel.value = "";
    editing.value = true;
  }

  function cancelEditing() {
    drafts.value = {};
    newLabel.value = "";
    editing.value = false;
  }

  function selectGroup(group) {
    if (group === activeGroup.value) return true;
    if (dirty.value) return false;
    cancelEditing();
    activeGroup.value = group;
    return true;
  }

  function patchDraft(item, patch) {
    drafts.value = {
      ...drafts.value,
      [item.id]: { ...(drafts.value[item.id] || itemDraft(item)), ...patch },
    };
  }

  async function save() {
    if (saving.value) return;
    const invalid = items.value.find((item) => !(
      drafts.value[item.id]?.label ?? item.label
    ).trim());
    if (invalid) {
      notify("字段或选项名称不能为空");
      return;
    }
    const changed = items.value.filter((item) => {
      const draft = drafts.value[item.id];
      return draft && (
        draft.label.trim() !== item.label
        || draft.enabled !== item.enabled
        || draft.required !== item.required
      );
    });
    if (!changed.length && !newLabel.value.trim()) {
      cancelEditing();
      return;
    }
    saving.value = true;
    try {
      const savedRows = await Promise.all(changed.map((item) => {
        const draft = drafts.value[item.id];
        return patchSetting(item.id, {
          label: draft.label.trim(),
          enabled: draft.enabled,
          required: draft.required,
        });
      }));
      const savedById = new Map(savedRows.map((item) => [item.id, item]));
      rows.value = rows.value.map((item) => savedById.get(item.id) || item);
      if (activeGroup.value !== "collection_field" && newLabel.value.trim()) {
        const created = await createSetting({
          group: activeGroup.value,
          label: newLabel.value.trim(),
          enabled: true,
          required: false,
          position: items.value.length,
        });
        rows.value = [...rows.value, created];
      }
      cancelEditing();
      notify("设置已保存");
    } catch (reason) {
      notify(reason.message || "保存失败，请稍后重试");
    } finally {
      saving.value = false;
    }
  }

  onMounted(load);

  return {
    loading,
    rows,
    activeGroup,
    editing,
    saving,
    drafts,
    newLabel,
    items,
    section,
    dirty,
    enabledCount,
    lockedFieldCodes,
    startEditing,
    cancelEditing,
    selectGroup,
    patchDraft,
    save,
  };
}
