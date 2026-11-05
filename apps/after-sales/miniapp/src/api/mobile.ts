import { del, get, post, request, uploadFile } from "@/api/client";
import type {
  MobileTaskUpdate,
  MobileAttachment,
  MidsalesProof,
  MobileWorkspace,
  FieldFeedback,
  ProviderApplication,
  ProviderResponse,
  ServiceTicket,
} from "@/api/types";

export function fetchProviderMe(): Promise<ProviderResponse> {
  return get<ProviderResponse>("/api/after-sales/providers/me");
}

export function fetchProviderTags(): Promise<{ items: string[] }> {
  return request<{ items: string[] }>("/api/after-sales/public/provider-tags", { authenticated: false });
}

export function applyProvider(profile: ProviderApplication): Promise<ProviderResponse> {
  return post<ProviderResponse>("/api/after-sales/providers/apply", { ...profile });
}

export function deactivateProvider(): Promise<{
  ok: true;
  activeAssignmentCount: number;
  message: string;
}> {
  return del("/api/after-sales/providers/me");
}

export function createFieldFeedback(payload: {
  projectId: number;
  nodeKey: string;
  title: string;
  feedbackType: string;
  content: string;
}): Promise<{ ok: true; item: FieldFeedback }> {
  return post("/api/after-sales/feedback", { ...payload, businessData: { source: "wechat-mini" } });
}

export function createServiceTicket(payload: {
  projectId: number;
  nodeKey: string;
  title: string;
  ticketType: string;
  priority: string;
  description: string;
}): Promise<{ ok: true; item: ServiceTicket }> {
  return post("/api/after-sales/tickets", { ...payload, businessData: { source: "wechat-mini" } });
}

export function fetchServiceTicket(ticketId: number): Promise<{ item: ServiceTicket }> {
  return get(`/api/after-sales/tickets/${encodeURIComponent(ticketId)}`);
}

export function fetchMobileWorkspace(): Promise<MobileWorkspace> {
  return get<MobileWorkspace>("/api/after-sales/mobile/v1/home");
}

export type MobileRecordType = "feedback" | "tickets" | "rewards";
export interface MobileRecordPage<T> { items: T[]; page: number; pageSize: number; total: number; totalPages: number }
export function fetchMobileRecords<T>(type: MobileRecordType, page = 1, pageSize = 20, recordId?: number): Promise<MobileRecordPage<T>> {
  return get(`/api/after-sales/mobile/v1/records/${type}?page=${page}&pageSize=${pageSize}${recordId ? `&recordId=${recordId}` : ""}`);
}

export function updateMobileTask(assignmentId: number, payload: Record<string, unknown>): Promise<MobileTaskUpdate> {
  return post<MobileTaskUpdate>(`/api/after-sales/mobile/v1/tasks/${assignmentId}`, payload);
}

export type AttachmentTargetType =
  | "project_node"
  | "midsales_proof"
  | "ticket"
  | "feedback"
  | "provider_application";

export function fetchAttachments(targetType: AttachmentTargetType, targetId: number): Promise<{ items: MobileAttachment[] }> {
  return get(`/api/after-sales/attachments?targetType=${encodeURIComponent(targetType)}&targetId=${encodeURIComponent(targetId)}&source=mobile`);
}

export function uploadAttachment(
  targetType: AttachmentTargetType,
  targetId: number,
  filePath: string,
  category = "general",
): Promise<{ ok: true; item: MobileAttachment }> {
  return uploadFile("/api/after-sales/attachments", filePath, {
    targetType,
    targetId: String(targetId),
    category,
    source: "mobile",
  });
}

export function deleteAttachment(attachmentId: number): Promise<{ ok: true }> {
  return del(`/api/after-sales/attachments/${encodeURIComponent(attachmentId)}?source=mobile`);
}

export function fetchMidsalesProofs(projectId: number, nodeKey: string): Promise<{ items: MidsalesProof[] }> {
  return get(`/api/after-sales/projects/${encodeURIComponent(projectId)}/nodes/${encodeURIComponent(nodeKey)}/proofs?source=mobile`);
}
