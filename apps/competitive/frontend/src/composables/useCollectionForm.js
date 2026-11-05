import { computed, reactive, readonly, shallowRef } from "vue";

import {
  createSubmission,
  deleteCollectionDraft,
  fetchBootstrap,
  fetchLatestDraft,
  fetchProducts,
  saveCollectionDraft,
} from "@/features/competitiveApi";
import { normalizeParameterText } from "@/features/competitorParameters";
import { fileSnapshot, stableSnapshot } from "@/features/unsavedChanges";

function initialState() {
  return {
    productId: "",
    brand: "",
    name: "",
    model: "",
    price: "",
    dealer: "",
    customer: "",
    note: "",
    advantage: "",
    weakness: "",
    tactic: "",
    region: "",
    location: "",
    located: false,
    latitude: null,
    longitude: null,
    locationAccuracy: null,
    locatedAt: null,
    locationSource: "manual",
    validity: "一年",
    reminderOwner: "本人 + 区域经理",
    competitorParameterText: "",
  };
}

export function useCollectionForm() {
  const form = reactive(initialState());
  const files = shallowRef([]);
  const categories = reactive({});
  const products = shallowRef([]);
  const settings = shallowRef([]);
  const loading = shallowRef(false);
  const submitting = shallowRef(false);
  const savingDraft = shallowRef(false);
  const draftId = shallowRef("");
  const draftAttachments = shallowRef([]);
  const baselineSnapshot = shallowRef("");
  let baselineState;

  function fileKey(file) {
    return `${file.name}-${file.lastModified}-${file.size}`;
  }

  function collectionSnapshot() {
    return {
      form: { ...form },
      files: files.value.map(fileSnapshot),
      categories: files.value.map((file) => categories[fileKey(file)] || ""),
    };
  }

  function commitBaseline() {
    baselineState = {
      form: { ...form },
      files: [...files.value],
      categories: { ...categories },
      draftId: draftId.value,
      draftAttachments: [...draftAttachments.value],
    };
    baselineSnapshot.value = stableSnapshot(collectionSnapshot());
  }

  function discardChanges() {
    if (!baselineState) return;
    Object.assign(form, initialState(), baselineState.form);
    files.value = [...baselineState.files];
    Object.keys(categories).forEach((key) => delete categories[key]);
    Object.assign(categories, baselineState.categories);
    draftId.value = baselineState.draftId;
    draftAttachments.value = [...baselineState.draftAttachments];
  }

  const options = computed(() => {
    const grouped = {};
    for (const item of settings.value) {
      if (!item.enabled) continue;
      (grouped[item.group] ||= []).push(item);
    }
    return grouped;
  });
  const dirty = computed(() => (
    stableSnapshot(collectionSnapshot()) !== baselineSnapshot.value
  ));

  function collectionField(code, fallbackLabel, fallbackRequired = false) {
    const item = settings.value.find(
      (setting) => setting.group === "collection_field" && setting.code === code,
    );
    return {
      label: item?.label ?? fallbackLabel,
      enabled: item?.enabled ?? true,
      required: item?.required ?? fallbackRequired,
    };
  }

  function missingRequiredField(candidates) {
    for (const candidate of candidates) {
      const field = collectionField(
        candidate.code,
        candidate.fallbackLabel,
        candidate.fallbackRequired,
      );
      if (field.enabled && field.required && !candidate.filled) return field.label;
    }
    return "";
  }

  async function loadOptions() {
    loading.value = true;
    try {
      const [bootstrap, firstPage, savedDraft] = await Promise.all([
        fetchBootstrap(),
        fetchProducts({ page: 1, pageSize: 100 }),
        fetchLatestDraft(),
      ]);
      settings.value = bootstrap.settings || [];
      const allProducts = [...firstPage.items];
      for (let page = 2; page <= firstPage.pages; page += 1) {
        allProducts.push(...(await fetchProducts({ page, pageSize: 100 })).items);
      }
      products.value = allProducts;
      if (!form.validity) form.validity = options.value.validity?.[0]?.label || "一年";
      if (!form.reminderOwner) form.reminderOwner = options.value.reminder_owner?.[0]?.label || "本人 + 区域经理";
      if (savedDraft) {
        const draftPayload = { ...(savedDraft.payload || {}) };
        draftPayload.competitorParameterText = normalizeParameterText(
          draftPayload.competitorParameterText ?? draftPayload.competitorParameters,
        );
        delete draftPayload.competitorParameters;
        Object.assign(form, initialState(), draftPayload);
        draftId.value = savedDraft.id;
        draftAttachments.value = savedDraft.attachments || [];
      }
      commitBaseline();
    } finally { loading.value = false; }
  }

  function addFiles(fileList) {
    const next = Array.from(fileList || []);
    files.value = [...files.value, ...next].slice(0, 20);
    const defaultCategory = options.value.material_category?.[0]?.label || "待归类";
    next.forEach((file) => { categories[`${file.name}-${file.lastModified}-${file.size}`] = defaultCategory; });
  }

  function removeFile(index) {
    const file = files.value[index];
    if (file) delete categories[`${file.name}-${file.lastModified}-${file.size}`];
    files.value = files.value.filter((_, itemIndex) => itemIndex !== index);
  }

  function reset() {
    Object.assign(form, initialState());
    files.value = [];
    Object.keys(categories).forEach((key) => delete categories[key]);
    draftId.value = "";
    draftAttachments.value = [];
    commitBaseline();
  }

  function payload({ forDraft = false } = {}) {
    return {
      ...form,
      model: forDraft ? form.model.trim() : (form.model.trim() || "型号待补充"),
      price: forDraft ? form.price.trim() : (form.price.trim() || "待采集"),
      competitorParameterText: form.competitorParameterText,
      categories: files.value.map((file) => categories[`${file.name}-${file.lastModified}-${file.size}`] || "待归类"),
    };
  }

  async function saveDraft() {
    savingDraft.value = true;
    try {
      const saved = await saveCollectionDraft(payload({ forDraft: true }), files.value, draftId.value);
      draftId.value = saved.id;
      draftAttachments.value = saved.attachments || [];
      files.value = [];
      Object.keys(categories).forEach((key) => delete categories[key]);
      commitBaseline();
      return saved;
    } finally { savingDraft.value = false; }
  }

  async function discardDraft() {
    if (draftId.value) await deleteCollectionDraft(draftId.value);
    reset();
  }

  async function submit() {
    submitting.value = true;
    try {
      return await createSubmission(
        { ...payload(), ...(draftId.value ? { draftId: draftId.value } : {}) },
        files.value,
      );
    } finally { submitting.value = false; }
  }

  commitBaseline();

  return {
    form,
    files: readonly(files),
    categories,
    products: readonly(products),
    options,
    collectionField,
    missingRequiredField,
    loading: readonly(loading),
    submitting: readonly(submitting),
    savingDraft: readonly(savingDraft),
    draftId: readonly(draftId),
    draftAttachments: readonly(draftAttachments),
    dirty,
    loadOptions,
    addFiles,
    removeFile,
    reset,
    saveDraft,
    discardDraft,
    discardChanges,
    submit,
  };
}
