import type { MiniSession, WeChatLoginResult, WeChatRegistrationChallenge } from "@/api/types";

export const SESSION_STORAGE_KEY = "mj.afterSales.mini.session";

const configuredBaseUrl = String(__API_BASE_URL__ || "").trim();
export const API_BASE_URL = configuredBaseUrl.replace(/\/+$/, "");

type RequestMethod = "GET" | "POST" | "PUT" | "DELETE";
type RequestData = string | Record<string, unknown> | ArrayBuffer;
type AuthenticatedOperation<T> = (token: string) => Promise<T>;
type StoredSessionClearedListener = () => void;

interface RequestOptions {
  method?: RequestMethod;
  data?: RequestData;
  authenticated?: boolean;
}

interface ErrorPayload {
  code?: unknown;
  error?: unknown;
  message?: unknown;
}

interface RawResponse<T> {
  readonly status: number;
  readonly data: T;
}

interface SessionRenewOptions {
  preferWechatLogin?: boolean;
}

const TOKEN_RENEW_WINDOW_MS = 5 * 60 * 1000;
const AUTH_FAILURE_CODES = new Set([
  "INVALID_AUTH_TOKEN",
  "MISSING_AUTH_TOKEN",
  "AUTH_SESSION_REVOKED",
  "AUTH_SESSION_NOT_FOUND",
  "AUTH_SESSION_MISMATCH",
  "AUTH_SESSION_CHANGED",
  "AUTH_VERSION_MISMATCH",
  "AUTH_CHANNEL_MISMATCH",
  "EMPLOYEE_INACTIVE",
  "ACCOUNT_DISABLED",
  "EMPLOYEE_NOT_ALLOWED",
]);
let sessionRenewalPromise: Promise<MiniSession> | null = null;
let sessionRenewalGeneration = -1;
let storedSessionGeneration = 0;
const storedSessionClearedListeners = new Set<StoredSessionClearedListener>();

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(message: string, status = 0, code = "REQUEST_FAILED") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export function readStoredSession(): MiniSession | null {
  const value = uni.getStorageSync(SESSION_STORAGE_KEY) as unknown;
  return isMiniSession(value) ? value : null;
}

export function writeStoredSession(session: MiniSession | null): void {
  storedSessionGeneration += 1;
  if (session) {
    uni.setStorageSync(SESSION_STORAGE_KEY, session);
    return;
  }
  uni.removeStorageSync(SESSION_STORAGE_KEY);
  storedSessionClearedListeners.forEach((listener) => {
    try { listener(); } catch { /* Session removal must not be blocked by UI cleanup. */ }
  });
}

export function onStoredSessionCleared(listener: StoredSessionClearedListener): () => void {
  storedSessionClearedListeners.add(listener);
  return () => storedSessionClearedListeners.delete(listener);
}

function errorFrom(data: unknown, status: number): ApiError {
  const payload = data && typeof data === "object" ? data as ErrorPayload : {};
  const message = String(payload.error || payload.message || `请求失败（${status || "网络异常"}）`);
  return new ApiError(message, status, String(payload.code || "REQUEST_FAILED"));
}

function isSuccessfulStatus(status: number): boolean {
  return status >= 200 && status < 300;
}

function isAuthenticationFailure(reason: unknown): reason is ApiError {
  return reason instanceof ApiError && (
    reason.status === 401
    || (reason.status === 403 && AUTH_FAILURE_CODES.has(reason.code))
  );
}

function expiresWithin(value: string, windowMs = TOKEN_RENEW_WINDOW_MS): boolean {
  const expiresAt = Date.parse(value);
  return !Number.isFinite(expiresAt) || expiresAt <= Date.now() + windowMs;
}

function isMiniSession(value: unknown): value is MiniSession {
  if (!value || typeof value !== "object") return false;
  const session = value as Partial<MiniSession>;
  return Boolean(
    typeof session.token === "string"
    && session.token
    && typeof session.sessionId === "string"
    && session.sessionId
    && typeof session.tokenExpiresAt === "string"
    && session.tokenExpiresAt
    && typeof session.sessionExpiresAt === "string"
    && session.sessionExpiresAt
    && session.user
    && typeof session.user.userId === "string"
    && session.user.userId,
  );
}

function isRegistrationChallenge(value: unknown): value is WeChatRegistrationChallenge {
  return Boolean(
    value
    && typeof value === "object"
    && (value as Partial<WeChatRegistrationChallenge>).registrationRequired === true
    && typeof (value as Partial<WeChatRegistrationChallenge>).registrationToken === "string"
    && (value as Partial<WeChatRegistrationChallenge>).registrationToken,
  );
}

