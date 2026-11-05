export type JsonRecord = Record<string, unknown>;

export interface MiniUser {
  userId: string;
  name: string;
  avatarUrl: string;
}

export interface MiniSession {
  token: string;
  sessionId: string;
  tokenType: "Bearer";
  tokenExpiresAt: string;
  tokenExpiresIn: number;
  sessionExpiresAt: string;
  sessionExpiresIn: number;
  user: MiniUser;
}

export interface WeChatRegistrationChallenge {
  ok: true;
  registrationRequired: true;
  registrationToken: string;
  expiresAt: string;
  expiresIn: number;
  privacyVersion: string;
}

export type WeChatLoginResult = MiniSession | WeChatRegistrationChallenge;

export interface ProviderApplication {
  name: string;
  role: "installer" | "maintenance" | "support" | "partner";
  phone: string;
  city: string;
  regions: string[];
  skills: string[];
  bio: string;
}

export interface ServiceProvider extends JsonRecord {
  id?: number;
  authUserId?: string;
  name?: string;
  certificationStatus?: string;
  certificationStatusLabel?: string;
  role?: ProviderApplication["role"];
  roleLabel?: string;
  phone?: string;
  city?: string;
  regions?: string[];
  skills?: string[];
  bio?: string;
}

export interface ProviderResponse {
  ok?: true;
  item: ServiceProvider | null;
}

export interface ServiceTicket extends JsonRecord {
  id: number;
  projectId: number;
  projectName: string;
  nodeKey?: string;
  title: string;
  ticketType: string;
  priority: string;
  priorityLabel?: string;
  status: string;
  statusLabel?: string;
  ownerUserId?: string;
  ownerName?: string;
  reporterUserId?: string;
  reporterName?: string;
  description: string;
  resolution?: string;
  createdAt?: string;
  updatedAt?: string;
  messages?: TicketMessage[];
}

export interface TicketMessage extends JsonRecord {
  id: number;
  authorUserId?: string;
  authorName?: string;
  messageType?: string;
  content: string;
  statusSnapshot?: string;
  createdAt?: string;
}

export interface FieldFeedback extends JsonRecord {
  id: number;
  projectId: number;
  projectName: string;
  nodeKey?: string;
  title: string;
  feedbackType: string;
  feedbackTypeLabel?: string;
  content: string;
  status: string;
  statusLabel?: string;
  reviewNote?: string;
  reviewedAt?: string;
  rating?: number;
  createdAt?: string;
  updatedAt?: string;
}

export interface ServiceReward extends JsonRecord {
  id: number;
  code?: string;
  providerId?: number;
  providerName?: string;
  providerCity?: string;
  projectId?: number;
  title?: string;
  description?: string;
  prize?: string;
  projectName?: string;
  projectProvince?: string;
  feedbackId?: number;
  rewardType?: string;
  rewardTypeLabel?: string;
  amount?: string;
  points?: number;
  status?: string;
  statusLabel?: string;
  issuedAt?: string;
  transitionNote?: string;
  createdAt?: string;
  updatedAt?: string;
}

export interface ProjectAssignment extends JsonRecord {
  id: number;
  status: string;
  statusLabel?: string;
  plannedStartDate?: string;
  standardDuration?: string;
  providerName?: string;
  assignedAt?: string;
  acceptedAt?: string;
  completedAt?: string;
  updatedAt?: string;
}

export interface ServiceProject extends JsonRecord {
  id: number;
  name: string;
  customer?: string;
  serviceType: "presales" | "midsales" | "aftersales";
  serviceTypeLabel?: string;
  status: string;
  summary?: string;
  businessData?: JsonRecord;
}

export interface ProjectNode extends JsonRecord {
  id: number;
  nodeKey: string;
  name: string;
  status: string;
  statusLabel?: string;
  description?: string;
  plannedStartAt?: string;
  plannedEndAt?: string;
  actualStartAt?: string;
  actualEndAt?: string;
  completedAt?: string;
  updatedAt?: string;
  estimatedFee?: string;
  actualFee?: string;
  businessData?: JsonRecord;
}

export interface MobileTaskEnvelope {
  assignment: ProjectAssignment;
  project: ServiceProject;
  node: ProjectNode;
  nodes: ProjectNode[];
}

export interface MobileTask extends MobileTaskEnvelope {
  id: number;
  projectId: number;
  projectName: string;
  serviceType: ServiceProject["serviceType"];
  serviceTypeLabel: string;
  nodeId: number;
  nodeKey: string;
  nodeName: string;
  assignmentStatus: string;
}

export interface ProductManual extends JsonRecord {
  id: string;
  projectId: number;
  projectName: string;
  nodeKey: string;
  productId: number;
  productName: string;
  productAbbr: string;
  title: string;
  resourceTypeLabel?: string;
  externalUrl: string;
}

export interface MobileAttachment extends JsonRecord {
  id: number;
  targetType: string;
  targetId: number;
  category: string;
  originalName: string;
  mimeType?: string;
  size: number;
  createdAt?: string;
  downloadUrl: string;
  canDelete?: boolean;
}

export interface PendingUploadFile {
  path: string;
  name: string;
  size: number;
}

export interface MidsalesProof extends JsonRecord {
  id: number;
  projectId: number;
  nodeId: number;
  nodeKey: string;
  proofType: "process" | "completion" | "evaluation";
  proofTypeLabel: string;
  status: "pending" | "approved" | "rejected";
  statusLabel: string;
  reviewOpinion?: string;
  attachments: MobileAttachment[];
  canUpload: boolean;
}

export interface MobileWorkspace {
  ok: true;
  profile: ServiceProvider;
  tasks: MobileTaskEnvelope[];
  productManuals: ProductManual[];
  resources: JsonRecord[];
  feedback: FieldFeedback[];
  tickets: ServiceTicket[];
  rewards: ServiceReward[];
  recordCounts?: { feedback: number; tickets: number; rewards: number };
}

export interface MobileTaskUpdate {
  ok: true;
  item: {
    assignment: ProjectAssignment;
    node: ProjectNode;
    fieldDraft?: JsonRecord;
    fieldSubmission?: JsonRecord;
    progressRounds?: JsonRecord[];
  };
}
