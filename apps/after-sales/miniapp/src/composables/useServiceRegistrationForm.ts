import { computed, reactive, shallowRef } from "vue";
import type { ProviderApplication } from "@/api/types";

export const SERVICE_ROLE_OPTIONS: { value: ProviderApplication["role"]; label: string }[] = [
  { value: "installer", label: "安装 / 调试人员" },
  { value: "maintenance", label: "售后维修人员" },
  { value: "support", label: "技术支持人员" },
  { value: "partner", label: "第三方合作资源" },
];

function splitList(value: string): string[] {
  return [...new Set(value.split(/[，,、\n]/).map((item) => item.trim()).filter(Boolean))];
}

export function useServiceRegistrationForm() {
  const form = reactive({
    name: "",
    role: "installer" as ProviderApplication["role"],
    phone: "",
    city: "",
    regions: "",
    skills: "",
    bio: "",
  });
  const validationError = shallowRef("");
  const roleIndex = computed(() => Math.max(0, SERVICE_ROLE_OPTIONS.findIndex((item) => item.value === form.role)));
  const selectedSkills = computed(() => splitList(form.skills));

  function setInitialName(value: string): void {
    if (!form.name) form.name = value;
  }

  function selectRole(index: number): void {
    form.role = SERVICE_ROLE_OPTIONS[index]?.value || "installer";
  }

  function toggleSkill(value: string): void {
    const skill = value.trim();
    if (!skill) return;
    const next = new Set(selectedSkills.value);
    if (next.has(skill)) next.delete(skill);
    else next.add(skill);
    form.skills = [...next].join("、");
  }

  function buildProfile(): ProviderApplication | null {
    validationError.value = "";
    if (!form.name.trim()) {
      validationError.value = "请填写姓名";
      return null;
    }
    if (!form.phone.trim()) {
      validationError.value = "请填写联系电话";
      return null;
    }
    if (!form.city.trim()) {
      validationError.value = "请填写所在城市";
      return null;
    }
    return {
      name: form.name.trim(),
      role: form.role,
      phone: form.phone.trim(),
      city: form.city.trim(),
      regions: splitList(form.regions),
      skills: splitList(form.skills),
      bio: form.bio.trim(),
    };
  }

  return {
    form,
    roleIndex,
    selectedSkills,
    roleOptions: SERVICE_ROLE_OPTIONS,
    validationError,
    setInitialName,
    selectRole,
    toggleSkill,
    buildProfile,
  };
}