function rawRequest<T>(
  path: string,
  options: Omit<RequestOptions, "authenticated"> = {},
  token = "",
): Promise<RawResponse<T>> {
  const { method = "GET", data } = options;
  const requestUrl = `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (data !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;

  return new Promise<RawResponse<T>>((resolve, reject) => {
    uni.request({
      url: requestUrl,
      method,
      data,
      header: headers,
      timeout: 15_000,
      success: (response) => {
        const status = Number(response.statusCode || 0);
        resolve({ status, data: response.data as T });
      },
      fail: (reason) => reject(new ApiError(
        `${reason.errMsg || "网络连接失败"}\n请求地址：${requestUrl}`,
      )),
    });
  });
}

async function checkedRequest<T>(
  path: string,
  options: Omit<RequestOptions, "authenticated"> = {},
  token = "",
): Promise<T> {
  const response = await rawRequest<T>(path, options, token);
  if (isSuccessfulStatus(response.status)) return response.data;
  throw errorFrom(response.data, response.status);
}

function wxLoginCode(): Promise<string> {
  return new Promise((resolve, reject) => {
    uni.login({
      provider: "weixin",
      success: (result) => {
        if (result.code) resolve(result.code);
        else reject(new ApiError("微信未返回登录凭证", 0, "WECHAT_LOGIN_CODE_REQUIRED"));
      },
      fail: (reason) => reject(new ApiError(reason.errMsg || "微信登录失败")),
    });
  });
}

export async function requestWeChatLogin(): Promise<WeChatLoginResult> {
  const result = __WECHAT_DEV_AUTH__
    ? checkedRequest<WeChatLoginResult>("/api/auth/wechat-mini/dev-login", { method: "POST" })
    : checkedRequest<WeChatLoginResult>("/api/auth/wechat-mini/login", {
      method: "POST",
      data: { code: await wxLoginCode() },
    });
  const resolved = await result;
  if (!isMiniSession(resolved) && !isRegistrationChallenge(resolved)) {
    throw new ApiError("微信登录返回了无效数据", 502, "WECHAT_LOGIN_RESPONSE_INVALID");
  }
  return resolved;
}

async function loginSilently(): Promise<MiniSession> {
  const result = await requestWeChatLogin();
  if (isRegistrationChallenge(result)) {
    throw new ApiError("微信身份需要重新注册", 401, "WECHAT_REGISTRATION_REQUIRED");
  }
  if (!isMiniSession(result)) {
    throw new ApiError("微信登录返回了无效会话", 502, "WECHAT_SESSION_INVALID");
  }
  return result;
}

async function refreshSession(current: MiniSession): Promise<MiniSession> {
  const result = await checkedRequest<unknown>(
    "/api/auth/wechat-mini/refresh",
    { method: "POST" },
    current.token,
  );
  if (!isMiniSession(result)) {
    throw new ApiError("身份续期返回了无效会话", 502, "WECHAT_SESSION_INVALID");
  }
  return result;
}

function assertSameIdentity(previous: MiniSession, next: MiniSession): void {
  if (previous.user.userId === next.user.userId) return;
  throw new ApiError("微信登录身份已发生变化，请重新进入小程序", 401, "AUTH_SESSION_CHANGED");
}

export function renewStoredSession(options: SessionRenewOptions = {}): Promise<MiniSession> {
  if (sessionRenewalPromise && sessionRenewalGeneration === storedSessionGeneration) return sessionRenewalPromise;
  const current = readStoredSession();
  if (!current) {
    return Promise.reject(new ApiError("登录已失效", 401, "MISSING_AUTH_TOKEN"));
  }
  const renewalGeneration = storedSessionGeneration;

  const renewal = (async () => {
    let next: MiniSession;
    if (options.preferWechatLogin || expiresWithin(current.sessionExpiresAt)) {
      next = await loginSilently();
    } else {
      try {
        next = await refreshSession(current);
      } catch (reason) {
        if (!isAuthenticationFailure(reason)) throw reason;
        next = await loginSilently();
      }
    }
    assertSameIdentity(current, next);
    if (renewalGeneration !== storedSessionGeneration) {
      throw new ApiError("登录状态已变更，请重新登录", 401, "AUTH_SESSION_CHANGED");
    }
    writeStoredSession(next);
    return next;
  })()
    .catch((reason: unknown) => {
      if (isAuthenticationFailure(reason) && renewalGeneration === storedSessionGeneration) writeStoredSession(null);
      throw reason;
    })
    .finally(() => { if (sessionRenewalPromise === renewal) sessionRenewalPromise = null; });
  sessionRenewalPromise = renewal;
  sessionRenewalGeneration = renewalGeneration;
  return renewal;
}

async function sessionForRequest(): Promise<MiniSession> {
  const current = readStoredSession();
  if (!current) throw new ApiError("登录已失效", 401, "MISSING_AUTH_TOKEN");
  if (expiresWithin(current.sessionExpiresAt)) {
    return renewStoredSession({ preferWechatLogin: true });
  }
  if (expiresWithin(current.tokenExpiresAt)) return renewStoredSession();
  return current;
}

async function withAuthenticatedRetry<T>(operation: AuthenticatedOperation<T>): Promise<T> {
  const current = await sessionForRequest();
  const requestGeneration = storedSessionGeneration;
  const ensureCurrentSession = (generation: number): void => {
    if (generation !== storedSessionGeneration || !readStoredSession()) {
      throw new ApiError("登录状态已变更，请重新操作", 401, "AUTH_SESSION_CHANGED");
    }
  };
  ensureCurrentSession(requestGeneration);
  try {
    const result = await operation(current.token);
    ensureCurrentSession(requestGeneration);
    return result;
  } catch (reason) {
    ensureCurrentSession(requestGeneration);
    if (!isAuthenticationFailure(reason)) throw reason;
  }

  const renewed = await renewStoredSession();
  const retryGeneration = storedSessionGeneration;
  ensureCurrentSession(retryGeneration);
  try {
    const result = await operation(renewed.token);
    ensureCurrentSession(retryGeneration);
    return result;
  } catch (reason) {
    ensureCurrentSession(retryGeneration);
    if (isAuthenticationFailure(reason)) writeStoredSession(null);
    throw reason;
  }
}

export function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { authenticated = true, ...requestOptions } = options;
  if (!authenticated) return checkedRequest<T>(path, requestOptions);
  return withAuthenticatedRetry((token) => checkedRequest<T>(path, requestOptions, token));
}

export const get = <T>(path: string) => request<T>(path);
export const post = <T>(path: string, data?: RequestData, authenticated = true) => request<T>(path, {
  method: "POST",
  data,
  authenticated,
});
export const del = <T>(path: string) => request<T>(path, { method: "DELETE" });

export function uploadFile<T>(
  path: string,
  filePath: string,
  formData: Record<string, string>,
): Promise<T> {
  return withAuthenticatedRetry((token) => new Promise<T>((resolve, reject) => {
    const headers: Record<string, string> = { Accept: "application/json" };
    headers.Authorization = `Bearer ${token}`;

    uni.uploadFile({
      url: absoluteApiUrl(path),
      filePath,
      name: "file",
      formData,
      header: headers,
      timeout: 600_000,
      success: (response) => {
        const status = Number(response.statusCode || 0);
        let payload: unknown = response.data;
        try {
          payload = typeof response.data === "string" ? JSON.parse(response.data) : response.data;
        } catch {
          payload = { error: "附件接口返回了无效数据" };
        }
        if (isSuccessfulStatus(status)) {
          resolve(payload as T);
          return;
        }
        reject(errorFrom(payload, status));
      },
      fail: (reason) => reject(new ApiError(reason.errMsg || "附件上传失败")),
    });
  }));
}

function checkedDownload(path: string, token: string, timeoutMs: number): Promise<string> {
  return new Promise((resolve, reject) => {
    const url = absoluteApiUrl(path);
    if (url !== API_BASE_URL && !url.startsWith(`${API_BASE_URL}/`)) {
      reject(new ApiError("受保护资料地址不属于当前服务", 400, "PROTECTED_DOWNLOAD_ORIGIN_INVALID"));
      return;
    }
    uni.downloadFile({
      url,
      header: { Authorization: `Bearer ${token}` },
      timeout: timeoutMs,
      success: (response) => {
        const status = Number(response.statusCode || 0);
        if (isSuccessfulStatus(status) && response.tempFilePath) {
          resolve(response.tempFilePath);
          return;
        }
        reject(new ApiError(`文件下载失败（${status || "网络异常"}）`, status));
      },
      fail: (reason) => reject(new ApiError(reason.errMsg || "文件下载失败")),
    });
  });
}

function downloadCacheRoot(): string {
  const runtime = uni as typeof uni & { env?: { USER_DATA_PATH?: string } };
  return String(runtime.env?.USER_DATA_PATH || "wxfile://usr").replace(/\/+$/, "");
}

function responseContentType(headers: Record<string, unknown> | undefined): string {
  if (!headers) return "";
  const entry = Object.entries(headers).find(([name]) => name.toLowerCase() === "content-type");
  const [contentType = ""] = String(entry?.[1] || "").split(";", 1);
  return contentType.trim().toLowerCase();
}

function cachedFileExtension(path: string, contentType: string): string {
  const extensions: Record<string, string> = {
    "application/msword": ".doc",
    "application/pdf": ".pdf",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
  };
  const knownExtension = extensions[contentType];
  if (knownExtension) return knownExtension;
  const [pathname = ""] = path.split(/[?#]/, 1);
  const matched = pathname.match(/\.(docx?|gif|jpe?g|pdf|png|webp|xlsx?)$/i);
  const pathExtension = matched?.[1];
  return pathExtension ? `.${pathExtension.toLowerCase().replace("jpeg", "jpg")}` : ".bin";
}

function cachedFileName(path: string, extension: string): string {
  let hash = 2166136261;
  for (let index = 0; index < path.length; index += 1) {
    hash ^= path.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `${(hash >>> 0).toString(16)}${extension}`;
}

function downloadedImageContentType(path: string, data: ArrayBuffer, declaredType: string): string {
  if (declaredType.startsWith("image/")) return declaredType;
  const bytes = new Uint8Array(data, 0, Math.min(data.byteLength, 12));
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return "image/jpeg";
  if (bytes.length >= 8 && bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47) return "image/png";
  if (bytes.length >= 6 && bytes[0] === 0x47 && bytes[1] === 0x49 && bytes[2] === 0x46) return "image/gif";
  if (bytes.length >= 12 && bytes[0] === 0x52 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x46
    && bytes[8] === 0x57 && bytes[9] === 0x45 && bytes[10] === 0x42 && bytes[11] === 0x50) return "image/webp";
  if (bytes.length >= 2 && bytes[0] === 0x42 && bytes[1] === 0x4d) return "image/bmp";
  const [pathname = ""] = path.split(/[?#]/, 1);
  const matched = pathname.match(/\.(gif|jpe?g|png|webp|bmp)$/i);
  if (matched?.[1]) return `image/${matched[1].toLowerCase().replace("jpg", "jpeg")}`;
  return "";
}

function persistDownloadedBuffer(path: string, data: ArrayBuffer, contentType: string): string {
  const fileSystem = uni.getFileSystemManager();
  const cacheRoot = downloadCacheRoot();
  const cacheDirectory = `${cacheRoot}/mj-after-sales-cache`;
  const resolvedContentType = downloadedImageContentType(path, data, contentType) || contentType;
  const fileName = cachedFileName(path, cachedFileExtension(path, resolvedContentType));
  let cacheDirectoryReady = true;
  try {
    fileSystem.mkdirSync(cacheDirectory, true);
  } catch {
    cacheDirectoryReady = false;
  }
  const destinations = cacheDirectoryReady
    ? [`${cacheDirectory}/${fileName}`, `${cacheRoot}/${fileName}`]
    : [`${cacheRoot}/${fileName}`];
  let writeFailure: unknown = null;
  for (const destination of destinations) {
    try {
      fileSystem.writeFileSync(destination, data);
      return destination;
    } catch (reason) {
      writeFailure = reason;
    }
  }
  throw writeFailure || new Error("文件写入失败");
}

function checkedBufferedDownload(path: string, token: string, timeoutMs: number): Promise<string> {
  return new Promise((resolve, reject) => {
    const url = absoluteApiUrl(path);
    if (url !== API_BASE_URL && !url.startsWith(`${API_BASE_URL}/`)) {
      reject(new ApiError("受保护资料地址不属于当前服务", 400, "PROTECTED_DOWNLOAD_ORIGIN_INVALID"));
      return;
    }
    uni.request({
      url,
      method: "GET",
      header: { Authorization: `Bearer ${token}`, Accept: "*/*" },
      responseType: "arraybuffer",
      timeout: timeoutMs,
      success: (response) => {
        const status = Number(response.statusCode || 0);
        if (!isSuccessfulStatus(status) || !(response.data instanceof ArrayBuffer)) {
          reject(new ApiError(`文件下载失败（${status || "网络异常"}）`, status));
          return;
        }
        try {
          resolve(persistDownloadedBuffer(
            path,
            response.data,
            responseContentType(response.header as Record<string, unknown> | undefined),
          ));
        } catch (reason) {
          const message = reason instanceof Error ? reason.message : String(reason || "文件写入失败");
          reject(new ApiError(message, 0, "DOWNLOAD_CACHE_WRITE_FAILED"));
        }
      },
      fail: (reason) => reject(new ApiError(reason.errMsg || "文件下载失败")),
    });
  });
}

export function downloadAuthenticatedFile(path: string, timeoutMs = 30_000): Promise<string> {
  return withAuthenticatedRetry(async (token) => {
    try {
      return await checkedDownload(path, token, timeoutMs);
    } catch (reason) {
      if (isAuthenticationFailure(reason) || (reason instanceof ApiError && reason.status > 0)) throw reason;
      return checkedBufferedDownload(path, token, timeoutMs);
    }
  });
}

export function absoluteApiUrl(path: string): string {
  return /^https?:\/\//i.test(path) ? path : `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}
