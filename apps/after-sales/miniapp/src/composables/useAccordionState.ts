import { shallowRef } from "vue";

const activeId = shallowRef(0);
let nextId = 0;

export function resetAccordionState(): void {
  activeId.value = 0;
}

export function useAccordionState(): { activeId: typeof activeId; sectionId: number } {
  nextId += 1;
  return { activeId, sectionId: nextId };
}
