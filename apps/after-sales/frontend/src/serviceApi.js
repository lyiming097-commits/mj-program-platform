import { apiDelete, apiGet, apiPatch, apiPost, apiUpload } from "@/api";
import { clearProjectListCache } from "@/projectListCache";

const API_ROOT = "/api/after-sales";

const PROJECT_NODES = {
  midsales: [
    "midsales-project",
    "construction-work",
    "furniture-install",
    "device-install",
    "device-debug",
    "school-support",
    "project-acceptance",
    "midsales-project-end",
  ],
  aftersales: ["onsite-service", "mail-service", "school-inspection"],
};

const FEEDBACK_TYPES = {
  "现场问题": "issue",
  "资料建议": "resource_suggestion",
  "奖励申请": "reward_application",
  "服务反馈": "service_report",
};

function endpoint(path = "") {
  const normalized = String(path).replace(/^\/+|\/+$/g, "");
  return normalized ? `${API_ROOT}/${normalized}` : API_ROOT;
}

function normalizedParams(params = {}) {
  const result = { ...params };
  if ("page_size" in result) {
    result.pageSize = result.page_size;
    delete result.page_size;
  }
  if ("service_type" in result) {
    result.type = result.service_type;
    delete result.service_type;
  }
  if (result.status === "active") result.status = "in_progress";
  return result;
}

function withQuery(path, params = {}) {
  const query = new URLSearchParams();
  Object.entries(normalizedParams(params)).forEach(([key, value]) => {
    if (value === "" || value === null || value === undefined) return;
    if (Array.isArray(value)) {
      value.filter(Boolean).forEach((item) => query.append(key, String(item)));
      return;
    }
    query.set(key, String(value));
  });
  const suffix = query.toString();
  return suffix ? `${endpoint(path)}?${suffix}` : endpoint(path);
}

import { collectionRows } from "./collectionPagination.js";
export { collectionRows, allCollectionRows } from "./collectionPagination.js";

export function collectionCount(payload) {
  return Number(payload?.count ?? payload?.total ?? collectionRows(payload).length) || 0;
}

const MAX_DATABASE_ID = "9223372036854775807";

export function normalizeDatabaseId(value) {
  const raw = String(value ?? "").trim();
  if (!/^[0-9]+$/.test(raw)) return "";
  const normalized = raw.replace(/^0+/, "");
  if (!normalized) return "";
  if (
    normalized.length > MAX_DATABASE_ID.length
    || (normalized.length === MAX_DATABASE_ID.length && normalized > MAX_DATABASE_ID)
  ) return "";
  return normalized;
}

function requiredDatabaseId(value, label) {
  const normalized = normalizeDatabaseId(value);
  if (!normalized) throw new Error(`${label}无效`);
  return normalized;
}

export async function fetchMallProjectSolutionUrl(sourceCrmId) {
  const sourceId = String(sourceCrmId ?? "").trim();
  if (!sourceId) throw new Error("本项目未关联 CRM，暂无对应商城方案");
  // Use the same authorized resolver as CRM's "打开方案" entry. CRM checks
  // visibility and Mall owns the mapping, including legacy linked projects.
  const payload = await apiGet(`/api/crm/opportunities/${encodeURIComponent(sourceId)}/solution-products`);
  if (String(payload?.opportunityId ?? "") !== sourceId) throw new Error("商城返回的项目关联无效");
  const rawUrl = String(payload?.projectDetailUrl || "").trim();
  if (!rawUrl) {
    const error = new Error("商城尚未关联此 CRM 项目，请在商城同步后重试");
    error.code = "MALL_PROJECT_NOT_LINKED";
    throw error;
  }
  const target = new URL(rawUrl, window.location.origin);
  if (!["http:", "https:"].includes(target.protocol) || target.username || target.password
    || target.pathname !== "/maijie-mall/" || target.search
    || !/^#\/opportunity\/[1-9][0-9]*\/solution(?:\/[1-9][0-9]*)?(?:\?[^#]*)?$/.test(target.hash)) {
    throw new Error("商城返回的方案地址无效");
  }
  // Mall may return its configured public hostname while the platform was
  // opened through another alias. Only navigate to its route on this origin.
  return `${target.pathname}${target.hash}`;
}

