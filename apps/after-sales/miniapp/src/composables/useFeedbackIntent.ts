export type FeedbackIntentMode = "feedback" | "ticket";

interface FeedbackIntent {
  readonly mode: FeedbackIntentMode;
  readonly taskId: number;
  readonly createdAt: number;
}

const STORAGE_KEY = "mj_after_sales_feedback_intent";
const MAX_AGE_MS = 5 * 60 * 1000;

export function saveFeedbackIntent(mode: FeedbackIntentMode, taskId: number): void {
  if (!Number.isInteger(taskId) || taskId <= 0) return;
  uni.setStorageSync(STORAGE_KEY, { mode, taskId, createdAt: Date.now() } satisfies FeedbackIntent);
}

export function takeFeedbackIntent(): FeedbackIntent | null {
  const value = uni.getStorageSync(STORAGE_KEY) as Partial<FeedbackIntent> | null;
  uni.removeStorageSync(STORAGE_KEY);
  if (!value || !["feedback", "ticket"].includes(String(value.mode))) return null;
  const taskId = Number(value.taskId);
  const createdAt = Number(value.createdAt);
  if (!Number.isInteger(taskId) || taskId <= 0 || !Number.isFinite(createdAt)) return null;
  if (Date.now() - createdAt > MAX_AGE_MS) return null;
  return { mode: value.mode as FeedbackIntentMode, taskId, createdAt };
}
