import { computed, reactive, ref, shallowRef, watch } from "vue";

import { fetchCompetitorDetail, fetchCompetitors, mergeSubmission } from "@/features/competitiveApi";
import {
  compareParameterItems,
  parameterComparisonIdentity,
  parameterItemText,
  splitParameterText,
} from "@/features/competitorParameters";
import { matchesSearch } from "@/features/search";
import { submissionPatch } from "@/features/submissionPayload";

export const mergeFields = [
  { key: "brand", label: "竞品品牌" },
  { key: "name", label: "产品名称" },
  { key: "model", label: "产品型号" },
  { key: "price", label: "单价" },
  { key: "dealer", label: "经销商", multiline: true },
  { key: "advantage", label: "竞品优势", multiline: true },
  { key: "weakness", label: "竞品劣势", multiline: true },
  { key: "tactic", label: "销售应对策略", multiline: true },
  { key: "expires", label: "有效期至" },
];

function missing(value) {
  const text = String(value || "").trim();
  return !text || text === "待采集" || text === "型号待补充";
}

function compareStatus(existingValue, incomingValue) {
  const existing = String(existingValue || "").trim();
  const incoming = String(incomingValue || "").trim();
  if (existing === incoming) return "same";
  if (missing(existing) && !missing(incoming)) return "new";
  if (missing(incoming)) return "same";
  return "conflict";
}

function targetValues(detail) {
  return {
    brand: detail.competitor.brand,
    name: detail.competitor.name,
    model: detail.competitor.model,
    price: detail.competitor.price,
    dealer: detail.competitor.dealer,
    advantage: detail.advantage,
    weakness: detail.weakness,
    tactic: detail.tactic,
    expires: detail.competitor.expires,
  };
}

function parameterRows(detail, submission, createIndependentVersion) {
  const existingItems = (detail.parameters || []).map(parameterItemText).filter(Boolean);
  const incomingItems = splitParameterText(
    submission.competitorParameterText,
    { unique: true },
  );
  return compareParameterItems(incomingItems, existingItems).map((row, rowIndex) => ({
    ...row,
    key: `parameter-comparison-${rowIndex + 1}-${row.incomingIndex || 0}-${row.existingIndex || 0}`,
    existingItem: row.existing ? {
      key: `existing-parameter-${row.existingIndex}`,
      text: row.existing,
      sourceIndex: row.existingIndex,
      order: row.existingIndex - 1,
      included: !createIndependentVersion,
      segments: row.existingSegments,
    } : null,
    incomingItem: row.incoming ? {
      key: `incoming-parameter-${row.incomingIndex}`,
      text: row.incoming,
      sourceIndex: row.incomingIndex,
      order: existingItems.length + row.incomingIndex - 1,
      included: createIndependentVersion || row.status !== "same",
      segments: row.incomingSegments,
    } : null,
  }));
}