function sourceFeeAmount(value) {
  if (value === null || value === undefined || value === "") return null;
  if (!["number", "string"].includes(typeof value) || !String(value).trim()) throw new Error("费用来源金额无效");
  const amount = Number(value);
  if (!Number.isFinite(amount)) throw new Error("费用来源金额无效");
  return amount;
}

export async function fetchPresalesEstimatedFee(sourceCrmId) {
  const sourceId = String(sourceCrmId ?? "").trim();
  if (!sourceId) return null;
  const payload = await apiGet(`/api/crm/opportunities/${encodeURIComponent(sourceId)}`);
  if (String(payload?.item?.id ?? "") !== sourceId) throw new Error("CRM 返回的项目关联无效");
  // Same source as Mall's gray expected_amount; never use the Mall quote fallback.
  return sourceFeeAmount(payload.item.amount);
}

export async function fetchPresalesMallFees(sourceCrmId) {
  const sourceId = String(sourceCrmId ?? "").trim();
  if (!sourceId) return { externalQuote: null, actualFee: null };
  // CRM authorizes this effective user's scope; Mall owns the aggregation of
  // all current linked project solutions. Do not add versions or use own-product A1.
  const payload = await apiGet(`/api/crm/opportunities/mall-amounts?opportunityId=${encodeURIComponent(sourceId)}`);
  if (!Array.isArray(payload?.items)) throw new Error("商城返回的项目费用无效");
  const rows = payload.items.filter(item => String(item?.opportunityId ?? "") === sourceId);
  if (rows.length > 1) throw new Error("商城返回了重复项目费用");
  return { externalQuote: sourceFeeAmount(rows[0]?.salespersonQuoteTotal), actualFee: sourceFeeAmount(rows[0]?.a1Total) };
}

function list(path, params) {
  return apiGet(withQuery(path, params));
}

function detail(path, id) {
  return apiGet(endpoint(`${path}/${encodeURIComponent(id)}`));
}

function create(path, payload) {
  const task = apiPost(endpoint(path), payload);
  return path === "projects" || path.startsWith("projects/") ? invalidateProjectListAfter(task) : task;
}

function update(path, id, payload) {
  const task = apiPatch(endpoint(`${path}/${encodeURIComponent(id)}`), payload);
  return path === "projects" ? invalidateProjectListAfter(task) : task;
}

async function invalidateProjectListAfter(task) {
  const response = await task;
  clearProjectListCache();
  return response;
}

function projectPayload(payload = {}) {
  const serviceType = payload.serviceType || payload.service_type;
  const result = {
    serviceType,
    name: payload.name,
    customer: payload.customer ?? payload.customer_name,
    ownerUserId: payload.ownerUserId ?? payload.owner_user_id,
    ownerName: payload.ownerName ?? payload.owner_name,
    address: payload.address,
    province: payload.province,
    summary: payload.summary ?? payload.description,
    plannedStartDate: payload.plannedStartDate ?? payload.planned_start_date,
    plannedEndDate: payload.plannedEndDate ?? payload.planned_end_date,
    businessData: payload.businessData ?? payload.business_data,
    expectedUpdatedAt: payload.expectedUpdatedAt,
    expectedDraftVersion: payload.expectedDraftVersion,
  };
  if (serviceType === "midsales" && Array.isArray(payload.enabled_node_ids)) {
    result.disabledNodeKeys = PROJECT_NODES.midsales.filter((key) => !payload.enabled_node_ids.includes(key));
  }
  if (serviceType === "aftersales" && payload.service_node_id) {
    result.disabledNodeKeys = PROJECT_NODES.aftersales.filter((key) => key !== payload.service_node_id);
    result.businessData = { ...(result.businessData || {}), serviceNodeKey: payload.service_node_id };
  }
  return Object.fromEntries(Object.entries(result).filter(([, value]) => value !== undefined));
}

