let userId = 'anonymous'
export function setStorageUser(id: string) { userId = id }
function key(name: string, owner = userId) { return `mj:form-designer:${owner}:${name}` }
export function storageForUser(owner: string) {
  return {
    getItem: (name: string) => localStorage.getItem(key(name, owner)),
    setItem: (name: string, value: string) => localStorage.setItem(key(name, owner), value),
    removeItem: (name: string) => localStorage.removeItem(key(name, owner)),
  }
}
export const scopedStorage = {
  getItem: (name: string) => localStorage.getItem(key(name)),
  setItem: (name: string, value: string) => localStorage.setItem(key(name), value),
  removeItem: (name: string) => localStorage.removeItem(key(name)),
}