export function useMergeWorkspace(props, emit) {
  const targets = shallowRef([]);
  const targetId = shallowRef("");
  const targetVersionId = shallowRef("");
  const resolutionMode = shallowRef("mergeExisting");
  const detail = shallowRef(null);
  const dirty = shallowRef(false);
  const loading = shallowRef(false);
  const submitting = shallowRef(false);
  const query = shallowRef("");
  const choices = reactive({});
  const result = reactive({
    brand: "", name: "", model: "", price: "", dealer: "",
    advantage: "", weakness: "", tactic: "", expires: "",
  });
  const parameterComparisons = ref([]);
  let targetListRequest = 0;
  let targetDetailRequest = 0;

  const visibleTargets = computed(() => {
    return targets.value.filter((item) => matchesSearch(
      query.value,
      [item.brand, item.name, item.model],
    ));
  });
  const existing = computed(() => detail.value ? targetValues(detail.value) : {});
  const fieldStatuses = computed(() => Object.fromEntries(mergeFields.map((field) => [
    field.key,
    compareStatus(existing.value[field.key], props.submission?.[field.key]),
  ])));
  const statusCounts = computed(() => {
    const counts = { new: 0, conflict: 0, same: 0 };
    Object.values(fieldStatuses.value).forEach((status) => { counts[status] += 1; });
    parameterComparisons.value.forEach((row) => {
      if (row.status === "different") counts.conflict += 1;
      else if (row.status === "same") counts.same += 1;
      if (row.incomingStatus === "extra") counts.new += 1;
      if (row.existingStatus === "missing") counts.conflict += 1;
    });
    return counts;
  });
  const selectedParameterItems = computed(() => {
    const selected = parameterComparisons.value
      .flatMap((row) => [row.existingItem, row.incomingItem])
      .filter((item) => item?.included && item.text.trim())
      .sort((left, right) => left.order - right.order);
    const seen = new Set();
    return selected.filter((item) => {
      const key = parameterComparisonIdentity(item.text);
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  });
  const parameterDifferenceCounts = computed(() => parameterComparisons.value.reduce(
    (counts, row) => {
      if (row.status === "different") counts.different += 1;
      if (row.incomingStatus === "extra") counts.extra += 1;
      if (row.existingStatus === "missing") counts.missing += 1;
      return counts;
    },
    { extra: 0, different: 0, missing: 0 },
  ));
  const targetReady = computed(() => Boolean(
    targetId.value
    && detail.value
    && (resolutionMode.value === "newVersion" || targetVersionId.value),
  ));

  function initializeResult() {
    if (!detail.value || !props.submission) {
      parameterComparisons.value = [];
      return;
    }
    const current = targetValues(detail.value);
    const createIndependentVersion = resolutionMode.value === "newVersion";
    for (const field of mergeFields) {
      const incoming = props.submission[field.key] || "";
      if (createIndependentVersion) {
        result[field.key] = incoming;
        choices[field.key] = "source";
        continue;
      }
      const useSource = missing(current[field.key]) && !missing(incoming);
      result[field.key] = useSource ? incoming : current[field.key];
      choices[field.key] = useSource ? "source" : "existing";
    }
    parameterComparisons.value = parameterRows(
      detail.value,
      props.submission,
      createIndependentVersion,
    );
  }

  function markDirty() {
    dirty.value = true;
  }

  function selectTarget(id) {
    if (id === targetId.value) return;
    markDirty();
    targetId.value = id;
  }

  function selectResolutionMode(mode) {
    if (mode === resolutionMode.value) return;
    markDirty();
    resolutionMode.value = mode;
  }

  function updateResult(field, value) {
    if (result[field] === value) return;
    markDirty();
    result[field] = value;
  }

  async function loadTargets() {
    const requestId = ++targetListRequest;
    targetDetailRequest += 1;
    const submission = props.submission;
    targets.value = [];
    targetId.value = "";
    targetVersionId.value = "";
    resolutionMode.value = "mergeExisting";
    detail.value = null;
    loading.value = false;
    parameterComparisons.value = [];
    query.value = "";
    dirty.value = false;
    if (!submission) return;
    try {
      const first = await fetchCompetitors({
        page: 1,
        pageSize: 100,
        productId: submission.productId,
      });
      const rows = [...first.items];
      for (let page = 2; page <= first.pages; page += 1) {
        rows.push(...(await fetchCompetitors({
          page,
          pageSize: 100,
          productId: submission.productId,
        })).items);
      }
      if (requestId !== targetListRequest) return;
      targets.value = rows;
      targetId.value = submission.competitorId || "";
    } catch (reason) {
      if (requestId !== targetListRequest) return;
      emit("notify", reason.message || "归并目标加载失败");
    }
  }

  async function loadTarget(versionId = "") {
    const requestId = ++targetDetailRequest;
    if (!targetId.value || !props.submission) {
      detail.value = null;
      targetVersionId.value = "";
      parameterComparisons.value = [];
      return;
    }
    loading.value = true;
    try {
      const preferredVersionId = versionId || (
        String(props.submission.competitorId || "") === String(targetId.value)
          ? props.submission.competitorVersionId || ""
          : ""
      );
      const nextDetail = await fetchCompetitorDetail(targetId.value, preferredVersionId);
      if (requestId !== targetDetailRequest) return;
      detail.value = nextDetail;
      targetVersionId.value = detail.value.selectedVersion?.id || "";
      initializeResult();
    } catch (reason) {
      if (requestId !== targetDetailRequest) return;
      detail.value = null;
      targetVersionId.value = "";
      emit("notify", reason.message || "目标竞品加载失败");
    } finally {
      if (requestId === targetDetailRequest) loading.value = false;
    }
  }

  async function selectTargetVersion(versionId) {
    if (!versionId || versionId === targetVersionId.value) return;
    markDirty();
    await loadTarget(versionId);
  }

  function chooseField(field, choice) {
    const current = existing.value[field.key] || "";
    const incoming = props.submission?.[field.key] || "";
    let nextResult;
    if (choice === "existing") nextResult = current;
    else if (choice === "source") nextResult = incoming;
    else nextResult = current.trim() === incoming.trim()
      ? current.trim()
      : [current.trim(), incoming.trim()].filter(Boolean).join("\n");
    if (choices[field.key] === choice && result[field.key] === nextResult) return;
    markDirty();
    choices[field.key] = choice;
    result[field.key] = nextResult;
  }

  function toggleParameter(row, side, included) {
    const item = side === "existing" ? row.existingItem : row.incomingItem;
    if (!item || item.included === included) return;
    markDirty();
    item.included = included;
    if (!included || row.status !== "same") return;
    const counterpart = side === "existing" ? row.incomingItem : row.existingItem;
    if (counterpart) counterpart.included = false;
  }

  function setParameterSelection(source) {
    markDirty();
    parameterComparisons.value.forEach((row) => {
      if (row.existingItem) row.existingItem.included = source === "existing";
      if (row.incomingItem) row.incomingItem.included = source === "incoming";
    });
  }

  async function submit() {
    if (loading.value || !targetReady.value) return;
    if (!result.brand.trim() || !result.name.trim() || !result.model.trim()) {
      emit("notify", "请补全审核结果中的品牌、名称和型号");
      return;
    }
    const finalParameters = selectedParameterItems.value.map((item) => item.text.trim());
    submitting.value = true;
    try {
      const response = await mergeSubmission(props.submission.id, {
        competitorId: targetId.value,
        versionId: resolutionMode.value === "mergeExisting" ? targetVersionId.value : "",
        mode: resolutionMode.value,
        submission: submissionPatch(props.submission),
        result: { ...result, parameters: finalParameters },
      });
      emit("merged", response);
      emit("close");
    } catch (reason) {
      emit("notify", reason.message || "审核处理失败");
    } finally {
      submitting.value = false;
    }
  }

  watch(() => props.submission?.id, loadTargets, { immediate: true });
  watch(targetId, () => loadTarget());
  watch(resolutionMode, initializeResult);

  return {
    choices,
    detail,
    dirty,
    existing,
    fieldStatuses,
    loading,
    parameterComparisons,
    parameterDifferenceCounts,
    query,
    result,
    resolutionMode,
    submitting,
    selectedParameterItems,
    statusCounts,
    targetId,
    targetReady,
    targetVersionId,
    visibleTargets,
    chooseField,
    selectResolutionMode,
    selectTarget,
    selectTargetVersion,
    setParameterSelection,
    submit,
    toggleParameter,
    updateResult,
  };
}