function ticketPayload(payload = {}) {
  return {
    projectId: payload.projectId ?? payload.project_id,
    nodeKey: payload.nodeKey ?? payload.node_key,
    title: payload.title,
    ticketType: payload.ticketType ?? payload.type,
    priority: payload.priority,
    ownerUserId: payload.ownerUserId ?? payload.owner_user_id,
    ownerName: payload.ownerName ?? payload.owner_name,
    description: payload.description ?? payload.content ?? payload.note,
    businessData: payload.businessData ?? payload.business_data ?? {},
  };
}

function feedbackPayload(payload = {}) {
  const feedbackType = payload.feedbackType ?? payload.type;
  return {
    projectId: payload.projectId ?? payload.project_id,
    nodeKey: payload.nodeKey ?? payload.node_key,
    providerId: payload.providerId ?? payload.provider_id,
    title: payload.title,
    feedbackType: FEEDBACK_TYPES[feedbackType] || feedbackType,
    content: payload.content,
    businessData: payload.businessData ?? payload.business_data ?? {},
  };
}

function settlementPayload(payload = {}) {
  return {
    projectId: payload.projectId ?? payload.project_id,
    sourceNodeId: payload.sourceNodeId ?? payload.source_node_id ?? payload.nodeId ?? payload.node_id,
    sourceAssignmentId: payload.sourceAssignmentId ?? payload.source_assignment_id ?? payload.assignmentId ?? payload.assignment_id,
    bearer: payload.bearer,
    serviceContent: payload.serviceContent ?? payload.service_content ?? payload.project_name,
    budgetAmount: payload.budgetAmount ?? payload.budget_amount,
    finalAmount: payload.finalAmount ?? payload.final_amount,
    orderAmount: payload.orderAmount ?? payload.order_amount,
    receivedAmount: payload.receivedAmount ?? payload.received_amount,
    invoiceDueAmount: payload.invoiceDueAmount ?? payload.invoice_due_amount ?? payload.final_amount,
    invoicedAmount: payload.invoicedAmount ?? payload.invoice_amount,
    invoiceType: payload.invoiceType ?? payload.invoice_type,
    invoiceNumber: payload.invoiceNumber ?? payload.invoice_number,
    subjectType: payload.subjectType ?? payload.subject_type,
    subjectName: payload.subjectName ?? payload.subject_name,
    subjectId: payload.subjectId,
    expectedRevision: payload.expectedRevision,
    correctionReason: payload.correctionReason,
    relatedProjectId: payload.relatedProjectId ?? payload.related_project_id,
    remark: payload.remark,
    status: payload.status,
  };
}

