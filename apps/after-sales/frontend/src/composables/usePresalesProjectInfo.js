import { computed, reactive, watch } from "vue";
import { serviceApi } from "@/serviceApi";
import { useDebouncedAutosave } from "@/composables/useDebouncedAutosave";
import { PRESALES_PROJECT_LEVELS, PRESALES_PROJECT_URGENCIES } from "@/presalesProjectInfo";

const fields = { totalArea: "项目总面积", designArea: "设计面积" };

function areaErrors(values) {
  return Object.fromEntries(Object.entries(fields).map(([key, label]) => {
    const raw = values[key].trim();
    const valid = !raw || (/^(?:[0-9]+(?:\.[0-9]{0,2})?|\.[0-9]{1,2})$/.test(raw)
      && raw.length <= 32 && Number(raw) <= 9999999999.99);
    return [key, valid ? "" : `${label}须为非负数字，最多两位小数，且不超过 9999999999.99`];
  }));
}

function infoErrors(values) {
  const expected = values.expectedBidAt.trim();
  const expectedTime = new Date(`${expected}T00:00:00Z`);
  const validExpected = !expected || (/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(expected)
    && !expected.startsWith("0000") && Number.isFinite(expectedTime.getTime())
    && expectedTime.toISOString().slice(0, 10) === expected);
  return { ...areaErrors(values), projectLevel: !values.projectLevel || PRESALES_PROJECT_LEVELS.includes(values.projectLevel)
    ? "" : "请选择有效的项目等级",
    urgency: !values.urgency || PRESALES_PROJECT_URGENCIES.includes(values.urgency) ? "" : "请选择有效的紧急程度",
    expectedBidAt: validExpected ? "" : "请选择有效的预计招标日期" };
}

export function usePresalesProjectInfo({ project, enabled, beforeSave, onSaved, onError }) {
  const values = reactive({ totalArea: "", designArea: "", projectLevel: "", urgency: "", expectedBidAt: "" });
  const editable = computed(() => Boolean(enabled() && project()?.permissions?.canManage && !project()?.deletedAt));
  const errors = computed(() => infoErrors(values));
  let hydrating = false;
  function snapshot() {
    return { projectId: project()?.id, totalArea: values.totalArea.trim(), designArea: values.designArea.trim(),
      projectLevel: values.projectLevel, urgency: values.urgency, expectedBidAt: values.expectedBidAt.trim() };
  }
  const { saving, pending, reset, schedule, flush } = useDebouncedAutosave(async draft => {
    const invalid = Object.values(infoErrors(draft)).find(Boolean);
    if (invalid) throw new Error(invalid);
    await beforeSave();
    if (!editable.value || String(project()?.id) !== String(draft.projectId)) throw new Error("项目已变更，请重新打开后填写项目信息");
    const response = await serviceApi.updatePresalesProjectInfo(draft.projectId, {
      totalArea: draft.totalArea || null, designArea: draft.designArea || null, projectLevel: draft.projectLevel, urgency: draft.urgency,
      expectedBidAt: draft.expectedBidAt,
    }, project().draftVersion);
    if (String(project()?.id) === String(draft.projectId)) onSaved(response.item || response);
  }, { onError });

  function restore() {
    hydrating = true;
    const info = project()?.businessData?.projectInfo || project()?.business_data?.projectInfo || {};
    Object.assign(values, Object.fromEntries([...Object.keys(fields), "projectLevel", "urgency", "expectedBidAt"].map(key => [key, info[key] == null ? "" : String(info[key])])));
    reset(snapshot());
    hydrating = false;
  }
  watch(() => [project()?.id, project()?.businessData?.projectInfo, project()?.business_data?.projectInfo], (next, previous) => {
    if (next[0] !== previous?.[0] || (!pending.value && !saving.value)) restore();
  }, { immediate: true, deep: true, flush: "sync" });
  watch(values, () => {
    if (!hydrating && editable.value) schedule(snapshot());
  }, { deep: true, flush: "sync" });

  return { values, editable, errors, saving, pending, flush, discard: restore };
}
