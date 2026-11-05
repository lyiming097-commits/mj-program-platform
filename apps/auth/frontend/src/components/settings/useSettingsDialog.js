import { nextTick, onBeforeUnmount, watch } from "vue";

// Desktop settings menus share the same keyboard and focus-return behavior.
export function useSettingsDialog(open, panel, close, suspended = () => false) {
  let previousFocus;
  function handleKeydown(event) {
    if (!open.value || suspended()) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopImmediatePropagation();
      close();
      return;
    }
    if (event.key !== "Tab") return;
    const elements = [
      ...(panel.value?.querySelectorAll(
        'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [contenteditable="true"], [tabindex="0"]',
      ) || []),
    ].filter(
      (item) =>
        item.getClientRects().length &&
        !item.matches(":disabled") &&
        (item.tabIndex >= 0 || item.isContentEditable),
    );
    const first = elements[0],
      last = elements.at(-1),
      active = document.activeElement;
    if (!first) {
      event.preventDefault();
      panel.value?.focus();
    } else if (
      event.shiftKey &&
      (active === first || !panel.value.contains(active))
    ) {
      event.preventDefault();
      last.focus();
    } else if (
      !event.shiftKey &&
      (active === last || !panel.value.contains(active))
    ) {
      event.preventDefault();
      first.focus();
    }
  }
  watch(open, async (value) => {
    if (value) {
      previousFocus = document.activeElement;
      window.addEventListener("keydown", handleKeydown, true);
      await nextTick();
      (
        panel.value?.querySelector("button:not([disabled])") || panel.value
      )?.focus();
    } else {
      window.removeEventListener("keydown", handleKeydown, true);
      const target = previousFocus;
      previousFocus = null;
      await nextTick();
      if (target?.isConnected && !target.closest("[inert]")) target.focus();
    }
  });
  onBeforeUnmount(() =>
    window.removeEventListener("keydown", handleKeydown, true),
  );
}