export const serviceApi = {
  dashboard: (params = {}) => apiGet(withQuery("dashboard", params)),

  listProjects: (params = {}) => list("projects", params),
  presalesStatistics: (params = {}) => list("presales/statistics", params),
  getProject: (id) => detail("projects", id),
  getPresalesMaterials: (id) => apiGet(endpoint(`projects/${encodeURIComponent(id)}/presales-materials`)),
  createProject: (payload) => create("projects", projectPayload(payload)),
  updateProject: (id, payload) => update("projects", id, projectPayload(payload)),
  updatePresalesAreas: (id, areas, expectedDraftVersion) => update("projects", id, {
    presalesAreas: areas, expectedDraftVersion,
  }),
  updatePresalesProjectInfo: (id, info, expectedDraftVersion) => update("projects", id, {
    presalesProjectInfo: info, expectedDraftVersion,
  }),
  updateRelatedProducts: (id, productIds) => apiPatch(
    endpoint(`projects/${encodeURIComponent(id)}/related-products`),
    { productIds },
  ),
  updateNodeRelatedProducts: (id, nodeKey, productIds) => apiPatch(
    endpoint(`projects/${encodeURIComponent(id)}/nodes/${encodeURIComponent(nodeKey)}/related-products`),
    { productIds },
  ),
  deleteProject: (id) => invalidateProjectListAfter(apiDelete(endpoint(`projects/${encodeURIComponent(id)}`))),
  listProductCatalog: (params = {}) => list("product-catalog", params),
  getProductCatalogItem: (id) => detail("product-catalog", id),
  updateProjectNode: (id, nodeKey, payload) => invalidateProjectListAfter(apiPatch(
    endpoint(`projects/${encodeURIComponent(id)}/nodes/${encodeURIComponent(nodeKey)}`),
    payload,
  )),
  projectRoundAction: (id, nodeKey, operation, payload, { reasonFiles = [] } = {}) => {
    const path = endpoint(`projects/${encodeURIComponent(id)}/nodes/${encodeURIComponent(nodeKey)}/rounds/${operation}`);
    if (!reasonFiles.length) return invalidateProjectListAfter(apiPost(path, payload));
    const form = new FormData();
    form.append("payload", JSON.stringify(payload));
    reasonFiles.forEach(file => form.append("reasonFiles", file, file.name));
    return invalidateProjectListAfter(apiUpload(path, form, { timeoutMs: 600_000 }));
  },
  roundShareConfig: (url, jsApiList) => apiGet(`/api/auth/dingtalk/jsapi_config?${new URLSearchParams({ url, jsApiList })}`),
  projectAction: (id, actionName, payload = {}) => {
    if (actionName === "assign") {
      return create(`projects/${encodeURIComponent(id)}/assignments`, {
        expectedUpdatedAt: payload.expectedUpdatedAt,
        nodeKey: payload.nodeKey ?? payload.node_key,
        providerId: payload.providerId ?? payload.provider_id ?? payload.member_id ?? payload.assignee_id,
        role: payload.role || "",
        note: payload.note || payload.remark || "",
        plannedStartDate: payload.plannedStartDate ?? payload.planned_start_date,
        standardDuration: payload.standardDuration ?? payload.standard_duration,
      });
    }
    if (actionName === "return") {
      return create(`projects/${encodeURIComponent(id)}/reopen`, {
        nodeKey: payload.nodeKey ?? payload.node_key,
        note: payload.note || "",
      });
    }
    if (actionName === "submit_version") {
      const nodeKey = payload.nodeKey ?? payload.node_key;
      return create(
        `projects/${encodeURIComponent(id)}/nodes/${encodeURIComponent(nodeKey)}/version`,
        {
          note: payload.note || "",
          plannedStartAt: payload.plannedStartAt,
          plannedEndAt: payload.plannedEndAt,
          actualStartAt: payload.actualStartAt,
          actualEndAt: payload.actualEndAt,
          estimatedFee: payload.estimatedFee,
          actualFee: payload.actualFee,
          businessData: payload.businessData,
          expectedUpdatedAt: payload.expectedUpdatedAt,
        },
      );
    }
    if (actionName === "reject_completion") {
      return create(`projects/${encodeURIComponent(id)}/reject-completion`, {
        nodeKey: payload.nodeKey ?? payload.node_key,
        note: payload.note || "",
      });
    }
    if (actionName === "select_service_type") {
      return create(`projects/${encodeURIComponent(id)}/select-service`, {
        nodeKey: payload.serviceNodeKey ?? payload.service_node_id,
        note: payload.note || "",
      });
    }
    if (actionName === "start") {
      return create(`projects/${encodeURIComponent(id)}/start`, {
        nodeKey: payload.nodeKey ?? payload.node_key,
      });
    }
    return create(`projects/${encodeURIComponent(id)}/advance`, {
      nodeKey: payload.nodeKey ?? payload.node_key,
      note: payload.note || "",
      plannedStartAt: payload.plannedStartAt,
      plannedEndAt: payload.plannedEndAt,
      actualStartAt: payload.actualStartAt,
      actualEndAt: payload.actualEndAt,
      estimatedFee: payload.estimatedFee,
      actualFee: payload.actualFee,
      businessData: payload.businessData,
      expectedUpdatedAt: payload.expectedUpdatedAt,
      outcome: payload.outcome,
    });
  },
  listPresalesApprovals: (projectId, nodeKey) => list(
    `projects/${encodeURIComponent(projectId)}/nodes/${encodeURIComponent(nodeKey)}/approvals`,
  ),
  createPresalesApproval: (projectId, nodeKey, payload) => create(
    `projects/${encodeURIComponent(projectId)}/nodes/${encodeURIComponent(nodeKey)}/approvals`,
    payload,
  ),
  updatePresalesApproval: (projectId, nodeKey, stepId, payload) => apiPatch(
    endpoint(`projects/${encodeURIComponent(projectId)}/nodes/${encodeURIComponent(nodeKey)}/approvals/${encodeURIComponent(stepId)}`),
    payload,
  ),
  deletePresalesApproval: (projectId, nodeKey, stepId) => apiDelete(
    endpoint(`projects/${encodeURIComponent(projectId)}/nodes/${encodeURIComponent(nodeKey)}/approvals/${encodeURIComponent(stepId)}`),
  ),
  employeeDirectory: () => apiGet(endpoint("employees/directory")),

  listTeamMembers: (params = {}) => list("providers", params),
  getTeamMember: (id) => detail("providers", id),
  updateTeamMember: (id, payload) => update("providers", id, payload),
  capabilityCatalog: () => apiGet(endpoint("capabilities")),
  updateCapabilityCatalog: (payload) => apiPatch(endpoint("capabilities"), payload),
  providerTagCatalog: () => apiGet(endpoint("provider-tags")),
  updateProviderTagCatalog: (payload) => apiPatch(endpoint("provider-tags"), payload),
  providerMe: () => apiGet(endpoint("providers/me")),
  applyProvider: (payload) => create("providers/apply", payload),

  listTickets: (params = {}) => list("tickets", params),
  getTicket: (id) => detail("tickets", id),
  createTicket: (payload) => create("tickets", ticketPayload(payload)),
  updateTicket: (id, payload) => update("tickets", id, ticketPayload(payload)),
  ticketAction: (id, actionName, payload = {}) => {
    const statuses = {
      start: "in_progress",
      submit: "pending_review",
      complete: "completed",
      return: "rejected",
    };
    return create(`tickets/${encodeURIComponent(id)}/transition`, {
      status: statuses[actionName] || actionName,
      note: payload.note || "",
    });
  },
  addTicketMessage: (id, content) => create(`tickets/${encodeURIComponent(id)}/messages`, { content }),

  listFeedback: (params = {}) => list("feedback", params),
  createFeedback: (payload) => create("feedback", feedbackPayload(payload)),
  updateFeedback: (id, payload) => create(`feedback/${encodeURIComponent(id)}/review`, {
    status: payload.status ?? payload.decision,
    reviewNote: payload.reviewNote ?? payload.review_note ?? payload.note,
    reward: payload.reward || {},
  }),
  createRating: (payload) => create("ratings", {
    projectId: payload.projectId ?? payload.project_id,
    nodeKey: payload.nodeKey ?? payload.node_key,
    providerId: payload.providerId ?? payload.provider_id,
    rating: payload.rating,
  }),

  listRewards: (params = {}) => list("rewards", params),
  listRewardPrizes: () => apiGet(endpoint("reward-prizes")),
  rewardPrizeOptions: () => apiGet(endpoint("reward-prizes/options")),
  createRewardPrize: (payload) => create("reward-prizes", payload),
  updateRewardPrize: (id, payload) => apiPatch(endpoint(`reward-prizes/${encodeURIComponent(id)}`), payload),
  createReward: (payload) => create("rewards", payload),
  updateReward: (id, payload) => create(`rewards/${encodeURIComponent(id)}/transition`, payload),
  rewardAction: (id, actionName, payload = {}) => {
    const statuses = { approve: "approved", issue: "issued", reject: "rejected" };
    return create(`rewards/${encodeURIComponent(id)}/transition`, {
      status: statuses[actionName] || actionName,
      note: [payload.tracking_no, payload.note].filter(Boolean).join(" · "),
    });
  },

  listSettlements: (params = {}) => list("settlements", params),
  listSettlementSources: (params = {}) => list("settlement-sources", params),
  settlementCompanies: () => list("settlement-companies"),
  settlementProjects: (params = {}) => list("settlement-projects", params),
  getSettlement: (id) => detail("settlements", id),
  createSettlement: (payload) => create("settlements", settlementPayload(payload)),
  updateSettlement: (id, payload) => update("settlements", id, settlementPayload(payload)),

  listMessageConversations: (params = {}) => list("messages", params),
  listProjectMessages: (projectId, nodeKey = "", params = {}) => list(
    `projects/${encodeURIComponent(projectId)}/messages`,
    { ...params, nodeKey },
  ),
  sendProjectMessage: (projectId, nodeKey, content) => create(
    `projects/${encodeURIComponent(projectId)}/messages`,
    { nodeKey, content },
  ),
  markProjectMessagesRead: (projectId, nodeKey, throughId = null) => create(
    `projects/${encodeURIComponent(projectId)}/messages/read`,
    { nodeKey, throughId },
  ),
  listMidsalesProofs: (projectId, nodeKey, params = {}) => list(
    `projects/${encodeURIComponent(projectId)}/nodes/${encodeURIComponent(nodeKey)}/proofs`,
    params,
  ),
  reviewMidsalesProof: (projectId, nodeKey, proofType, status, opinion = "") => create(
    `projects/${encodeURIComponent(projectId)}/nodes/${encodeURIComponent(nodeKey)}/proofs/${encodeURIComponent(proofType)}/review`,
    { status, opinion },
  ),

  listMaterials: (params = {}) => list("resources", params),
  getMaterial: (id) => detail("resources", id),
  createMaterial: (payload) => create("resources", payload),
  updateMaterial: (id, payload) => update("resources", id, payload),
  deleteMaterial: (id) => apiDelete(endpoint(`resources/${encodeURIComponent(id)}`)),

  listAttachments: (targetType, targetId, params = {}) => list("attachments", {
    targetType,
    targetId: requiredDatabaseId(targetId, "附件目标ID"),
    ...params,
  }),
  uploadAttachment: (targetType, targetId, file, category = "general", { source = "", roundIndex = null, roundId = "" } = {}) => {
    const form = new FormData();
    form.append("targetType", targetType);
    form.append("targetId", requiredDatabaseId(targetId, "附件目标ID"));
    form.append("category", category);
    if (source) form.append("source", source);
    if (Number.isInteger(roundIndex) && roundIndex >= 0) form.append("roundIndex", String(roundIndex));
    if (roundId) form.append("roundId", roundId);
    form.append("file", file, file.name);
    return apiUpload(endpoint("attachments"), form, { timeoutMs: 600_000 });
  },
  deleteAttachment: (id, { source = "" } = {}) => apiDelete(endpoint(
    `attachments/${encodeURIComponent(requiredDatabaseId(id, "附件ID"))}${source ? `?source=${encodeURIComponent(source)}` : ""}`,
  )),

  updateMobileTask: (id, payload) => apiPatch(endpoint(`mobile/tasks/${encodeURIComponent(id)}`), payload),
  mobileWorkspace: () => apiGet(endpoint("mobile/home")),
};
