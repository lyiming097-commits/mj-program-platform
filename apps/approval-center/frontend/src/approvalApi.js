import { apiDelete, apiGet, apiPatch, apiPost } from "@/api";

const API_ROOT = "/api/approval-center";

function endpoint(path, params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    query.set(key, String(value));
  });
  const suffix = query.toString();
  return `${API_ROOT}/${String(path || "").replace(/^\/+|\/+$/g, "")}${suffix ? `?${suffix}` : ""}`;
}

export function itemsOf(payload, keys = []) {
  if (Array.isArray(payload)) return payload;
  for (const key of [...keys, "items", "results"]) {
    if (Array.isArray(payload?.[key])) return payload[key];
  }
  return [];
}

export function itemOf(payload, keys = []) {
  if (!payload || typeof payload !== "object") return null;
  for (const key of [...keys, "item"]) {
    if (payload?.[key] && typeof payload[key] === "object") return payload[key];
  }
  return payload;
}

export const approvalApi = {
  employeeDirectory: (categoryId = "") => apiGet(endpoint("directory/employees", { categoryId })),
  permissionDirectory: () => apiGet(endpoint("permissions/directory")),
  formOptions: (templateId) => apiGet(endpoint("directory/form-options", { templateId })),
  workspace: () => apiGet(endpoint("workspace")),
  categories: (params = {}) => apiGet(endpoint("categories", params)),
  createCategory: (payload) => apiPost(endpoint("categories"), payload),
  updateCategory: (id, payload) => apiPatch(endpoint(`categories/${encodeURIComponent(id)}`), payload),
  reorderCategories: (payload) => apiPost(endpoint("categories/reorder"), payload),
  categoryPermissions: (id) => apiGet(endpoint(`categories/${encodeURIComponent(id)}/permissions`)),
  updateCategoryPermissions: (id, payload) => apiPost(endpoint(`categories/${encodeURIComponent(id)}/permissions`), payload),
  templates: (params = {}) => apiGet(endpoint("templates", params)),
  template: (id, params = {}) => apiGet(endpoint(`templates/${encodeURIComponent(id)}`, params)),
  createTemplate: (payload) => apiPost(endpoint("templates"), payload),
  updateTemplate: (id, payload) => apiPatch(endpoint(`templates/${encodeURIComponent(id)}`), payload),
  reorderTemplates: (payload) => apiPost(endpoint("templates/reorder"), payload),
  publishTemplate: (id, payload = {}) => apiPost(endpoint(`templates/${encodeURIComponent(id)}/publish`), payload),
  templateVersions: (id) => apiGet(endpoint(`templates/${encodeURIComponent(id)}/versions`)),
  applications: (params = {}) => apiGet(endpoint("applications", params)),
  application: (id) => apiGet(endpoint(`applications/${encodeURIComponent(id)}`)),
  createApplication: (payload) => apiPost(endpoint("applications"), payload),
  actOnApplication: (id, action, payload = {}) => apiPost(
    endpoint(`applications/${encodeURIComponent(id)}/${action}`),
    payload,
  ),
  tasks: (params = {}) => apiGet(endpoint("tasks", params)),
  drafts: (params = {}) => apiGet(endpoint("drafts", params)),
  draft: (id) => apiGet(endpoint(`drafts/${encodeURIComponent(id)}`)),
  createDraft: (payload) => apiPost(endpoint("drafts"), payload),
  updateDraft: (id, payload) => apiPatch(endpoint(`drafts/${encodeURIComponent(id)}`), payload),
  deleteDraft: (id) => apiDelete(endpoint(`drafts/${encodeURIComponent(id)}`)),
};
