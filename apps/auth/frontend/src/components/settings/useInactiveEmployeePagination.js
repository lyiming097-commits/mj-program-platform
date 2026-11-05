import { computed, ref, watch } from "vue";

export const INACTIVE_EMPLOYEE_PAGE_SIZE = 20;

export function useInactiveEmployeePagination(props) {
  const page = ref(1);
  const totalPages = computed(() => Math.max(1, Math.ceil(props.filteredInactiveEmployees.length / INACTIVE_EMPLOYEE_PAGE_SIZE)));
  const currentPage = computed(() => Math.min(page.value, totalPages.value));
  const pageEmployees = computed(() => {
    const start = (currentPage.value - 1) * INACTIVE_EMPLOYEE_PAGE_SIZE;
    return props.filteredInactiveEmployees.slice(start, start + INACTIVE_EMPLOYEE_PAGE_SIZE);
  });
  const visiblePages = computed(() => {
    if (totalPages.value <= 7) {
      return Array.from({ length: totalPages.value }, (_, index) => index + 1);
    }
    const candidates = [...new Set([1, totalPages.value, currentPage.value - 1, currentPage.value, currentPage.value + 1])]
      .filter((value) => value >= 1 && value <= totalPages.value)
      .sort((left, right) => left - right);
    const result = [];
    candidates.forEach((value, index) => {
      if (index && value - candidates[index - 1] > 1) result.push(`ellipsis-${value}`);
      result.push(value);
    });
    return result;
  });

  watch(() => [props.filteredInactiveEmployees, props.inactiveKeyword], () => { page.value = 1; });

  function goToPage(value) {
    page.value = Math.max(1, Math.min(totalPages.value, value));
  }

  return { page: currentPage, pageEmployees, totalPages, visiblePages, goToPage };
}
