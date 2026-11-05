export const SETTINGS_STORAGE_KEY = "mj.afterSales.settings.draft.v1";
export const PROVIDER_TAGS_UPDATED_EVENT = "mj.afterSales.provider-tags-updated";
export const DEFAULT_PROVIDER_TAGS = Object.freeze([
  "讲台安装",
  "中控联调",
  "智慧板书",
  "录播联动",
  "平台接入",
]);

export function normalizeProviderTags(tags) {
  return [...new Set((Array.isArray(tags) ? tags : [])
    .map((tag) => String(tag || "").trim())
    .filter(Boolean))];
}

export function readProviderTags() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(SETTINGS_STORAGE_KEY) || "null");
    const tags = normalizeProviderTags(parsed?.tags);
    return tags.length ? tags : [...DEFAULT_PROVIDER_TAGS];
  } catch (_reason) {
    return [...DEFAULT_PROVIDER_TAGS];
  }
}

export function notifyProviderTagsUpdated(tags) {
  window.dispatchEvent(new CustomEvent(PROVIDER_TAGS_UPDATED_EVENT, {
    detail: { tags: normalizeProviderTags(tags) },
  }));
}
