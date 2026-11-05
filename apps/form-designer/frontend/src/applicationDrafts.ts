import { scopedStorage } from './storage'
import type { FormField, FormValues } from './types'

export interface ApplicationDraft {
  schemaVersion: 3
  version: number
  savedAt: string
  values: FormValues
  fields: Pick<FormField, 'id' | 'label' | 'type'>[]
}
const key = (workflowId: string) => `application-draft-${workflowId}`
const object = (value: unknown): value is Record<string, unknown> => Boolean(value) && typeof value === 'object' && !Array.isArray(value)
function validValues(value: unknown): value is FormValues {
  return object(value) && Object.values(value).every(item =>
    typeof item === 'string' || (typeof item === 'number' && Number.isFinite(item)) ||
    (Array.isArray(item) && item.every(part => typeof part === 'string')))
}
export function readApplicationDraft(workflowId: string, storage = scopedStorage): ApplicationDraft | null {
  const raw = storage.getItem(key(workflowId))
  if (!raw) return null
  let data: unknown = JSON.parse(raw)
  if (!object(data)) throw new Error('草稿格式不正确')
  // The historical format stored newest saves first. The former activeId may
  // be null after submission, or refer to an older manually selected entry.
  if (data.schemaVersion === 2) {
    if (!Array.isArray(data.entries)) throw new Error('草稿格式不正确')
    if (!data.entries.length) return null
    data = data.entries[0]
  }
  if (!object(data) || !Number.isInteger(data.version) || !validValues(data.values)) throw new Error('草稿格式不正确')
  const fields = Array.isArray(data.fields) ? data.fields : []
  if (fields.some(field => !object(field) || typeof field.id !== 'string' || typeof field.label !== 'string' || typeof field.type !== 'string')) throw new Error('草稿字段格式不正确')
  return { schemaVersion: 3, version: data.version as number, savedAt: typeof data.savedAt === 'string' ? data.savedAt : '', values: data.values,
    fields: fields.map(field => ({ id: field.id as string, label: field.label as string, type: field.type as FormField['type'] })) }
}
export function saveApplicationDraft(workflowId: string, version: number, values: FormValues, fields: FormField[], storage = scopedStorage): void {
  const draft: ApplicationDraft = {
    schemaVersion: 3, version, savedAt: new Date().toISOString(),
    values: JSON.parse(JSON.stringify(Object.fromEntries(fields.map(field => [field.id, values[field.id]])))),
    fields: fields.map(({ id, label, type }) => ({ id, label, type })),
  }
  // Replace one draft atomically. A failed write leaves the last saved draft intact.
  storage.setItem(key(workflowId), JSON.stringify(draft))
}
