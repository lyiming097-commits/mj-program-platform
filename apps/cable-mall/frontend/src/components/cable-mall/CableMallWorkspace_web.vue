<script setup>
import { backdropDismiss as vBackdropDismiss } from "@platform-ui/backdrop-dismiss.js";
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { PlatformSidebar, PlatformSoftwareSuggestions, PlatformUnsavedChangesDialog, isSoftwareSuggestionsPath, useSoftwareSuggestionsContext, useSoftwareSuggestionsGuard, useSoftwareSuggestionsTabNavigation } from '@platform-ui';
import { apiDelete, apiGet, apiPatch, apiPost, apiPut, apiUpload } from '@/api';
import { API_BASE_URL } from '@/config';
import { loadLoginSession } from '@/session';
import { splitParameterLines } from '@/features/parameterText';
import {
  ArrowLeft,
  Download,
  Upload,
  FileText,
  Check,
  ChevronDown,
  FolderKanban,
  Plus,
  RefreshCw,
  Search,
  Building2,
  ShieldCheck,
  ShoppingCart,
  UserMinus,
  UserRound,
  UsersRound,
  Wrench,
  MapPin,
  X,
} from '@lucide/vue';

const props = defineProps({
  externalMode: {
    type: Boolean,
    default: false,
  },
  externalSession: {
    type: Object,
    default: null,
  },
});

const emit = defineEmits(['external-logout']);

const registrationStorageKey = 'xiancai_info_registrations';
const registrationContactsStorageKey = 'xiancai_registration_contacts';
const demoProjectName = '智慧教室一期演示项目';
const demoRegistrationName = '杭州示范学校';
const classroomNamePresets = ['单班教室', '合班教室', '阶梯教室'];
const activeTab = ref(isSoftwareSuggestionsPath("cable-mall") && !props.externalMode ? "suggestions" : 'products');
const { suggestionsRef, suggestionsDirty, suggestionsBusy, suggestionsConfirmOpen, requestSuggestionsAction, interceptSuggestionsAction, cancelSuggestionsLeave, confirmSuggestionsLeave } = useSoftwareSuggestionsGuard();
const loginSession = ref(loadLoginSession() || {});
const busy = ref(false);
const notice = ref('');
const error = ref('');
const messageLeaving = ref(false);
const productCartOpen = ref(false);
const productCartDetailOpen = ref(false);
const productCartDraftQuantity = ref(1);

const products = ref([]);
const drawerProducts = ref([]);
const addCableProducts = ref([]);
const categoriesA = ref([]);
const categoriesB = ref([]);
const filters = reactive({ q: '', category_a: '', category_b: '' });
const productPagination = reactive({ page: 1, page_size: 200, total: 0 });
const addCableCategoriesA = ref([]);
const addCableCategoriesB = ref([]);
const addCableFilters = reactive({ q: '', category_a: '', category_b: '' });
const projectStatsFilters = reactive({ q: '', category_a: '', category_b: '' });
const packageProductQuantities = reactive({});
const productCartItems = ref([]);
const productCartTarget = ref(null);
const addCableQuantities = reactive({});
const addCableSelectedProducts = reactive({});
const selectedPackageId = ref('');
const selectedProjectId = ref('');
const projectView = ref('list');
const projectDetailTab = ref('info');
const projectCreating = ref(false);
const recycleDrawerOpen = ref(false);
const deletingProjectId = ref(null);
const classroomCreating = ref(false);
const customCreating = ref(false);
const restartingCustomRequestId = ref(null);
const customBinding = ref(false);
const customBoundDetailOpen = ref(false);
const customBoundDetailRequest = ref(null);
const projectSearch = ref('');
const recycleSearch = ref('');
const customSearch = ref('');
const customTableShellRef = ref(null);
const customBottomScrollRef = ref(null);
const customBottomScrollWidth = ref(0);
const customBottomScrollVisible = ref(false);
const customBindSearch = ref('');
const orderSearch = ref('');
const orderStatusFilter = ref('all');
const shippingAddressSearch = ref('');
const signingInfoSearch = ref('');
const orderCreateSearch = ref('');
const orderAddressSearch = ref('');
const orderSigningInfoSearch = ref('');
const orderCreateTab = ref('cart-products');
const orderProjectViewMode = ref('cables');
const orderCopyDraft = ref(null);
const orderCopyWarnings = ref([]);
const orderEditDraft = ref(null);
const packageDetailId = ref(null);
const addCableModalOpen = ref(false);
const imagePreview = reactive({ open: false, src: '', title: '', loading: false, objectUrl: '', requestId: 0 });
const detailProductOrder = ref([]);
const parameterTooltipRef = ref(null);
const editingPackageId = ref(null);
const deletingPackageId = ref(null);
const deletingClassroom = ref(null);
const deletingDetailRowKey = ref('');
const classroomNameInput = ref(null);
const parameterTooltip = reactive({ visible: false, text: '', x: 0, y: 0 });
let productSearchTimer = null;
let addCableSearchTimer = null;
let messageFadeTimer = null;
let messageClearTimer = null;
let productLoadSeq = 0;
let productCartSaveTimer = null;
const detailQuantityInputs = new Map();

const unsavedConfirm = reactive({
  open: false,
  title: '是否放弃修改',
  message: '当前内容已有修改，退出后未保存的内容将不会保留。',
  cancelText: '继续编辑',
  confirmText: '放弃修改',
  confirmClass: '',
  action: null,
});

const packages = ref([]);
const projects = ref([]);
const archivedProjectRows = ref([]);
const customRequests = ref([]);
const orders = ref([]);
const orderProgressNoteDrafts = reactive({});
const shippingAddresses = ref([]);
const signingInfos = ref([]);
const externalAccounts = ref([]);
const registrations = ref(loadRegistrations());
const packageEditForm = reactive({ name: '', note: '' });
const packageEditInitial = ref({});
const packageDetailForm = reactive({ name: '', note: '' });
const detailDeletedRowKeys = reactive({});
const detailDeletedItemIds = reactive({});
const projectForm = reactive({ name: '', note: '' });
const projectFormInitial = ref({});
const projectInfoForm = reactive({
  name: '',
  note: '',
});
const classroomForm = reactive({ name: '' });
const classroomCreateForm = reactive({ name: '' });
const classroomCreateInitial = ref({});
const registrationForm = reactive({
  company_name: '迈杰教育科技',
  credit_code: '91330100MA00000000',
});
const registrationContactForm = reactive({ name: '', contact: '', position: '' });
const registrationContactEditForm = reactive({ name: '', contact: '', position: '' });
const registrationContactErrors = reactive({ name: '', contact: '' });
const registrationContactEditErrors = reactive({ name: '', contact: '' });
const registrationContacts = ref(loadRegistrationContacts());
const registrationContactEditorOpen = ref(false);
const editingContactId = ref(null);
const deletingContactId = ref(null);
const customForm = reactive({
  head_a_type: '',
  head_a_gender: '公头',
  head_a_other: '',
  head_b_type: '',
  head_b_gender: '公头',
  head_b_other: '',
  length_m: '',
  quantity: 1,
  note: '',
});
const customFormInitial = ref({});
const customCategoryContext = reactive({ category_a: '', category_b: '' });
const customCategoryLocked = ref(false);
const customBindForm = reactive({
  requestId: null,
  productId: '',
});
const customBindInitial = ref({});
const orderForm = reactive({
  external_account_id: '',
  shipping_address_id: '',
  signing_info_id: '',
  customer_name: '',
  customer_phone: '',
  project_name: '',
  shipping_method: '快递',
  arrival_date: '',
  remark: '',
});
const orderFormInitial = ref({});
const shippingAddressForm = reactive({ detail_address: '', receiver_name: '', receiver_phone: '' });
const shippingAddressEditForm = reactive({ detail_address: '', receiver_name: '', receiver_phone: '' });
const shippingAddressFormInitial = ref({});
const shippingAddressEditInitial = ref({});
const shippingAddressCreating = ref(false);
const shippingAddressCreateSource = ref('manager');
const shippingAddressEditing = ref(false);
const shippingAddressEditSource = ref('manager');
const orderAddressPickerOpen = ref(false);
const pendingOrderShippingAddressId = ref('');
const editingShippingAddressId = ref(null);
const deletingShippingAddressId = ref(null);
const signingInfoForm = reactive({ company_name: '', opening_bank: '', tax_number: '', bank_account: '' });
const signingInfoEditForm = reactive({ company_name: '', opening_bank: '', tax_number: '', bank_account: '' });
const signingInfoFormInitial = ref({});
const signingInfoEditInitial = ref({});
const signingInfoCreating = ref(false);
const signingInfoCreateSource = ref('manager');
const signingInfoEditing = ref(false);
const signingInfoEditSource = ref('manager');
const orderSigningInfoPickerOpen = ref(false);
const pendingOrderSigningInfoId = ref('');
const editingSigningInfoId = ref(null);
const deletingSigningInfoId = ref(null);
const externalAccountSearch = ref('');
const externalAccountStatusTab = ref('active');
const externalAccountCreating = ref(false);
const editingExternalAccountId = ref(null);
const externalAccountCreatedCredential = ref(null);
const externalAccountForm = reactive({ display_name: '', credit_code: '', username: '', password: '' });
const externalAccountEditForm = reactive({ display_name: '', credit_code: '', status: 'active', password: '' });
const externalAccountFormInitial = ref({});
const externalAccountEditInitial = ref({});
const accountPasswordForm = reactive({ old_password: '', new_password: '', confirm_password: '' });
const selectedOrderPackageIds = reactive({});
const orderPackageQuantities = reactive({});
const orderSelectionInitial = ref({});
const selectedOrder = ref(null);
const orderCreateOpen = ref(false);
const orderDetailOpen = ref(false);
const orderDetailTab = ref('info');
const orderDetailProductView = ref('cables');
const moduleBootstrapped = ref(false);
const cableMallPermission = ref({
  canAccessCableMall: props.externalMode,
  canManageCableMall: false,
  permission: '',
  permissionLabel: '',
  rulesConfigured: false,
});
const permissionLoading = ref(!props.externalMode);
const permissionError = ref('');
const adminPermissionRules = ref([]);
const adminPermissionInitialRules = ref([]);
const permissionDirectory = reactive({ departments: [], roles: [], employees: [] });
const adminPermissionRevision = ref('');
const adminPermissionOrgRevision = ref('');
const adminPermissionLoading = ref(false);
const adminPermissionSaving = ref(false);
const adminPermissionError = ref('');
const adminPermissionNotice = ref('');
const adminPermissionSnapshot = ref('');
const activeAdminPermissionId = ref('admin');
const expandedPermissionDepartmentIds = ref(new Set());
const permissionPickerInput = ref(null);
const permissionPicker = reactive({ open: false, permission: 'admin', scopeType: 'department', keyword: '' });

const currentSession = computed(() => (props.externalMode ? (props.externalSession?.account || {}) : (loginSession.value || {})));
const isExternalMode = computed(() => props.externalMode);
const accountName = computed(() => (
  props.externalMode
    ? (currentSession.value.display_name || currentSession.value.username || '外部用户')
    : (currentSession.value.name || currentSession.value.nick || currentSession.value.userId || '钉钉用户')
));
const displayName = computed(() => accountName.value);
const avatarInitial = computed(() => (displayName.value || '迈').slice(0, 1));
const currentUserId = computed(() => (props.externalMode ? (currentSession.value.username || '') : (currentSession.value.userId || '')));
const currentUserAvatar = computed(() => currentSession.value.avatarUrl || '');

function requestExternalLogout() {
  if (props.externalMode) guardBeforeLeavingCurrentDraft(() => emit('external-logout'));
}

const { navigateSuggestionsPage } = useSoftwareSuggestionsTabNavigation("cable-mall", {
  activePage: activeTab, suggestionsRef, defaultPage: "products",
  requestNavigation(action) {
    if (props.externalMode && isSoftwareSuggestionsPath("cable-mall")) return;
    if (interceptSuggestionsAction(() => guardBeforeLeavingCurrentDraft(action))) return;
    guardBeforeLeavingCurrentDraft(action);
  },
  commitPage(id) { activeTab.value = id === "suggestions" && props.externalMode ? "products" : id; },
});

function switchActiveTab(tabKey) {
  if (tabKey === activeTab.value) return;
  navigateSuggestionsPage(tabKey);
}

function refreshCustomBottomScroll() {
  nextTick(() => {
    const shell = customTableShellRef.value;
    if (!shell) {
      customBottomScrollWidth.value = 0;
      customBottomScrollVisible.value = false;
      return;
    }
    customBottomScrollWidth.value = shell.scrollWidth;
    customBottomScrollVisible.value = shell.scrollWidth > shell.clientWidth + 16;
    if (customBottomScrollRef.value) {
      customBottomScrollRef.value.scrollLeft = shell.scrollLeft;
    }
  });
}

function syncCustomBottomScrollFromTable() {
  if (!customBottomScrollRef.value || !customTableShellRef.value) return;
  customBottomScrollRef.value.scrollLeft = customTableShellRef.value.scrollLeft;
}

function syncCustomTableScrollFromBottom() {
  if (!customBottomScrollRef.value || !customTableShellRef.value) return;
  customTableShellRef.value.scrollLeft = customBottomScrollRef.value.scrollLeft;
}

function cableProductName(value) {
  return String(
    value?.abbr
    || value?.product_abbr
    || value?.label
    || value?.product_label
    || value?.order_display_name
    || '',
  ).trim();
}

function cableProductSortKey(value) {
  return [
    cableProductName(value),
    value?.label || value?.product_label || '',
    value?.product_model || '',
    String(value?.product_archive_id || value?.product_id || value?.id || ''),
  ].join('\u0001');
}

function compareCableProducts(left, right) {
  return cableProductSortKey(left).localeCompare(cableProductSortKey(right), 'zh-Hans-CN', {
    numeric: true,
    sensitivity: 'base',
  });
}

function sortCableProducts(rows = [], getProduct = (item) => item) {
  return [...rows].sort((left, right) => compareCableProducts(getProduct(left), getProduct(right)));
}

function sortCategoryValues(values = []) {
  return Array.from(new Set(values.map((value) => String(value || '').trim()).filter(Boolean))).sort((left, right) => (
    left.localeCompare(right, 'zh-Hans-CN', { numeric: true, sensitivity: 'base' })
  ));
}

function sortOrderDetailCables(order) {
  if (!order) return order;
  return {
    ...order,
    packages: (order.packages || []).map((packageItem) => ({
      ...packageItem,
      items: sortCableProducts(packageItem.items || []),
    })),
  };
}

function loadRegistrations() {
  try {
    return JSON.parse(localStorage.getItem(registrationStorageKey) || '[]');
  } catch {
    return [];
  }
}

function saveRegistrations() {
  localStorage.setItem(registrationStorageKey, JSON.stringify(registrations.value));
}

function loadRegistrationContacts() {
  try {
    return JSON.parse(localStorage.getItem(registrationContactsStorageKey) || '[]');
  } catch {
    return [];
  }
}

function saveRegistrationContacts() {
  localStorage.setItem(registrationContactsStorageKey, JSON.stringify(registrationContacts.value));
}

function createRegistration() {
  if (!registrationForm.company_name.trim() || !registrationForm.credit_code.trim()) {
    setMessage('error', '请填写单位名称和统一社会信用代码');
    return;
  }
  if (!registrationContacts.value.length) {
    setMessage('error', '请至少添加一个联系人');
    return;
  }
  registrations.value.unshift({
    id: Date.now(),
    company_name: registrationForm.company_name.trim(),
    credit_code: registrationForm.credit_code.trim(),
    contacts: registrationContacts.value.map((item) => ({ ...item })),
    created_at: new Date().toISOString(),
  });
  saveRegistrations();
  Object.assign(registrationForm, {
    company_name: '',
    credit_code: '',
  });
  registrationContacts.value = [];
  saveRegistrationContacts();
  setMessage('notice', '信息已保存');
}

function addRegistrationContact() {
  clearGlobalMessages();
  clearRegistrationContactErrors();
  if (!registrationContactForm.name.trim() || !registrationContactForm.contact.trim()) {
    if (!registrationContactForm.name.trim()) registrationContactErrors.name = '请填写联系人';
    if (!registrationContactForm.contact.trim()) registrationContactErrors.contact = '请填写电话/微信';
    return;
  }
  registrationContacts.value.push({
    id: Date.now() + Math.random(),
    name: registrationContactForm.name.trim(),
    contact: registrationContactForm.contact.trim(),
    position: registrationContactForm.position.trim(),
  });
  Object.assign(registrationContactForm, { name: '', contact: '', position: '' });
  registrationContactEditorOpen.value = false;
  saveRegistrationContacts();
}

function openRegistrationContactEditor() {
  Object.assign(registrationContactForm, { name: '', contact: '', position: '' });
  clearSettingsFeedback();
  editingContactId.value = null;
  deletingContactId.value = null;
  registrationContactEditorOpen.value = true;
}

function cancelRegistrationContact() {
  Object.assign(registrationContactForm, { name: '', contact: '', position: '' });
  clearRegistrationContactErrors();
  registrationContactEditorOpen.value = false;
}

function startEditRegistrationContact(item) {
  registrationContactEditorOpen.value = false;
  deletingContactId.value = null;
  editingContactId.value = item.id;
  Object.assign(registrationContactEditForm, {
    name: item.name,
    contact: item.contact,
    position: item.position,
  });
}

function saveRegistrationContactEdit(item) {
  clearGlobalMessages();
  clearRegistrationContactEditErrors();
  if (!registrationContactEditForm.name.trim() || !registrationContactEditForm.contact.trim()) {
    if (!registrationContactEditForm.name.trim()) registrationContactEditErrors.name = '请填写联系人';
    if (!registrationContactEditForm.contact.trim()) registrationContactEditErrors.contact = '请填写电话/微信';
    return;
  }
  Object.assign(item, {
    name: registrationContactEditForm.name.trim(),
    contact: registrationContactEditForm.contact.trim(),
    position: registrationContactEditForm.position.trim(),
  });
  saveRegistrationContacts();
  Object.assign(registrationContactEditForm, { name: '', contact: '', position: '' });
  editingContactId.value = null;
}

function cancelRegistrationContactEdit() {
  Object.assign(registrationContactEditForm, { name: '', contact: '', position: '' });
  clearRegistrationContactEditErrors();
  editingContactId.value = null;
}

function requestRemoveRegistrationContact(item) {
  registrationContactEditorOpen.value = false;
  editingContactId.value = null;
  deletingContactId.value = item.id;
}

function cancelRemoveRegistrationContact() {
  deletingContactId.value = null;
}

function confirmRemoveRegistrationContact(item) {
  registrationContacts.value = registrationContacts.value.filter((row) => row.id !== item.id);
  saveRegistrationContacts();
  deletingContactId.value = null;
}

function filterCustomRequests(keywordValue) {
  const keyword = keywordValue.trim().toLowerCase();
  if (!keyword) return customRequests.value;
  return customRequests.value.filter((item) => [
    item.submitter,
    item.contact_name,
    item.contact_phone,
    item.head_a_type,
    item.head_a_gender,
    item.head_b_type,
    item.head_b_gender,
    item.category_a,
    item.category_b,
    item.length_m,
    item.quantity,
    item.scenario,
    item.note,
    item.status,
    item.handle_result,
    item.bound_product_label,
    customBoundProductMeta(item.bound_product),
  ].join(' ').toLowerCase().includes(keyword));
}

function customCableText(item) {
  return `${customHeadText(item, 'a')} → ${customHeadText(item, 'b')}`;
}

function customCategoryText(item) {
  return [item.category_a, item.category_b].filter(Boolean).join(' - ') || '-';
}

function customHeadPairText(item) {
  return `${customHeadText(item, 'a')} - ${customHeadText(item, 'b')}`;
}

function customHeadText(item, side) {
  const gender = side === 'a' ? item.head_a_gender : item.head_b_gender;
  const type = side === 'a' ? item.head_a_type : item.head_b_type;
  if (!gender && !type) return '-';
  if (gender === '其他') return type ? `其他（${type}）` : '其他';
  return gender || type || '-';
}

function customStatusText(item) {
  return item?.status === '已取消' ? '中止' : (item?.status || '-');
}

function customStatusClass(item) {
  return {
    muted: ['已取消', '已忽略'].includes(item?.status),
  };
}

function isRequesterCanceledCustom(item) {
  return item?.status === '已取消' && !String(item?.handle_result || '').includes('内部取消');
}

function customSubmitterText(item) {
  return item.submitter || item.contact_name || item.contact_phone || '-';
}

function customRequestSupplementText(item) {
  const categoryText = [item.category_a, item.category_b].filter(Boolean).join(' / ');
  return [categoryText, item.scenario, item.note].filter(Boolean).join('；') || '-';
}

function customHandleResultText(item) {
  if (item?.handle_result === '内部忽略') return '暂不考虑';
  if (item?.status === '已忽略' && !item?.handle_result) return '暂不考虑';
  return item.handle_result || item.bound_product_label || '-';
}

function orderMatchesStatusFilter(order, filter) {
  if (!filter || filter === 'all') return order?.status !== '已删除';
  if (filter === '进行中') return orderInProgressStatuses.has(order?.status);
  return order?.status === filter;
}

function ordersForStatusFilter(rows, filter) {
  return rows.filter((item) => orderMatchesStatusFilter(item, filter));
}

function orderWorkflowStage(order) {
  if (order?.status === '已删除') return 'deleted';
  if (order?.status === '已完结') return 'done';
  if (order?.status === '未锁定') return 'pending';
  return 'active';
}

function orderDetailStage(order) {
  if (order?.status === '已删除') return '已删除';
  if (order?.status === '已完结') return '已完结';
  if (order?.status === '未锁定') return '未锁定';
  return '进行中';
}

function orderContractStatus(order) {
  if (order?.contract_uploaded_at || ['待发货', '待签收', '已完结'].includes(order?.status)) return '已签合同';
  if (order?.status === '未锁定') return '未锁定';
  return '待签合同';
}

function orderShipmentStatus(order) {
  if (order?.shipped_at || order?.status === '待签收') return '已发货';
  if (order?.received_at || order?.status === '已完结') return '已发货';
  if (order?.status === '待发货') return '待发货';
  return '未发货';
}

function orderInvoiceStatus(order) {
  if (order?.invoice_uploaded_at) return '已开票';
  return order?.invoice_status || order?.invoiceStatus || '未开票';
}

function orderPaymentStatus(order) {
  if (order?.paid_at) return '已收款';
  return order?.payment_status || order?.paymentStatus || '未收款';
}

function orderListStatus(order) {
  return orderDetailStage(order);
}

function orderBuyerName(order) {
  return order?.signing_company_name || order?.external_account_name || order?.owner_name || order?.customer_name || '-';
}

function orderSalespersonName(order) {
  return order?.salesperson_name || order?.owner_name || order?.owner_user_id || '-';
}

function orderSubmitterName(order) {
  if (order?.submitter_name) return order.submitter_name;
  if (order?.source === 'external') {
    return order?.external_account_name || order?.external_account_username || '-';
  }
  return order?.owner_name || order?.owner_user_id || '-';
}

function orderDetailProgressBubbleText(order, key) {
  if (key === 'contract') return orderContractStatus(order);
  if (key === 'shipment') return orderShipmentStatus(order);
  if (key === 'invoice') return orderInvoiceStatus(order);
  if (key === 'payment') return orderPaymentStatus(order);
  return '-';
}

function orderDetailProgressBubbleClass(order, key) {
  const text = orderDetailProgressBubbleText(order, key);
  return {
    done: ['已签合同', '已发货', '已签收', '已开票', '已收款'].includes(text),
    active: ['待签合同', '待发货', '待开票', '待收款'].includes(text),
  };
}

function orderProgressDoneStatus(key) {
  if (key === 'contract') return '已签合同';
  if (key === 'shipment') return '已发货';
  if (key === 'invoice') return '已开票';
  if (key === 'payment') return '已收款';
  return '';
}

function orderProgressPendingStatus(key) {
  if (key === 'contract') return '待签合同';
  if (key === 'shipment') return '待发货';
  if (key === 'invoice') return '未开票';
  if (key === 'payment') return '未收款';
  return '';
}

function orderProgressTime(order, key) {
  if (key === 'contract') return order?.contract_uploaded_at;
  if (key === 'shipment') return order?.shipped_at;
  if (key === 'invoice') return order?.invoice_uploaded_at;
  if (key === 'payment') return order?.paid_at;
  return '';
}

function orderProgressFileUrl(order, key) {
  if (key === 'contract') return order?.contract_file_url || '';
  if (key === 'shipment') return order?.shipment_file_url || '';
  if (key === 'invoice') return order?.invoice_file_url || '';
  if (key === 'payment') return order?.payment_file_url || '';
  return '';
}

function orderProgressFileName(order, key) {
  if (key === 'contract') return order?.contract_file_name || '查看附件';
  if (key === 'shipment') return order?.shipment_file_name || '查看附件';
  if (key === 'invoice') return order?.invoice_file_name || '查看附件';
  if (key === 'payment') return order?.payment_file_name || '查看附件';
  return '查看附件';
}

function orderProgressNoteField(key) {
  if (key === 'contract') return 'contract_note';
  if (key === 'shipment') return 'shipment_note';
  if (key === 'invoice') return 'invoice_note';
  if (key === 'payment') return 'payment_note';
  return '';
}

function orderProgressNoteKey(order, key) {
  return `${order?.id || 'new'}:${key}`;
}

function orderProgressNote(order, key) {
  const draftKey = orderProgressNoteKey(order, key);
  if (Object.prototype.hasOwnProperty.call(orderProgressNoteDrafts, draftKey)) {
    return orderProgressNoteDrafts[draftKey];
  }
  return order?.[orderProgressNoteField(key)] || '';
}

function setOrderProgressNote(order, key, value) {
  orderProgressNoteDrafts[orderProgressNoteKey(order, key)] = value;
}

function clearOrderProgressNoteDraft(order, key) {
  delete orderProgressNoteDrafts[orderProgressNoteKey(order, key)];
}

function canUploadOrderProgress(order, key) {
  if (isExternalMode.value) return false;
  if (!order || order.status === '未锁定' || order.status === '已删除') return false;
  return ['contract', 'shipment', 'invoice', 'payment'].includes(key);
}

function canCompleteOrderProgress(order, key) {
  if (isExternalMode.value) return false;
  if (!order || order.status === '未锁定' || order.status === '已删除') return false;
  return ['contract', 'shipment', 'invoice', 'payment'].includes(key);
}

function customBoundProductTitle(product) {
  return product?.abbr || product?.product_model || product?.label || '-';
}

function customBoundProductMeta(product) {
  return [
    product?.product_model,
    product?.category_a,
    product?.category_b,
    productParameterText(product),
  ].filter(Boolean).join(' / ') || '-';
}

function formatDateTime(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '-';
  const yyyy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, '0');
  const dd = String(date.getDate()).padStart(2, '0');
  const hh = String(date.getHours()).padStart(2, '0');
  const min = String(date.getMinutes()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd} ${hh}:${min}`;
}

function ensureDemoRegistrationData() {
  if (!registrationContacts.value.length) {
    registrationContacts.value = [
      { id: 'demo-contact-1', name: '李国强', contact: '13000000000', position: '产品经理' },
      { id: 'demo-contact-2', name: '周明', contact: 'wx-demo-zhou', position: '项目负责人' },
    ];
    saveRegistrationContacts();
  }
  if (!registrations.value.some((item) => item.company_name === demoRegistrationName)) {
    registrations.value.unshift({
      id: 'demo-registration-1',
      company_name: demoRegistrationName,
      credit_code: '91330100MA8DEMO001',
      contacts: [
        { id: 'demo-registration-contact-1', name: '王老师', contact: '13800000000', position: '信息中心' },
        { id: 'demo-registration-contact-2', name: '陈老师', contact: 'chen-demo', position: '采购负责人' },
      ],
      created_at: new Date().toISOString(),
    });
    saveRegistrations();
  }
}

async function ensureDemoData() {
  ensureDemoRegistrationData();
  await ensureDemoCustomRequests();
  await ensureDemoProject();
}

async function ensureDemoCustomRequests() {
  const demoRequests = [
    {
      head_a_type: 'HDMI',
      head_a_gender: '公头',
      head_b_type: '网线头',
      head_b_gender: '公头',
      length_m: 8,
      quantity: 4,
      note: '阶梯教室讲桌到显示终端；需要柔软线身',
    },
    {
      head_a_type: 'USB-C',
      head_a_gender: '公头',
      head_b_type: 'HDMI',
      head_b_gender: '公头',
      length_m: 3,
      quantity: 2,
      note: '移动授课设备；优先白色',
    },
  ];
  const missingRequests = demoRequests.filter((demoItem) => !customRequests.value.some((item) => (
    item.head_a_type === demoItem.head_a_type
    && item.head_b_type === demoItem.head_b_type
    && Number(item.length_m) === Number(demoItem.length_m)
    && item.note === demoItem.note
  )));
  if (!missingRequests.length) return;
  await Promise.all(missingRequests.map((item) => request('/custom-requests/', {
    method: 'POST',
    body: JSON.stringify(item),
  })));
  await loadCustomRequests();
}

async function ensureDemoProject() {
  if (projects.value.some((item) => item.name === demoProjectName)) return;
  const projectData = await request('/projects/', {
    method: 'POST',
    body: JSON.stringify({
      name: demoProjectName,
      note: '演示：项目、教室包与统计联动',
    }),
  });
  const project = projectData.item;
  await Promise.all(['标准教室A', '阶梯教室B'].flatMap((classroomName) => (
    ['教室内', '教室外'].map((scope) => request('/packages/', {
      method: 'POST',
      body: JSON.stringify({
        project_id: project.id,
        classroom_name: classroomName,
        classroom_scope: scope,
        name: `${classroomName}-${scope}`,
        note: scope === '教室内' ? '讲桌内线材' : '讲桌外线材',
        quantity: classroomName === '阶梯教室B' ? 1 : 2,
      }),
    }))
  )));
  await loadProjects();
  await loadPackages();
  await seedDemoPackageItems(project.id);
}

async function seedDemoPackageItems(projectId) {
  if (!drawerProducts.value.length) return;
  const projectPackageItems = activePackages.value.filter((item) => Number(item.project_id) === Number(projectId));
  if (projectPackageItems.some((item) => (item.items || []).length)) return;
  const demoProducts = drawerProducts.value.slice(0, 6);
  if (!demoProducts.length) return;
  const tasks = [];
  projectPackageItems.forEach((packageItem, packageIndex) => {
    const productA = demoProducts[packageIndex % demoProducts.length];
    const productB = demoProducts[(packageIndex + 2) % demoProducts.length];
    if (productA) {
      tasks.push(request(`/packages/${packageItem.id}/items/`, {
        method: 'POST',
        body: JSON.stringify({ product_id: productA.id, quantity: packageItem.classroom_scope === '教室内' ? 2 : 1 }),
      }));
    }
    if (productB && productB.id !== productA?.id) {
      tasks.push(request(`/packages/${packageItem.id}/items/`, {
        method: 'POST',
        body: JSON.stringify({ product_id: productB.id, quantity: packageItem.classroom_scope === '教室内' ? 1 : 3 }),
      }));
    }
  });
  await Promise.all(tasks);
  await loadPackages();
  await loadProjects();
}

function customCategoryContextText() {
  return [customCategoryContext.category_a, customCategoryContext.category_b].filter(Boolean).join(' / ');
}

function applyCustomCategoryContext(context = {}) {
  const categoryA = typeof context?.category_a === 'string' ? context.category_a.trim() : '';
  const categoryB = categoryA && typeof context?.category_b === 'string' ? context.category_b.trim() : '';
  customCategoryContext.category_a = categoryA;
  customCategoryContext.category_b = categoryB;
  customCategoryLocked.value = Boolean(categoryA && categoryB);
}

function selectCustomCategoryA(value) {
  customCategoryContext.category_a = value;
  customCategoryContext.category_b = '';
}

function selectCustomCategoryB(value) {
  customCategoryContext.category_b = value;
}

function customFormSnapshotValue() {
  return {
    form: formSnapshot(customForm),
    context: formSnapshot(customCategoryContext),
    restartingId: restartingCustomRequestId.value,
  };
}

function openCustomCreateModal(context = {}) {
  restartingCustomRequestId.value = null;
  applyCustomCategoryContext(context);
  if (!customCategoryLocked.value && !drawerProducts.value.length) loadDrawerProducts();
  customFormInitial.value = customFormSnapshotValue();
  customCreating.value = true;
}

function openCustomRestartModal(item) {
  if (!isRequesterCanceledCustom(item)) {
    setMessage('error', '内部取消的定制需求不能重新发起');
    return;
  }
  restartingCustomRequestId.value = item.id;
  applyCustomCategoryContext({ category_a: item.category_a || '', category_b: item.category_b || '' });
  if (!customCategoryLocked.value && !drawerProducts.value.length) loadDrawerProducts();
  Object.assign(customForm, {
    head_a_type: item.head_a_type || '',
    head_a_gender: item.head_a_gender || '公头',
    head_a_other: item.head_a_gender === '其他' ? (item.head_a_type || '') : '',
    head_b_type: item.head_b_type || '',
    head_b_gender: item.head_b_gender || '公头',
    head_b_other: item.head_b_gender === '其他' ? (item.head_b_type || '') : '',
    length_m: item.length_m || '',
    quantity: item.quantity || 1,
    note: item.note || item.scenario || '',
  });
  customFormInitial.value = customFormSnapshotValue();
  customCreating.value = true;
}

function goCustomFromAddCable(context = null) {
  const resolvedContext = context || (
    addCableModalOpen.value
      ? { category_a: addCableFilters.category_a, category_b: addCableFilters.category_b }
      : {}
  );
  openCustomCreateModal(resolvedContext);
}

function goCustomFromProductCatalog() {
  const context = { category_a: filters.category_a, category_b: filters.category_b };
  openCustomCreateModal(context);
}

function closeCustomCreateModal() {
  closeWithUnsavedGuard(customCreateHasChanges.value, () => {
    forceCloseCustomCreateModal();
  });
}

function forceCloseCustomCreateModal() {
  customCreating.value = false;
  restartingCustomRequestId.value = null;
  resetCustomForm();
  customFormInitial.value = {};
}

function resetCustomForm() {
  Object.assign(customForm, {
    head_a_type: '',
    head_a_gender: '公头',
    head_a_other: '',
    head_b_type: '',
    head_b_gender: '公头',
    head_b_other: '',
    length_m: '',
    quantity: 1,
    note: '',
  });
  applyCustomCategoryContext();
}

function clearGlobalMessages() {
  window.clearTimeout(messageFadeTimer);
  window.clearTimeout(messageClearTimer);
  messageFadeTimer = null;
  messageClearTimer = null;
  messageLeaving.value = false;
  notice.value = '';
  error.value = '';
}

function clearRegistrationContactErrors() {
  registrationContactErrors.name = '';
  registrationContactErrors.contact = '';
}

function clearRegistrationContactEditErrors() {
  registrationContactEditErrors.name = '';
  registrationContactEditErrors.contact = '';
}

function clearSettingsFeedback() {
  clearGlobalMessages();
  clearRegistrationContactErrors();
  clearRegistrationContactEditErrors();
}

function normalizeDraftValue(value) {
  if (Array.isArray(value)) return value.map((item) => normalizeDraftValue(item));
  if (value && typeof value === 'object') {
    return Object.keys(value).sort().reduce((acc, key) => {
      const item = value[key];
      if (item !== undefined && typeof item !== 'function') acc[key] = normalizeDraftValue(item);
      return acc;
    }, {});
  }
  if (value === undefined || value === null) return '';
  return String(value);
}

function draftChanged(current, initial) {
  return JSON.stringify(normalizeDraftValue(current)) !== JSON.stringify(normalizeDraftValue(initial));
}

function formSnapshot(form, keys = Object.keys(form)) {
  return keys.reduce((snapshot, key) => {
    snapshot[key] = form[key];
    return snapshot;
  }, {});
}

function closeUnsavedConfirm() {
  unsavedConfirm.open = false;
  unsavedConfirm.action = null;
  unsavedConfirm.cancelText = '继续编辑';
  unsavedConfirm.confirmText = '放弃修改';
  unsavedConfirm.confirmClass = '';
}

function confirmDiscardChanges() {
  const action = unsavedConfirm.action;
  closeUnsavedConfirm();
  if (typeof action === 'function') action();
}

function requestDiscardChanges(action, options = {}) {
  unsavedConfirm.title = options.title || '是否放弃修改';
  unsavedConfirm.message = options.message || '当前内容已有修改，退出后未保存的内容将不会保留。';
  unsavedConfirm.cancelText = options.cancelText || '继续编辑';
  unsavedConfirm.confirmText = options.confirmText || '放弃修改';
  unsavedConfirm.confirmClass = options.confirmClass || '';
  unsavedConfirm.action = action;
  unsavedConfirm.open = true;
}

function closeWithUnsavedGuard(hasChanges, action, options = {}) {
  if (hasChanges) {
    requestDiscardChanges(action, options);
    return false;
  }
  action();
  return true;
}

function currentDraftHasChanges() {
  return Boolean(
    (editingPackageId.value && packageEditHasChanges.value)
      || (projectCreating.value && projectCreateHasChanges.value)
      || detailHasUnsavedChanges.value
      || (addCableModalOpen.value && addCableHasChanges.value)
      || (classroomCreating.value && classroomCreateHasChanges.value)
      || (customCreating.value && customCreateHasChanges.value)
      || (customBinding.value && customBindHasChanges.value)
      || (externalAccountCreating.value && externalAccountCreateHasChanges.value)
      || (editingExternalAccountId.value && externalAccountEditHasChanges.value)
      || (shippingAddressCreating.value && shippingAddressCreateHasChanges.value)
      || (shippingAddressEditing.value && shippingAddressEditHasChanges.value)
      || (signingInfoCreating.value && signingInfoCreateHasChanges.value)
      || (signingInfoEditing.value && signingInfoEditHasChanges.value)
      || (productCartOpen.value && productCartModalHasChanges.value)
      || (orderCreateOpen.value && orderCreateHasChanges.value)
      || (orderAddressPickerOpen.value && orderAddressPickerHasChanges.value)
      || (orderSigningInfoPickerOpen.value && orderSigningInfoPickerHasChanges.value)
      || (activeTab.value === 'admin-settings' && adminPermissionDirty.value)
  );
}

function discardCurrentDrafts() {
  closeUnsavedConfirm();
  if (orderSigningInfoPickerOpen.value) forceCloseOrderSigningInfoDrawer();
  if (orderAddressPickerOpen.value) forceCloseOrderAddressDrawer();
  if (orderCreateOpen.value) forceCloseOrderCreate();
  if (productCartOpen.value) forceCloseProductCartModal();
  if (addCableModalOpen.value) forceCloseAddCableModal();
  if (projectCreating.value) forceCloseProjectCreateModal();
  if (classroomCreating.value) forceCloseClassroomCreateModal();
  if (customCreating.value) forceCloseCustomCreateModal();
  if (customBinding.value) forceCloseCustomBindModal();
  if (customBoundDetailOpen.value) closeCustomBoundDetail();
  if (externalAccountCreating.value) {
    externalAccountCreating.value = false;
    externalAccountCreatedCredential.value = null;
    resetExternalAccountForm();
    externalAccountFormInitial.value = {};
  }
  if (editingExternalAccountId.value) forceCancelExternalAccountEdit();
  if (shippingAddressCreating.value) forceCloseShippingAddressCreateModal();
  if (shippingAddressEditing.value) forceCancelShippingAddressEdit();
  if (signingInfoCreating.value) forceCloseSigningInfoCreateModal();
  if (signingInfoEditing.value) forceCancelSigningInfoEdit();
  if (editingPackageId.value) forceCancelPackageEdit();
  if (detailPackage.value) discardPackageDetailChanges();
  if (adminPermissionDirty.value) {
    adminPermissionRules.value = adminPermissionInitialRules.value.map((rule) => ({ ...rule }));
    closePermissionPicker();
  }
}

function guardBeforeLeavingCurrentDraft(action) {
  if (!currentDraftHasChanges()) {
    action();
    return;
  }
  requestDiscardChanges(() => {
    discardCurrentDrafts();
    action();
  });
}

const tabs = [
  { key: 'products', label: '单品下单', icon: ShoppingCart, group: '线材购买' },
  { key: 'projects', label: '项目下单', icon: FolderKanban, group: '线材购买' },
  { key: 'custom', label: '定制需求', icon: Wrench, group: '需求管理' },
  { key: 'orders', label: '订单管理', icon: FolderKanban, group: '订单管理' },
  { key: 'shipping-addresses', label: '收货地址管理', icon: MapPin, group: '账号与信息' },
  { key: 'signing-infos', label: '公司抬头管理', icon: Building2, group: '账号与信息' },
  { key: 'external-accounts', label: '外部账号管理', icon: UsersRound, internalOnly: true, group: '账号与信息' },
  { key: 'registration', label: '账号信息设置', icon: UserRound, group: '账号与信息', externalOnly: true },
  { key: 'admin-settings', label: '设置', icon: ShieldCheck, adminOnly: true, group: '系统设置' },
];
const orderCreateModes = ['cart-products', 'project-classrooms'];
const orderStatusTabs = [
  { key: 'all', label: '全部' },
  { key: '未锁定', label: '未锁定' },
  { key: '进行中', label: '进行中' },
  { key: '已完结', label: '已完结' },
  { key: '已删除', label: '已删除' },
];
const externalAccountStatusTabs = [
  { key: 'active', label: '启用' },
  { key: 'disabled', label: '停用' },
];
const orderInProgressStatuses = new Set(['待签合同', '待发货', '待签收']);
const orderDetailProgressBubbles = [
  { key: 'contract', label: '合同签订', statusOptions: ['待签合同', '已签合同'] },
  { key: 'shipment', label: '发货', statusOptions: ['未发货', '待发货', '已发货'] },
  { key: 'invoice', label: '开票', statusOptions: ['未开票', '待开票', '已开票'] },
  { key: 'payment', label: '收款', statusOptions: ['未收款', '待收款', '已收款'] },
];
const orderWorkflowFileAccept = '.pdf,.jpg,.jpeg,.png,.gif,.webp,.bmp,.jfif';
const classroomDetailScopes = [
  { key: '教室内', label: '讲桌内线' },
  { key: '教室外', label: '讲桌外线' },
];

const activePackages = computed(() => packages.value.filter((item) => !item.is_archived));
const activeProjects = computed(() => projects.value.filter((item) => !item.is_archived));
const filteredProjects = computed(() => {
  const keyword = projectSearch.value.trim().toLowerCase();
  if (!keyword) return activeProjects.value;
  return activeProjects.value.filter((item) => [
    item.name,
    item.note,
  ].join(' ').toLowerCase().includes(keyword));
});
const filteredArchivedProjects = computed(() => {
  const keyword = recycleSearch.value.trim().toLowerCase();
  if (!keyword) return archivedProjectRows.value;
  return archivedProjectRows.value.filter((item) => [
    item.name,
    item.note,
  ].join(' ').toLowerCase().includes(keyword));
});
const filteredCustomRequests = computed(() => filterCustomRequests(customSearch.value));
const activeCustomBindRequest = computed(() => (
  customRequests.value.find((item) => Number(item.id) === Number(customBindForm.requestId)) || null
));

function productOrderUnitPrice(product, fallback = 0) {
  const salespersonPrice = product?.salesperson_price;
  const raw = salespersonPrice === null || salespersonPrice === undefined || String(salespersonPrice).trim() === ''
    ? product?.unit_price ?? fallback
    : salespersonPrice;
  const price = Number(raw);
  return Number.isFinite(price) && price >= 0 ? price : Number(fallback) || 0;
}

const productCartSummary = computed(() => {
  const quantity = productCartItems.value.reduce((sum, item) => sum + Number(item.quantity || 0), 0);
  const amount = productCartItems.value.reduce((sum, item) => {
    return sum + productOrderUnitPrice(item.product) * Number(item.quantity || 0);
  }, 0);
  return {
    count: productCartItems.value.length,
    quantity,
    amount: amount.toFixed(2),
  };
});
const sortedProductCartItems = computed(() => sortCableProducts(productCartItems.value, (item) => item.product));
const productCartOrderRows = computed(() => sortedProductCartItems.value.map((item) => {
  const product = item.product || {};
  const quantity = Math.max(Math.floor(Number(item.quantity || 1)), 1);
  return {
    ...item,
    order_key: `cart-product:${product.id}`,
    order_source: 'cart-product',
    order_type: '购物车',
    order_display_name: product.abbr || product.label || '-',
    order_note: [product.product_model, product.category_a, product.category_b].filter(Boolean).join(' / ') || '-',
    order_quantity_default: quantity,
    order_package_count: 1,
    item_count: 1,
    cable_count: 1,
    order_amount: productOrderUnitPrice(product),
    product,
  };
}));
const systemCategoryAOptions = computed(() => sortCategoryValues([
  ...categoriesA.value,
  ...addCableCategoriesA.value,
  ...drawerProducts.value.map((product) => product.category_a),
  ...products.value.map((product) => product.category_a),
  ...addCableProducts.value.map((product) => product.category_a),
]));
const systemCategoryBOptions = computed(() => {
  const categoryA = customCategoryContext.category_a;
  return sortCategoryValues([
    ...drawerProducts.value
      .filter((product) => !categoryA || product.category_a === categoryA)
      .map((product) => product.category_b),
    ...products.value
      .filter((product) => !categoryA || product.category_a === categoryA)
      .map((product) => product.category_b),
    ...addCableProducts.value
      .filter((product) => !categoryA || product.category_a === categoryA)
      .map((product) => product.category_b),
    ...(categoryA && filters.category_a === categoryA ? categoriesB.value : []),
    ...(categoryA && addCableFilters.category_a === categoryA ? addCableCategoriesB.value : []),
  ]);
});
const filteredCustomBindProducts = computed(() => {
  const keyword = customBindSearch.value.trim().toLowerCase();
  const rows = sortCableProducts(drawerProducts.value);
  if (!keyword) return rows.slice(0, 200);
  return rows.filter((product) => [
    product.abbr,
    product.label,
    product.product_brand,
    product.product_model,
    product.category_a,
    product.category_b,
    product.kingdee_code,
    product.spec_text,
    productParameterText(product),
  ].join(' ').toLowerCase().includes(keyword)).slice(0, 200);
});
const orderableProjectRows = computed(() => activeProjects.value
    .map((project) => {
      const projectPackageRows = projectPackages(project).filter((item) => (item.items || []).length > 0);
      const packageCount = projectPackageRows.reduce((sum, item) => sum + Number(item.quantity || 1), 0);
      const itemCount = projectPackageRows.reduce((sum, item) => sum + Number(item.item_count || 0), 0);
      const cableCount = projectPackageRows.reduce((sum, item) => sum + Number(item.cable_count || 0) * Number(item.quantity || 1), 0);
      const amount = projectPackageRows.reduce((sum, item) => sum + Number(packageAmount(item)) * Number(item.quantity || 1), 0);
      return {
        ...project,
        order_key: `project:${project.id}`,
        order_source: 'project',
        order_type: '项目',
        order_display_name: project.name,
        order_note: project.note || '-',
        order_packages: projectPackageRows,
        order_quantity_default: 1,
        order_package_count: packageCount,
        item_count: itemCount,
        cable_count: cableCount,
        order_amount: amount,
      };
    })
    .filter((item) => item.order_packages.length > 0));
const allOrderablePackageRows = computed(() => [
  ...productCartOrderRows.value,
  ...orderableProjectRows.value,
]);
const orderCopyRows = computed(() => {
  const products = orderCopyDraft.value?.products || [];
  return products.map((item) => {
    const product = item.product || {};
    const quantity = Math.max(Math.floor(Number(item.quantity || 1)), 1);
    return {
      order_key: `copy-product:${item.product_id || product.id}`,
      order_source: 'copy-product',
      order_type: '复制订单',
      order_display_name: product.abbr || product.label || '-',
      order_note: [product.product_model, product.category_a, product.category_b].filter(Boolean).join(' / ') || '-',
      order_quantity_default: quantity,
      order_package_count: 1,
      item_count: 1,
      cable_count: 1,
      order_amount: productOrderUnitPrice(product),
      product,
      product_id: item.product_id || product.id,
    };
  });
});
const orderEditRows = computed(() => {
  const products = orderEditDraft.value?.products || [];
  return products.map((item) => {
    const product = item.product || {};
    const quantity = Math.max(Math.floor(Number(item.quantity || 1)), 1);
    return {
      order_key: `edit-product:${item.product_id || product.id}`,
      order_source: 'edit-product',
      order_type: '编辑订单',
      order_display_name: product.abbr || product.label || item.product_abbr || item.product_label || '-',
      order_note: [product.product_model || item.product_model, product.category_a || item.category_a, product.category_b || item.category_b].filter(Boolean).join(' / ') || '-',
      order_quantity_default: quantity,
      order_package_count: 1,
      item_count: 1,
      cable_count: 1,
      order_amount: productOrderUnitPrice(product, item.unit_price),
      product,
      product_id: item.product_id || product.id,
    };
  });
});
const orderablePackageRows = computed(() => {
  if (orderCreateTab.value === 'order-edit') return orderEditRows.value;
  if (orderCreateTab.value === 'order-copy') return orderCopyRows.value;
  let rows = productCartOrderRows.value;
  if (orderCreateTab.value === 'project-classrooms') {
    const selectedKeys = new Set(Object.entries(selectedOrderPackageIds)
      .filter(([, selected]) => selected)
      .map(([key]) => key));
    rows = orderableProjectRows.value
      .filter((item) => selectedKeys.has(item.order_key))
      .flatMap((item) => projectOrderCableRows(item).map((row) => ({
        ...row,
        order_key: `project-cable:${item.id}:${row.key}`,
        order_source: 'project-cable',
        order_type: '项目线材',
        order_display_name: row.product_abbr || row.product_label || '-',
        order_note: [row.product_model, row.category_a, row.category_b].filter(Boolean).join(' / ') || '-',
        order_quantity_default: row.quantity,
        order_amount: Number(row.unit_price || 0),
        line_amount: Number(row.amount || 0),
        project_order_key: item.order_key,
      })));
  }
  const keyword = orderCreateSearch.value.trim().toLowerCase();
  if (!keyword) return rows;
  return rows.filter((item) => [
    item.order_type,
    item.order_display_name,
    item.name,
    item.note,
    item.order_note,
  ].join(' ').toLowerCase().includes(keyword));
});
const orderProjectClassroomRows = computed(() => {
  if (orderCreateTab.value !== 'project-classrooms') return [];
  const selectedKeys = new Set(Object.entries(selectedOrderPackageIds)
    .filter(([, selected]) => selected)
    .map(([key]) => key));
  const rows = [];
  orderableProjectRows.value
    .filter((project) => selectedKeys.has(project.order_key))
    .forEach((project) => {
      const classroomMap = new Map();
      (project.order_packages || []).forEach((packageItem) => {
        const name = packageItem.classroom_name || packageItem.name || '未命名教室';
        if (!classroomMap.has(name)) {
          classroomMap.set(name, {
            name,
            note: packageItem.note || '',
            indoor: null,
            outdoor: null,
            packages: [],
          });
        }
        const classroom = classroomMap.get(name);
        classroom.packages.push(packageItem);
        if (packageItem.classroom_scope === '教室外') classroom.outdoor = packageItem;
        else classroom.indoor = packageItem;
      });
      Array.from(classroomMap.values()).forEach((classroom) => {
        const scopeRows = classroomScopeRows(classroom);
        rows.push({
          key: `${project.id}:${classroom.name}`,
          project_id: project.id,
          project_name: project.name,
          classroom,
          name: classroom.name,
          note: classroom.note,
          scope_rows: scopeRows,
          room_count: classroomRoomCount(classroom),
          single_amount: classroomTotalAmount(classroom),
          total_amount: classroomGrandAmount(classroom),
          kind_count: scopeRows.reduce((sum, row) => sum + classroomScopeKindCount(row), 0),
          cable_count: scopeRows.reduce((sum, row) => sum + classroomScopeCableCount(row), 0),
        });
      });
    });
  const keyword = orderCreateSearch.value.trim().toLowerCase();
  if (!keyword) return rows;
  return rows.filter((item) => [
    item.project_name,
    item.name,
    item.note,
    item.scope_rows.map((row) => row.label).join(' '),
  ].join(' ').toLowerCase().includes(keyword));
});
const orderCreateSearchPlaceholder = computed(() => {
  if (orderCreateTab.value === 'order-edit') return '搜索订单线材';
  if (orderCreateTab.value === 'order-copy') return '搜索复制线材';
  if (orderCreateTab.value === 'project-classrooms') {
    return orderProjectViewMode.value === 'classrooms' ? '搜索教室' : '搜索项目线材';
  }
  return '搜索购物车线材';
});
const orderCreateNameHeader = computed(() => {
  if (orderCreateTab.value === 'order-edit') return '线材';
  if (orderCreateTab.value === 'order-copy') return '线材';
  return '线材';
});
const orderCreateEmptyText = computed(() => {
  if (orderCreateTab.value === 'order-edit') return '订单暂无可编辑线材';
  if (orderCreateTab.value === 'order-copy') return '原订单暂无可复制线材';
  if (orderCreateTab.value === 'project-classrooms') {
    return orderProjectViewMode.value === 'classrooms' ? '暂无教室' : '暂无项目线材';
  }
  return '购物车暂无线材';
});
const orderCreateTitle = computed(() => (
  orderCreateTab.value === 'order-edit'
    ? `编辑订单：${orderEditDraft.value?.order_no || '-'}`
    : orderCreateTab.value === 'order-copy'
      ? '复制下单'
      : orderCreateTab.value === 'project-classrooms'
        ? '项目下单'
        : '单品下单'
));
const orderSubmitText = computed(() => (
  orderCreateTab.value === 'order-edit' ? '保存订单' : '提交订单'
));
const selectedOrderPackages = computed(() => {
  if (orderCreateTab.value === 'order-edit') return orderEditRows.value.filter((item) => selectedOrderPackageIds[item.order_key]);
  if (orderCreateTab.value === 'order-copy') return orderCopyRows.value.filter((item) => selectedOrderPackageIds[item.order_key]);
  return allOrderablePackageRows.value.filter((item) => selectedOrderPackageIds[item.order_key]);
});
const selectableOrderCustomers = computed(() => externalAccounts.value.filter((item) => item.status === 'active'));
const selectedOrderCustomer = computed(() => (
  props.externalMode
    ? currentSession.value
    : selectableOrderCustomers.value.find((item) => Number(item.id) === Number(orderForm.external_account_id)) || null
));
const selectedOrderShippingAddress = computed(() => (
  shippingAddresses.value.find((item) => Number(item.id) === Number(orderForm.shipping_address_id)) || null
));
const pendingOrderShippingAddress = computed(() => (
  shippingAddresses.value.find((item) => Number(item.id) === Number(pendingOrderShippingAddressId.value)) || null
));
const selectedOrderSigningInfo = computed(() => (
  signingInfos.value.find((item) => Number(item.id) === Number(orderForm.signing_info_id)) || null
));
const pendingOrderSigningInfo = computed(() => (
  signingInfos.value.find((item) => Number(item.id) === Number(pendingOrderSigningInfoId.value)) || null
));
const sortedShippingAddresses = computed(() => [...shippingAddresses.value].sort((left, right) => (
  new Date(right.updated_at || 0).getTime() - new Date(left.updated_at || 0).getTime()
)));
const sortedSigningInfos = computed(() => [...signingInfos.value].sort((left, right) => (
  new Date(right.updated_at || 0).getTime() - new Date(left.updated_at || 0).getTime()
)));
const filteredOrderShippingAddresses = computed(() => {
  const keyword = orderAddressSearch.value.trim().toLowerCase();
  const rows = sortedShippingAddresses.value;
  if (!keyword) return rows;
  return rows.filter((item) => [
    item.detail_address,
    item.receiver_name,
    item.receiver_phone,
    item.created_by,
    item.created_at,
    item.updated_at,
  ].join(' ').toLowerCase().includes(keyword));
});
const filteredOrderSigningInfos = computed(() => {
  const keyword = orderSigningInfoSearch.value.trim().toLowerCase();
  const rows = sortedSigningInfos.value;
  if (!keyword) return rows;
  return rows.filter((item) => [
    item.company_name,
    item.opening_bank,
    item.tax_number,
    item.bank_account,
    item.created_by,
    item.created_at,
    item.updated_at,
  ].join(' ').toLowerCase().includes(keyword));
});
const selectedOrderSummary = computed(() => {
  const summary = selectedOrderPackages.value.reduce((total, item) => {
    const quantity = Math.max(Math.floor(Number(orderPackageQuantities[item.order_key] || item.order_quantity_default || 1)), 1);
    if (item.order_source === 'project') {
      total.projectCount += 1;
    } else if (['cart-product', 'copy-product', 'edit-product'].includes(item.order_source)) {
      total.productCount += 1;
    }
    total.cableCount += Number(item.cable_count || 0) * quantity;
    total.amount += ['cart-product', 'copy-product', 'edit-product'].includes(item.order_source)
      ? productOrderUnitPrice(item.product, item.order_amount) * quantity
      : Number(item.order_amount || 0) * quantity;
    return total;
  }, { packageCount: 0, projectCount: 0, productCount: 0, cableCount: 0, amount: 0 });
  return {
    projectCount: summary.projectCount,
    productCount: summary.productCount,
    cableCount: summary.cableCount,
    amount: summary.amount.toFixed(2),
  };
});
const filteredOrders = computed(() => {
  const keyword = orderSearch.value.trim().toLowerCase();
  const statusRows = ordersForStatusFilter(orders.value, orderStatusFilter.value);
  if (!keyword) return statusRows;
  return statusRows.filter((item) => [
    item.order_no,
    orderBuyerName(item),
    orderSalespersonName(item),
    orderSubmitterName(item),
    item.customer_name,
    item.customer_phone,
    item.project_name,
    item.remark,
    item.source_label,
    item.owner_name,
    item.salesperson_name,
    item.salesperson_user_id,
    item.submitter_name,
    item.submitter_user_id,
    item.external_account_username,
    item.external_account_name,
    item.signing_company_name,
    item.signing_opening_bank,
    item.signing_tax_number,
    item.signing_bank_account,
    item.total_amount,
    item.status,
    orderListStatus(item),
    orderContractStatus(item),
    orderShipmentStatus(item),
    orderInvoiceStatus(item),
    orderPaymentStatus(item),
    item.created_at,
  ].join(' ').toLowerCase().includes(keyword));
});
const orderStatusCounts = computed(() => orderStatusTabs.reduce((summary, tab) => ({
  ...summary,
  [tab.key]: ordersForStatusFilter(orders.value, tab.key).length,
}), {}));
const orderDetailTabs = [
  { key: 'info', label: '订单信息' },
  { key: 'products', label: '产品信息' },
];
const orderDetailProjectProductViews = [
  { key: 'classrooms', label: '教室视图' },
  { key: 'cables', label: '线材视图' },
];
const selectedOrderProductRows = computed(() => {
  const rows = new Map();
  (selectedOrder.value?.packages || []).forEach((orderPackage) => {
    const packageQuantity = Math.max(Math.floor(Number(orderPackage.package_quantity || 1)), 1);
    (orderPackage.items || []).forEach((item) => {
      const key = String(item.product_archive_id || item.id);
      if (!rows.has(key)) {
        rows.set(key, {
          key,
          product_abbr: item.product_abbr,
          product_label: item.product_label,
          product_model: item.product_model,
          category_a: item.category_a,
          category_b: item.category_b,
          unit_price: item.unit_price || '0.00',
          quantity: 0,
          amount: 0,
        });
      }
      const row = rows.get(key);
      const quantity = Number(item.quantity_per_package || 0) * packageQuantity;
      row.quantity += quantity;
      row.amount += Number(item.unit_price || 0) * quantity;
    });
  });
  return sortCableProducts(Array.from(rows.values()), (row) => row).map((row) => ({
    ...row,
    amount_text: row.amount.toFixed(2),
  }));
});
const selectedOrderClassroomRows = computed(() => {
  const groups = new Map();
  (selectedOrder.value?.packages || []).forEach((orderPackage) => {
    const classroomName = orderPackage.classroom_name || inferOrderPackageClassroomName(orderPackage);
    const scope = orderPackage.classroom_scope || inferOrderPackageClassroomScope(orderPackage);
    if (!classroomName || !scope) return;
    const key = `${orderPackage.source_project_id || orderPackage.project_name || 'project'}:${classroomName}`;
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        name: classroomName,
        project_name: orderPackage.project_name || '',
        note: orderPackage.package_note || '',
        indoor: null,
        outdoor: null,
        packages: [],
      });
    }
    const group = groups.get(key);
    const normalizedPackage = {
      ...orderPackage,
      name: orderPackage.package_name,
      note: orderPackage.package_note,
      quantity: orderPackage.package_quantity,
      item_count: (orderPackage.items || []).length,
      cable_count: (orderPackage.items || []).reduce((sum, item) => sum + Number(item.quantity_per_package || 0), 0),
      items: orderPackage.items || [],
    };
    group.packages.push(normalizedPackage);
    if (scope === '教室外') group.outdoor = normalizedPackage;
    else group.indoor = normalizedPackage;
  });
  return Array.from(groups.values()).map((classroom) => {
    const scopeRows = classroomScopeRows(classroom);
    return {
      ...classroom,
      scope_rows: scopeRows,
      room_count: orderDetailClassroomRoomCount(classroom),
      single_amount: orderDetailClassroomSingleAmount(classroom),
      total_amount: orderDetailClassroomTotalAmount(classroom),
      kind_count: scopeRows.reduce((sum, row) => sum + classroomScopeKindCount(row), 0),
      cable_count: scopeRows.reduce((sum, row) => sum + orderDetailScopeCableCount(row), 0),
    };
  });
});
const selectedOrderHasProjectView = computed(() => selectedOrderClassroomRows.value.length > 0);
const filteredShippingAddresses = computed(() => {
  const keyword = shippingAddressSearch.value.trim().toLowerCase();
  const rows = sortedShippingAddresses.value;
  if (!keyword) return rows;
  return rows.filter((item) => [
    item.detail_address,
    item.receiver_name,
    item.receiver_phone,
    item.created_by,
    item.created_at,
  ].join(' ').toLowerCase().includes(keyword));
});
const filteredSigningInfos = computed(() => {
  const keyword = signingInfoSearch.value.trim().toLowerCase();
  const rows = sortedSigningInfos.value;
  if (!keyword) return rows;
  return rows.filter((item) => [
    item.company_name,
    item.opening_bank,
    item.tax_number,
    item.bank_account,
    item.created_by,
    item.created_at,
    item.updated_at,
  ].join(' ').toLowerCase().includes(keyword));
});
const filteredExternalAccounts = computed(() => {
  const keyword = externalAccountSearch.value.trim().toLowerCase();
  const rows = externalAccounts.value.filter((item) => item.status === externalAccountStatusTab.value);
  if (!keyword) return rows;
  return rows.filter((item) => [
    item.username,
    item.display_name,
    item.credit_code,
    item.owner_name,
    item.owner_user_id,
    item.status_label,
    item.created_at,
    item.updated_at,
  ].join(' ').toLowerCase().includes(keyword));
});
const externalAccountStatusCounts = computed(() => (
  externalAccountStatusTabs.reduce((counts, tab) => {
    counts[tab.key] = externalAccounts.value.filter((item) => item.status === tab.key).length;
    return counts;
  }, {})
));
const visibleTabs = computed(() => tabs.filter((tab) => {
  if (props.externalMode && tab.internalOnly) return false;
  if (!props.externalMode && tab.externalOnly) return false;
  if (tab.adminOnly && !cableMallPermission.value.canManageCableMall) return false;
  return true;
}));
const sidebarSections = computed(() => {
  const sections = [];
  const groupMap = new Map();
  visibleTabs.value.forEach((tab) => {
    const group = tab.group || '其他';
    if (!groupMap.has(group)) {
      const section = { key: group, label: group, tabs: [] };
      groupMap.set(group, section);
      sections.push(section);
    }
    groupMap.get(group).tabs.push(tab);
  });
  return sections;
});
const platformSidebarSections = computed(() => [...sidebarSections.value.map((section) => ({
  ...section,
  id: section.key,
  items: section.tabs.map((tab) => ({
    ...tab,
    id: tab.key,
  })),
})), ...(!props.externalMode ? [{ id: "suggestions", label: "优化建议", items: [{ id: "suggestions", label: "本软件优化建议", icon: FileText }] }] : [])]);
const activeTabMeta = computed(() => tabs.find((tab) => tab.key === activeTab.value));
const permissionGroups = [
  {
    id: 'admin',
    label: '线材商城管理员',
    note: '可进入线材商城并维护线材权限设置。',
    icon: ShieldCheck,
  },
  {
    id: 'user',
    label: '线材商城普通用户',
    note: '可进入线材商城使用线材业务功能。',
    icon: UsersRound,
  },
];
const permissionScopeGroups = [
  { id: 'department', label: '部门', icon: Building2, empty: '未添加部门' },
  { id: 'employee', label: '成员', icon: UserRound, empty: '未添加成员' },
];
const permissionPickerTitle = computed(() => {
  const scope = permissionScopeGroups.find((item) => item.id === permissionPicker.scopeType)?.label || '';
  return `添加${scope}`;
});
const permissionDepartmentTree = computed(() => normalizePermissionDepartmentTree(permissionDirectory.departments));
const permissionDepartmentRows = computed(() => flattenPermissionDepartments(permissionDepartmentTree.value));
const permissionDepartmentById = computed(() => new Map(permissionDepartmentRows.value.map((item) => [item.id, item])));
const permissionEmployeeRows = computed(() => (permissionDirectory.employees || [])
  .map(normalizePermissionEmployee)
  .filter((item) => item.id));
const permissionEmployeeById = computed(() => new Map(permissionEmployeeRows.value.map((item) => [item.id, item])));
const activeAdminPermission = computed(() => (
  permissionGroups.find((item) => item.id === activeAdminPermissionId.value) || permissionGroups[0]
));
const activePermissionMemberRows = computed(() => permissionMemberRows(activeAdminPermissionId.value));
const activePermissionExcludedRows = computed(() => permissionExcludedMemberRows(activeAdminPermissionId.value));
const adminPermissionDirty = computed(() => (
  serializeAdminPermissionRules(adminPermissionRules.value) !== adminPermissionSnapshot.value
));
const permissionPickerRows = computed(() => {
  const keyword = permissionPicker.keyword.trim().toLowerCase();
  if (permissionPicker.scopeType === 'department') {
    const filteredTree = filterPermissionDepartmentTree(permissionDepartmentTree.value, keyword);
    return flattenPermissionPickerDepartments(filteredTree, 0, Boolean(keyword));
  }
  return permissionEmployeeRows.value
    .map((item) => ({
      ...item,
      subtitle: permissionEmployeeDepartmentText(item),
      selected: permissionRuleExists(permissionPicker.permission, 'employee', item.id),
    }))
    .filter((item) => permissionEmployeeMatches(item, keyword));
});
const selectedProject = computed(() => activeProjects.value.find((item) => item.id === Number(selectedProjectId.value)));
const selectedProjectPackages = computed(() => {
  if (!selectedProject.value) return [];
  return activePackages.value.filter((item) => Number(item.project_id) === Number(selectedProject.value.id));
});
const projectClassrooms = computed(() => {
  const groups = new Map();
  selectedProjectPackages.value.forEach((item) => {
    const name = item.classroom_name || item.name || '未命名教室';
    if (!groups.has(name)) {
      groups.set(name, {
        name,
        note: item.note || '',
        indoor: null,
        outdoor: null,
        packages: [],
      });
    }
    const group = groups.get(name);
    group.packages.push(item);
    if (item.classroom_scope === '教室外') group.outdoor = item;
    else if (item.classroom_scope === '教室内') group.indoor = item;
  });
  return Array.from(groups.values());
});
const filteredProjectClassrooms = computed(() => {
  const keyword = classroomForm.name.trim().toLowerCase();
  if (!keyword) return projectClassrooms.value;
  return projectClassrooms.value.filter((classroom) => classroom.name.toLowerCase().includes(keyword));
});
const filteredProjectClassroomSummary = computed(() => {
  const packageAmountTotal = filteredProjectClassrooms.value.reduce((sum, classroom) => {
    return sum + Number(classroomTotalAmount(classroom));
  }, 0);
  const grandAmountTotal = filteredProjectClassrooms.value.reduce((sum, classroom) => {
    return sum + Number(classroomGrandAmount(classroom));
  }, 0);
  return {
    packageAmount: packageAmountTotal.toFixed(2),
    grandAmount: grandAmountTotal.toFixed(2),
  };
});
const projectStatsRows = computed(() => {
  const rows = new Map();
  selectedProjectPackages.value.forEach((packageItem) => {
    const roomCount = Math.max(Math.floor(Number(packageItem.quantity || 1)), 1);
    (packageItem.items || []).forEach((item) => {
      const key = String(item.product_archive_id || item.id);
      if (!rows.has(key)) {
        rows.set(key, {
          key,
          product_image: '',
          product_abbr: item.product_abbr,
          product_label: item.product_label,
          product_model: item.product_model,
          category_a: item.category_a || '-',
          category_b: item.category_b || '-',
          unit_price: item.unit_price || '0.00',
          quantity: 0,
          amount: 0,
          plan_para: item.spec_text || '-',
        });
      }
      const row = rows.get(key);
      const quantity = Number(item.quantity || 0) * roomCount;
      row.quantity += quantity;
      row.amount += Number(item.unit_price || 0) * quantity;
    });
  });
  return sortCableProducts(Array.from(rows.values()), (row) => row).map((row) => ({
    ...row,
    amount_text: row.amount.toFixed(2),
  }));
});
const projectStatsCategoriesA = computed(() => Array.from(new Set(projectStatsRows.value.map((row) => row.category_a).filter(Boolean))));
const projectStatsCategoriesB = computed(() => Array.from(new Set(
  projectStatsRows.value
    .filter((row) => !projectStatsFilters.category_a || row.category_a === projectStatsFilters.category_a)
    .map((row) => row.category_b)
    .filter(Boolean),
)));
const filteredProjectStatsRows = computed(() => {
  const keyword = projectStatsFilters.q.trim().toLowerCase();
  return projectStatsRows.value.filter((row) => {
    if (projectStatsFilters.category_a && row.category_a !== projectStatsFilters.category_a) return false;
    if (projectStatsFilters.category_b && row.category_b !== projectStatsFilters.category_b) return false;
    if (!keyword) return true;
    return [
      row.product_abbr,
      row.product_label,
      row.product_model,
      row.category_a,
      row.category_b,
      row.plan_para,
    ].join(' ').toLowerCase().includes(keyword);
  });
});
const filteredProjectStatsSummary = computed(() => {
  const quantity = filteredProjectStatsRows.value.reduce((sum, row) => sum + Number(row.quantity || 0), 0);
  const amount = filteredProjectStatsRows.value.reduce((sum, row) => sum + Number(row.amount || 0), 0);
  return {
    quantity,
    amount: amount.toFixed(2),
  };
});
const groupedProjectStatsRows = computed(() => {
  const primaryGroups = [];
  const primaryMap = new Map();
  filteredProjectStatsRows.value.forEach((row) => {
    const categoryA = row.category_a || '-';
    const categoryB = row.category_b || '-';
    if (!primaryMap.has(categoryA)) {
      const group = { categoryA, rows: [], secondaryGroups: [], secondaryMap: new Map() };
      primaryMap.set(categoryA, group);
      primaryGroups.push(group);
    }
    const primaryGroup = primaryMap.get(categoryA);
    primaryGroup.rows.push(row);
    if (!primaryGroup.secondaryMap.has(categoryB)) {
      const secondaryGroup = { categoryB, rows: [] };
      primaryGroup.secondaryMap.set(categoryB, secondaryGroup);
      primaryGroup.secondaryGroups.push(secondaryGroup);
    }
    primaryGroup.secondaryMap.get(categoryB).rows.push(row);
  });

  const output = [];
  primaryGroups.forEach((primaryGroup) => {
    let primaryRowIndex = 0;
    primaryGroup.secondaryGroups.forEach((secondaryGroup) => {
      secondaryGroup.rows.forEach((row, secondaryRowIndex) => {
        output.push({
          row,
          categoryA: primaryGroup.categoryA,
          categoryB: secondaryGroup.categoryB,
          categoryARowspan: primaryRowIndex === 0 ? primaryGroup.rows.length : 0,
          categoryBRowspan: secondaryRowIndex === 0 ? secondaryGroup.rows.length : 0,
          index: output.length + 1,
        });
        primaryRowIndex += 1;
      });
    });
  });
  return output;
});
const detailPackage = computed(() => activePackages.value.find((item) => item.id === Number(packageDetailId.value)));
const detailIsClassroomPackage = computed(() => Boolean(detailPackage.value?.project_id && detailPackage.value?.classroom_name));
const detailClassroomPackages = computed(() => {
  if (!detailIsClassroomPackage.value) return [];
  return activePackages.value.filter((item) => {
    return Number(item.project_id) === Number(detailPackage.value.project_id)
      && item.classroom_name === detailPackage.value.classroom_name;
  });
});
const detailScopeTabs = computed(() => {
  if (!detailIsClassroomPackage.value) return [];
  return classroomDetailScopes.map((scope) => ({
    ...scope,
    package: findDetailScopePackage(scope.key),
  }));
});
const detailProductRows = computed(() => {
  const packageItems = detailPackage.value?.items || [];
  const productsBySource = new Map(drawerProducts.value.map((product) => [String(product.product_archive_id), product]));
  const packageItemsBySource = packageItems.reduce((map, item) => {
    const key = String(item.product_archive_id);
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(item);
    return map;
  }, new Map());

  const rows = drawerProducts.value.map((product, index) => {
    const matchedItems = packageItemsBySource.get(String(product.product_archive_id)) || [];
    const quantity = matchedItems.length
      ? matchedItems.reduce((sum, item) => sum + Number(item.quantity || 0), 0)
      : packageProductQuantities[`product:${product.id}`] || 0;
    return {
      product,
      packageItems: matchedItems,
      selected: matchedItems.length > 0,
      quantity: Math.max(Math.floor(Number(quantity || 0)), matchedItems.length ? 1 : 0),
      unit_price: matchedItems[0]?.unit_price ?? productOrderUnitPrice(product),
      sourceIndex: index,
    };
  });

  packageItems.forEach((item) => {
    if (productsBySource.has(String(item.product_archive_id))) return;
    rows.push({
      product: null,
      packageItems: [item],
      selected: true,
      quantity: Math.max(Math.floor(Number(item.quantity || 1)), 1),
      unit_price: item.unit_price || '0.00',
      sourceIndex: drawerProducts.value.length,
      fallbackItem: item,
    });
  });

  const orderMap = new Map(detailProductOrder.value.map((key, index) => [key, index]));
  return sortCableProducts(rows.filter((row) => row.selected && !detailDeletedRowKeys[detailRowKey(row)]), detailRowProduct).sort((a, b) => {
    const aOrder = orderMap.has(detailRowKey(a)) ? orderMap.get(detailRowKey(a)) : 100000 + a.sourceIndex;
    const bOrder = orderMap.has(detailRowKey(b)) ? orderMap.get(detailRowKey(b)) : 100000 + b.sourceIndex;
    return aOrder - bOrder;
  });
});
const detailSelectedRows = computed(() => detailProductRows.value);
const addCableProductRows = computed(() => {
  const currentRows = addCableCurrentProductRows();
  const currentSources = new Set(currentRows.map((row) => String(row.product.product_archive_id || '')));
  const currentKeys = new Set(currentRows.map((row) => addCableProductKey(row.product)));
  const otherRows = addCableProducts.value
    .filter((product) => {
      const sourceId = String(product.product_archive_id || '');
      return !currentKeys.has(addCableProductKey(product)) && (!sourceId || !currentSources.has(sourceId));
    })
    .map((product, index) => ({ product, current: false, index }));
  return sortCableProducts([...currentRows, ...otherRows], (row) => row.product);
});
const detailGroupedRows = computed(() => {
  const primaryGroups = [];
  const primaryMap = new Map();
  detailProductRows.value.forEach((row) => {
    const categoryA = detailRowCategoryA(row);
    const categoryB = detailRowCategoryB(row);
    if (!primaryMap.has(categoryA)) {
      const group = { categoryA, rows: [], secondaryGroups: [], secondaryMap: new Map() };
      primaryMap.set(categoryA, group);
      primaryGroups.push(group);
    }
    const primaryGroup = primaryMap.get(categoryA);
    primaryGroup.rows.push(row);
    if (!primaryGroup.secondaryMap.has(categoryB)) {
      const secondaryGroup = { categoryB, rows: [] };
      primaryGroup.secondaryMap.set(categoryB, secondaryGroup);
      primaryGroup.secondaryGroups.push(secondaryGroup);
    }
    primaryGroup.secondaryMap.get(categoryB).rows.push(row);
  });

  const output = [];
  primaryGroups.forEach((primaryGroup) => {
    let primaryRowIndex = 0;
    primaryGroup.secondaryGroups.forEach((secondaryGroup) => {
      secondaryGroup.rows.forEach((row, secondaryRowIndex) => {
        output.push({
          row,
          categoryA: primaryGroup.categoryA,
          categoryB: secondaryGroup.categoryB,
          categoryARowspan: primaryRowIndex === 0 ? primaryGroup.rows.length : 0,
          categoryBRowspan: secondaryRowIndex === 0 ? secondaryGroup.rows.length : 0,
          index: output.length + 1,
        });
        primaryRowIndex += 1;
      });
    });
  });
  return output;
});
const detailPackageAmount = computed(() => {
  const total = detailSelectedRows.value.reduce((sum, row) => {
    return sum + Number(row.unit_price || 0) * detailRowQuantity(row);
  }, 0);
  return total.toFixed(2);
});
const detailPackageKindCount = computed(() => detailSelectedRows.value.length);
const detailPackageCableCount = computed(() => detailSelectedRows.value.reduce((sum, row) => sum + detailRowQuantity(row), 0));
const detailClassroomSummary = computed(() => {
  if (!detailPackage.value) return { amount: '0.00', kindCount: 0, cableCount: 0 };
  const relatedPackages = detailIsClassroomPackage.value
    ? detailClassroomPackages.value
    : [detailPackage.value];

  const summary = relatedPackages.reduce((total, packageItem) => {
    if (Number(packageItem.id) === Number(detailPackage.value.id)) {
      detailSelectedRows.value.forEach((row) => {
        const quantity = detailRowQuantity(row);
        total.amount += Number(row.unit_price || 0) * quantity;
        total.kindCount += 1;
        total.cableCount += quantity;
      });
      return total;
    }
    (packageItem.items || []).forEach((item) => {
      const quantity = Number(item.quantity || 0);
      total.amount += Number(item.unit_price || 0) * quantity;
      total.kindCount += 1;
      total.cableCount += quantity;
    });
    return total;
  }, { amount: 0, kindCount: 0, cableCount: 0 });

  return {
    amount: summary.amount.toFixed(2),
    kindCount: summary.kindCount,
    cableCount: summary.cableCount,
  };
});
const detailHasUnsavedChanges = computed(() => {
  if (!detailPackage.value) return false;
  if (packageDetailForm.name.trim() !== detailPackage.value.name) return true;
  if (packageDetailForm.note.trim() !== (detailPackage.value.note || '')) return true;
  if (Object.values(detailDeletedItemIds).some(Boolean)) return true;
  return detailSelectedRows.value.some((row) => {
    if (!row.selected || !row.packageItems.length) return false;
    return detailRowQuantity(row) !== Math.max(Math.floor(Number(row.quantity || 1)), 1);
  });
});
const packageEditHasChanges = computed(() => draftChanged(formSnapshot(packageEditForm), packageEditInitial.value));
const projectCreateHasChanges = computed(() => draftChanged(formSnapshot(projectForm), projectFormInitial.value));
const classroomCreateHasChanges = computed(() => draftChanged(formSnapshot(classroomCreateForm), classroomCreateInitial.value));
const customCreateHasChanges = computed(() => draftChanged(customFormSnapshotValue(), customFormInitial.value));
const customBindHasChanges = computed(() => draftChanged(formSnapshot(customBindForm, ['productId']), customBindInitial.value));
const externalAccountCreateHasChanges = computed(() => draftChanged(formSnapshot(externalAccountForm), externalAccountFormInitial.value));
const externalAccountEditHasChanges = computed(() => draftChanged(formSnapshot(externalAccountEditForm), externalAccountEditInitial.value));
const shippingAddressCreateHasChanges = computed(() => draftChanged(formSnapshot(shippingAddressForm), shippingAddressFormInitial.value));
const shippingAddressEditHasChanges = computed(() => draftChanged(formSnapshot(shippingAddressEditForm), shippingAddressEditInitial.value));
const signingInfoCreateHasChanges = computed(() => draftChanged(formSnapshot(signingInfoForm), signingInfoFormInitial.value));
const signingInfoEditHasChanges = computed(() => draftChanged(formSnapshot(signingInfoEditForm), signingInfoEditInitial.value));
const productCartModalHasChanges = computed(() => {
  if (!productCartOpen.value || !productCartTarget.value) return false;
  return Math.max(Math.floor(Number(productCartDraftQuantity.value || 1)), 1) !== Math.max(productCartQuantity(productCartTarget.value) || 1, 1);
});
const addCableHasChanges = computed(() => {
  if (!addCableModalOpen.value) return false;
  return addCableProductRows.value.some(({ product }) => {
    const currentQuantity = Math.floor(Number(addCableQuantities[product.id] || 0));
    return currentQuantity !== addCablePackageQuantity(product);
  });
});
const orderCreateHasChanges = computed(() => {
  if (!orderCreateOpen.value) return false;
  return draftChanged({
    tab: orderCreateTab.value,
    form: formSnapshot(orderForm),
    selected: formSnapshot(selectedOrderPackageIds),
    quantities: formSnapshot(orderPackageQuantities),
  }, orderSelectionInitial.value);
});
const orderAddressPickerHasChanges = computed(() => (
  orderAddressPickerOpen.value && String(pendingOrderShippingAddressId.value || '') !== String(orderForm.shipping_address_id || '')
));
const orderSigningInfoPickerHasChanges = computed(() => (
  orderSigningInfoPickerOpen.value && String(pendingOrderSigningInfoId.value || '') !== String(orderForm.signing_info_id || '')
));
function packageAmount(packageItem) {
  const total = packageItem?.items?.reduce((sum, item) => {
    return sum + Number(item.unit_price || 0) * Number(item.quantity || 0);
  }, 0) || 0;
  return total.toFixed(2);
}

function productLineAmount(product, quantity) {
  return (productOrderUnitPrice(product) * Math.max(Math.floor(Number(quantity || 0)), 0)).toFixed(2);
}

function productCartLineAmount(item) {
  return productLineAmount(item?.product, item?.quantity);
}

function productUnit(product) {
  return product?.quantity_unit || product?.source_unit || '-';
}

function productCartItem(product) {
  return productCartItems.value.find((item) => Number(item.product?.id) === Number(product?.id));
}

function hydrateProductCart(items = []) {
  productCartItems.value = items
    .filter((item) => item?.product)
    .map((item) => ({
      id: item.id,
      product: item.product,
      quantity: Math.max(Math.floor(Number(item.quantity || 1)), 1),
    }));
}

async function loadProductCart() {
  const data = await request('/product-cart/');
  hydrateProductCart(data.items || []);
}

function productCartPayload() {
  return productCartItems.value.map((item) => ({
    id: item.id,
    product_id: item.product.id,
    quantity: Math.max(Math.floor(Number(item.quantity || 1)), 1),
  }));
}

async function saveProductCartNow() {
  const payloadItems = productCartPayload();
  const savedIds = new Set();
  for (const item of payloadItems) {
    const response = await request('/product-cart/', {
      method: 'POST',
      body: JSON.stringify({ product_id: item.product_id, quantity: item.quantity }),
    });
    if (response.item?.id) {
      savedIds.add(Number(response.item.id));
      const cartItem = productCartItems.value.find((row) => Number(row.product?.id) === Number(item.product_id));
      if (cartItem) cartItem.id = response.item.id;
    }
  }
  const existingIds = payloadItems.map((item) => Number(item.id)).filter(Boolean);
  await Promise.all(existingIds
    .filter((id) => !savedIds.has(id))
    .map((id) => request(`/product-cart/${id}/`, { method: 'DELETE' }).catch(() => null)));
}

function scheduleProductCartSave() {
  window.clearTimeout(productCartSaveTimer);
  productCartSaveTimer = window.setTimeout(() => {
    saveProductCartNow().catch((err) => setMessage('error', err.message || '购物车保存失败'));
  }, 350);
}

async function clearSavedProductCart() {
  await request('/product-cart/', { method: 'DELETE' });
  productCartItems.value = [];
}

function productCartQuantity(product) {
  return Number(productCartItem(product)?.quantity || 0);
}

function openProductCartModal(product) {
  productCartTarget.value = product;
  productCartDraftQuantity.value = Math.max(productCartQuantity(product) || 1, 1);
  productCartOpen.value = true;
}

function closeProductCartModal() {
  closeWithUnsavedGuard(productCartModalHasChanges.value, () => {
    forceCloseProductCartModal();
  });
}

function forceCloseProductCartModal() {
  productCartOpen.value = false;
  productCartTarget.value = null;
  productCartDraftQuantity.value = 1;
}

function openProductCartDetail() {
  if (!productCartItems.value.length) return setMessage('error', '购物车暂无线材');
  productCartDetailOpen.value = true;
}

function closeProductCartDetail() {
  productCartDetailOpen.value = false;
}

async function confirmAddProductToCart() {
  const product = productCartTarget.value;
  if (!product) return setMessage('error', '请选择线材');
  const quantity = Math.max(Math.floor(Number(productCartDraftQuantity.value || 1)), 1);
  const existing = productCartItem(product);
  if (existing) {
    existing.quantity = quantity;
  } else {
    productCartItems.value.push({ product, quantity });
  }
  try {
    await saveProductCartNow();
  } catch (err) {
    return setMessage('error', err.message || '购物车保存失败');
  }
  forceCloseProductCartModal();
  setMessage('notice', '已加入购物车');
}

function updateProductCartQuantity(item, value) {
  const quantity = Math.max(Math.floor(Number(value || 1)), 1);
  item.quantity = quantity;
  const cartItem = productCartItem(item.product);
  if (cartItem) cartItem.quantity = quantity;
  orderPackageQuantities[`cart-product:${item.product.id}`] = quantity;
  scheduleProductCartSave();
}

async function removeProductCartItem(item) {
  productCartItems.value = productCartItems.value.filter((row) => Number(row.product?.id) !== Number(item.product?.id));
  delete selectedOrderPackageIds[`cart-product:${item.product.id}`];
  delete orderPackageQuantities[`cart-product:${item.product.id}`];
  try {
    if (item.id) {
      await request(`/product-cart/${item.id}/`, { method: 'DELETE' });
    } else {
      scheduleProductCartSave();
    }
  } catch (err) {
    setMessage('error', err.message || '购物车移除失败');
  }
}

function selectAllProductCartRows() {
  productCartItems.value.forEach((item) => {
    const key = `cart-product:${item.product.id}`;
    selectedOrderPackageIds[key] = true;
    orderPackageQuantities[key] = Math.max(Math.floor(Number(item.quantity || 1)), 1);
  });
}

async function openProductCartOrder() {
  if (!productCartItems.value.length) return setMessage('error', '购物车暂无线材');
  clearOrderSelection();
  selectAllProductCartRows();
  await openOrderCreate('cart-products');
}

function setOrderProjectViewMode(mode) {
  if (orderProjectViewMode.value === mode) return;
  orderProjectViewMode.value = mode;
  orderCreateSearch.value = '';
}

async function openProjectOrder(item) {
  const row = orderableProjectRows.value.find((projectItem) => Number(projectItem.id) === Number(item?.id));
  if (!row) return setMessage('error', '该项目暂无线材，不能下单');
  clearOrderSelection();
  selectedOrderPackageIds[row.order_key] = true;
  orderPackageQuantities[row.order_key] = Math.max(Math.floor(Number(row.order_quantity_default || 1)), 1);
  await openOrderCreate('project-classrooms');
}

function productParameterText(product) {
  return product?.solution_params || product?.plan_para || '';
}

function parameterTooltipLines(text) {
  return splitParameterLines(text);
}

function updateParameterTooltipPosition(event) {
  const gap = 14;
  const margin = 10;
  const rect = parameterTooltipRef.value?.getBoundingClientRect();
  const tooltipWidth = rect?.width || Math.min(460, window.innerWidth - margin * 2);
  const tooltipHeight = rect?.height || Math.min(240, window.innerHeight - margin * 2);
  let x = event.clientX + gap;
  let y = event.clientY + gap;
  if (x + tooltipWidth > window.innerWidth - margin) {
    x = Math.max(margin, event.clientX - tooltipWidth - gap);
  }
  if (y + tooltipHeight > window.innerHeight - margin) {
    y = Math.max(margin, event.clientY - tooltipHeight - gap);
  }
  parameterTooltip.x = x;
  parameterTooltip.y = y;
}

function showParameterTooltip(product, event) {
  const text = productParameterText(product);
  if (!text) return;
  parameterTooltip.text = text;
  parameterTooltip.visible = true;
  updateParameterTooltipPosition(event);
  nextTick(() => updateParameterTooltipPosition(event));
}

function moveParameterTooltip(event) {
  if (!parameterTooltip.visible) return;
  updateParameterTooltipPosition(event);
}

function hideParameterTooltip() {
  parameterTooltip.visible = false;
  parameterTooltip.text = '';
}

function handleKeydown(event) {
  if (event.key !== 'Escape') return;
  if (unsavedConfirm.open) {
    closeUnsavedConfirm();
    return;
  }
  if (signingInfoEditing.value) return cancelSigningInfoEdit();
  if (signingInfoCreating.value) return closeSigningInfoCreateModal();
  if (shippingAddressEditing.value) return cancelShippingAddressEdit();
  if (shippingAddressCreating.value) return closeShippingAddressCreateModal();
  if (externalAccountCreating.value) return closeExternalAccountCreateModal();
  if (customBoundDetailOpen.value) return closeCustomBoundDetail();
  if (customBinding.value) return closeCustomBindModal();
  if (customCreating.value) return closeCustomCreateModal();
  if (deletingClassroom.value) return cancelClassroomDelete();
  if (classroomCreating.value) return closeClassroomCreateModal();
  if (projectCreating.value) return closeProjectCreateModal();
  if (addCableModalOpen.value) return closeAddCableModal();
  if (orderSigningInfoPickerOpen.value) {
    closeOrderSigningInfoDrawer();
    return;
  }
  if (orderAddressPickerOpen.value) {
    closeOrderAddressDrawer();
    return;
  }
  if (orderCreateOpen.value) return closeOrderCreate();
  if (productCartOpen.value) {
    closeProductCartModal();
    return;
  }
  if (productCartDetailOpen.value) {
    closeProductCartDetail();
    return;
  }
  if (imagePreview.open) closeImagePreview();
}

function projectPackages(project) {
  if (!project) return [];
  return activePackages.value.filter((item) => Number(item.project_id) === Number(project.id));
}

function projectOrderCableRows(item) {
  const rows = new Map();
  (item?.order_packages || []).forEach((packageItem) => {
    const packageQuantity = Math.max(Math.floor(Number(packageItem.quantity || 1)), 1);
    (packageItem.items || []).forEach((detail) => {
      const key = String(detail.product_archive_id || detail.id);
      if (!rows.has(key)) {
        rows.set(key, {
          key,
          product_abbr: detail.product_abbr,
          product_label: detail.product_label,
          product_model: detail.product_model,
          category_a: detail.category_a,
          category_b: detail.category_b,
          unit_price: detail.unit_price || '0.00',
          quantity: 0,
          amount: 0,
        });
      }
      const row = rows.get(key);
      const quantity = Number(detail.quantity || 0) * packageQuantity;
      row.quantity += quantity;
      row.amount += Number(detail.unit_price || 0) * quantity;
    });
  });
  return sortCableProducts(Array.from(rows.values()), (row) => row).map((row) => ({
    ...row,
    amount_text: row.amount.toFixed(2),
  }));
}

function projectAmount(project) {
  return projectPackages(project)
    .reduce((sum, item) => sum + Number(packageAmount(item)) * Number(item.quantity || 1), 0)
    .toFixed(2);
}

function projectCableCount(project) {
  return projectPackages(project).reduce((sum, item) => sum + Number(item.cable_count || 0), 0);
}

function projectClassroomCount(project) {
  return new Set(projectPackages(project).map((item) => item.classroom_name || item.name)).size;
}

function classroomPackageAmount(item) {
  return item ? packageAmount(item) : '0.00';
}

function classroomPackages(classroom) {
  return [classroom?.indoor, classroom?.outdoor].filter(Boolean);
}

function classroomScopeRows(classroom) {
  return [
    { key: '教室内', label: '讲桌内', package: classroom?.indoor || null },
    { key: '教室外', label: '讲桌外', package: classroom?.outdoor || null },
  ];
}

function inferOrderPackageClassroomScope(orderPackage) {
  const text = `${orderPackage?.classroom_scope || ''} ${orderPackage?.package_name || ''} ${orderPackage?.package_note || ''}`;
  if (text.includes('教室外') || text.includes('讲桌外')) return '教室外';
  if (text.includes('教室内') || text.includes('讲桌内')) return '教室内';
  return '';
}

function inferOrderPackageClassroomName(orderPackage) {
  const scope = inferOrderPackageClassroomScope(orderPackage);
  const name = String(orderPackage?.package_name || '').trim();
  if (!scope || !name) return '';
  const scopeText = scope === '教室外' ? '(教室外|讲桌外)' : '(教室内|讲桌内)';
  return name
    .replace(new RegExp(`[-_\\s]*${scopeText}.*$`), '')
    .replace(new RegExp(`${scopeText}`), '')
    .replace(/[-_\\s]+$/, '')
    .trim() || name;
}

function orderPackageLineAmount(orderPackage) {
  return (orderPackage?.items || []).reduce((sum, item) => sum + Number(item.line_total || 0), 0);
}

function orderDetailClassroomRoomCount(classroom) {
  const quantities = classroomPackages(classroom)
    .map((item) => Math.floor(Number(item.package_quantity || item.quantity || 1)))
    .filter((value) => value > 0);
  return quantities.length ? Math.max(...quantities) : 1;
}

function orderDetailClassroomSingleAmount(classroom) {
  return classroomPackages(classroom).reduce((sum, item) => {
    const roomCount = Math.max(Math.floor(Number(item.package_quantity || item.quantity || 1)), 1);
    return sum + (orderPackageLineAmount(item) / roomCount);
  }, 0).toFixed(2);
}

function orderDetailClassroomTotalAmount(classroom) {
  return classroomPackages(classroom)
    .reduce((sum, item) => sum + orderPackageLineAmount(item), 0)
    .toFixed(2);
}

function orderDetailScopeCableCount(scopeRow) {
  const item = scopeRow?.package;
  if (!item) return 0;
  const quantity = Math.max(Math.floor(Number(item.package_quantity || item.quantity || 1)), 1);
  return Number(item.cable_count || 0) * quantity;
}

function resetOrderDetailView() {
  orderDetailTab.value = 'info';
  orderDetailProductView.value = selectedOrderHasProjectView.value ? 'classrooms' : 'cables';
}

function classroomTotalAmount(classroom) {
  return classroomPackages(classroom)
    .reduce((sum, item) => sum + Number(classroomPackageAmount(item)), 0)
    .toFixed(2);
}

function classroomRoomCount(classroom) {
  const quantities = classroomPackages(classroom)
    .map((item) => Math.floor(Number(item.quantity || 1)))
    .filter((value) => value > 0);
  return quantities.length ? Math.max(...quantities) : 1;
}

function classroomGrandAmount(classroom) {
  return (Number(classroomTotalAmount(classroom)) * classroomRoomCount(classroom)).toFixed(2);
}

function classroomTotalKindCount(classroom) {
  return classroomPackages(classroom).reduce((sum, item) => sum + Number(item.item_count || 0), 0);
}

function classroomTotalCableCount(classroom) {
  return classroomPackages(classroom).reduce((sum, item) => sum + Number(item.cable_count || 0), 0);
}

function classroomScopeKindCount(scopeRow) {
  return Number(scopeRow?.package?.item_count || 0);
}

function classroomScopeCableCount(scopeRow) {
  return Number(scopeRow?.package?.cable_count || 0);
}

function classroomPrimaryPackage(classroom) {
  return classroom?.indoor || classroom?.outdoor || classroom?.packages?.[0] || null;
}

function classroomIndoorPackage(classroom) {
  return classroom?.indoor || classroomPrimaryPackage(classroom);
}

function findDetailScopePackage(scope) {
  if (!detailPackage.value?.project_id || !detailPackage.value?.classroom_name) return null;
  return activePackages.value.find((item) => {
    return Number(item.project_id) === Number(detailPackage.value.project_id)
      && item.classroom_name === detailPackage.value.classroom_name
      && item.classroom_scope === scope;
  }) || null;
}

function detailRowProduct(row) {
  return row.product || row.fallbackItem || {};
}

function detailRowCategoryA(row) {
  const product = detailRowProduct(row);
  return product.category_a || '-';
}

function detailRowCategoryB(row) {
  const product = detailRowProduct(row);
  return product.category_b || '-';
}

function detailRowKey(row) {
  const product = detailRowProduct(row);
  return row.product ? `product:${product.id}` : `item:${row.fallbackItem.id}`;
}

function detailRowQuantity(row) {
  const key = detailRowKey(row);
  const fallback = row.selected ? row.quantity || 1 : row.quantity || 0;
  const quantity = Math.floor(Number(packageProductQuantities[key] ?? fallback));
  if (row.selected) return Math.max(quantity, 1);
  return quantity > 0 ? quantity : 0;
}

function detailRowQuantityDisplay(row) {
  const quantity = detailRowQuantity(row);
  return quantity > 0 ? quantity : '';
}

function setDetailRowQuantity(row, value) {
  const quantity = Math.floor(Number(value));
  packageProductQuantities[detailRowKey(row)] = quantity >= 1 ? quantity : 0;
}

function detailRowLineAmount(row) {
  return (Number(row.unit_price || 0) * detailRowQuantity(row)).toFixed(2);
}

function buildDetailProductOrder(packageItem, organize = false) {
  const selectedSources = new Set((packageItem?.items || []).map((item) => String(item.product_archive_id)));
  const productSources = new Set(drawerProducts.value.map((product) => String(product.product_archive_id)));
  const entries = drawerProducts.value.map((product, index) => ({
    key: `product:${product.id}`,
    selected: selectedSources.has(String(product.product_archive_id)),
    product,
    index,
  }));

  (packageItem?.items || []).forEach((item, index) => {
    if (productSources.has(String(item.product_archive_id))) return;
    entries.push({
      key: `item:${item.id}`,
      selected: true,
      product: item,
      index: drawerProducts.value.length + index,
    });
  });

  if (organize) {
    entries.sort((a, b) => {
      if (a.selected !== b.selected) return a.selected ? -1 : 1;
      return compareCableProducts(a.product, b.product) || a.index - b.index;
    });
  }
  detailProductOrder.value = entries.map((entry) => entry.key);
}

function setDetailQuantityInputRef(key, el) {
  if (el) detailQuantityInputs.set(key, el);
  else detailQuantityInputs.delete(key);
}

async function focusDetailQuantityInput(row) {
  const key = typeof row === 'string' ? row : detailRowKey(row);
  await nextTick();
  const input = detailQuantityInputs.get(key);
  if (!input) return;
  input.focus();
  input.select();
}

function selectPackage(item) {
  selectedPackageId.value = item.id;
}

function isSelectedPackage(item) {
  return Number(selectedPackageId.value) === Number(item.id);
}

function handlePackageTableRowClick(item, event) {
  if (event.target.closest('input, button, a, select, textarea')) return;
  if (editingPackageId.value === item.id) return;
  openPackageDetail(item);
}

function openPackageDetail(item) {
  if (!item) return;
  if (detailPackage.value && Number(detailPackage.value.id) !== Number(item.id) && detailHasUnsavedChanges.value) {
    requestDiscardChanges(() => {
      discardPackageDetailChanges();
      openPackageDetail(item);
    });
    return;
  }
  selectPackage(item);
  packageDetailId.value = item.id;
  hydratePackageDetail(item);
  editingPackageId.value = null;
  deletingPackageId.value = null;
  deletingDetailRowKey.value = '';
  clearDetailDeletedDraft();
}

function hydratePackageDetail(item) {
  if (!item) return;
  buildDetailProductOrder(item, true);
  packageDetailForm.name = item.name;
  packageDetailForm.note = item.note || '';
  drawerProducts.value.forEach((product) => {
    const matchedItems = (item.items || []).filter((detail) => String(detail.product_archive_id) === String(product.product_archive_id));
    packageProductQuantities[`product:${product.id}`] = matchedItems.length
      ? matchedItems.reduce((sum, detail) => sum + Number(detail.quantity || 0), 0)
      : 0;
  });
}

async function switchDetailScope(scope) {
  const targetPackage = findDetailScopePackage(scope);
  if (!targetPackage || Number(targetPackage.id) === Number(packageDetailId.value)) return;
  if (detailHasUnsavedChanges.value) {
    const saved = await savePackageDetailDraft();
    if (!saved) return;
  }
  packageDetailId.value = targetPackage.id;
  selectedPackageId.value = targetPackage.id;
  addCableModalOpen.value = false;
  deletingDetailRowKey.value = '';
  clearDetailDeletedDraft();
  hydratePackageDetail(targetPackage);
}

function clearDetailDeletedDraft() {
  Object.keys(detailDeletedRowKeys).forEach((key) => {
    delete detailDeletedRowKeys[key];
  });
  Object.keys(detailDeletedItemIds).forEach((key) => {
    delete detailDeletedItemIds[key];
  });
}

function discardPackageDetailChanges() {
  packageDetailId.value = null;
  addCableModalOpen.value = false;
  deletingDetailRowKey.value = '';
  deletingClassroom.value = null;
  clearDetailDeletedDraft();
}

function closePackageDetail() {
  closeWithUnsavedGuard(detailHasUnsavedChanges.value, () => {
    discardPackageDetailChanges();
  });
}

async function openAddCableModal() {
  if (!detailPackage.value) return;
  selectedPackageId.value = detailPackage.value.id;
  addCableFilters.category_a = filters.category_a || addCableFilters.category_a || '';
  addCableFilters.category_b = filters.category_b || addCableFilters.category_b || '';
  clearAddCableDraft();
  seedAddCableDraftFromPackage();
  addCableModalOpen.value = true;
  await run(async () => {
    await loadAddCableProducts(false);
  });
}

function closeAddCableModal() {
  closeWithUnsavedGuard(addCableHasChanges.value, () => {
    forceCloseAddCableModal();
  });
}

function forceCloseAddCableModal() {
  addCableModalOpen.value = false;
  window.clearTimeout(addCableSearchTimer);
}

function clearAddCableDraft() {
  Object.keys(addCableQuantities).forEach((key) => {
    delete addCableQuantities[key];
  });
  Object.keys(addCableSelectedProducts).forEach((key) => {
    delete addCableSelectedProducts[key];
  });
}

function addCablePackageItemsForProduct(product) {
  if (!product) return [];
  return (detailPackage.value?.items || []).filter((item) => String(item.product_archive_id) === String(product.product_archive_id));
}

function addCablePackageQuantity(product) {
  return addCablePackageItemsForProduct(product).reduce((sum, item) => sum + Number(item.quantity || 0), 0);
}

function addCableProductKey(product) {
  return `product:${product.id}`;
}

function addCableCurrentProductRows() {
  const rows = [];
  const seenSources = new Set();
  (detailPackage.value?.items || []).forEach((item, index) => {
    const sourceId = String(item.product_archive_id || '');
    if (!sourceId || seenSources.has(sourceId)) return;
    const product = drawerProducts.value.find((candidate) => String(candidate.product_archive_id) === sourceId);
    if (!product) return;
    seenSources.add(sourceId);
    rows.push({ product, current: true, index: -100000 + index });
  });
  return rows;
}

function seedAddCableDraftFromPackage() {
  (detailPackage.value?.items || []).forEach((item) => {
    const product = drawerProducts.value.find((candidate) => String(candidate.product_archive_id) === String(item.product_archive_id));
    if (!product) return;
    const key = String(product.id);
    addCableQuantities[key] = (Math.floor(Number(addCableQuantities[key] || 0)) || 0) + Number(item.quantity || 0);
    addCableSelectedProducts[key] = product;
  });
}

async function savePackageDetailDraft() {
  if (!detailPackage.value || !detailHasUnsavedChanges.value) return;
  const name = packageDetailForm.name.trim();
  if (!name) {
    packageDetailForm.name = detailPackage.value.name;
    return;
  }
  const note = packageDetailForm.note.trim();
  const rows = [...detailSelectedRows.value];

  return run(async () => {
    const tasks = [];
    if (name !== detailPackage.value.name || note !== (detailPackage.value.note || '')) {
      tasks.push(request(`/packages/${detailPackage.value.id}/`, {
        method: 'PATCH',
        body: JSON.stringify({ name, note }),
      }));
    }
    rows.forEach((row) => {
      if (!row.packageItems.length) return;
      const normalizedQuantity = detailRowQuantity(row);
      const originalQuantity = Math.max(Math.floor(Number(row.quantity || 1)), 1);
      if (normalizedQuantity === originalQuantity) return;
      const [primaryItem, ...duplicateItems] = row.packageItems;
      tasks.push(request(`/package-items/${primaryItem.id}/`, {
        method: 'PATCH',
        body: JSON.stringify({ quantity: normalizedQuantity }),
      }));
      duplicateItems.forEach((item) => {
        tasks.push(request(`/package-items/${item.id}/`, { method: 'DELETE' }));
      });
    });
    Object.entries(detailDeletedItemIds).forEach(([id, deleted]) => {
      if (deleted) tasks.push(request(`/package-items/${id}/`, { method: 'DELETE' }));
    });
    await Promise.all(tasks);
    await loadPackages();
    packageDetailForm.name = name;
    packageDetailForm.note = note;
    clearDetailDeletedDraft();
    deletingDetailRowKey.value = '';
    return true;
  }, '已保存线材清单');
}

async function togglePackageDetailProduct(row, checked) {
  if (!detailPackage.value) return;
  if (checked && !row.selected && row.product) {
    const key = detailRowKey(row);
    packageProductQuantities[key] = 1;
    await run(async () => {
      await request(`/packages/${detailPackage.value.id}/items/`, {
        method: 'POST',
        body: JSON.stringify({ product_id: row.product.id, quantity: 1 }),
      });
      await loadPackages();
    });
    await focusDetailQuantityInput(key);
    return;
  }
  if (checked && row.selected) {
    if (detailRowQuantity(row) < 1) packageProductQuantities[detailRowKey(row)] = 1;
    await focusDetailQuantityInput(row);
    return;
  }
  if (!checked && row.selected) {
    const key = detailRowKey(row);
    await run(async () => {
      await Promise.all(row.packageItems.map((item) => request(`/package-items/${item.id}/`, { method: 'DELETE' })));
      await loadPackages();
    });
    packageProductQuantities[key] = 0;
  }
}

async function handleDetailProductRowClick(row, event) {
  if (event.target.closest('input, button, a, select, textarea')) return;
  if (!row.selected) {
    await togglePackageDetailProduct(row, true);
    return;
  }
  await focusDetailQuantityInput(row);
}

async function handleDetailQuantityFocus(row) {
  if (!row.selected) await togglePackageDetailProduct(row, true);
}

function productImageUrl(product) {
  const thumb = String(product?.product_thumb || '').trim();
  if (!thumb) return '';
  if (/^https?:\/\//i.test(thumb)) return thumb;
  return new URL(thumb, API_BASE_URL).toString();
}

function productFullImageUrl(product) {
  if (isExternalMode.value) {
    return product?.product_image_preview_external
      || product?.product_image_preview
      || (product?.id ? `/api/external-cable-mall/products/${product.id}/image/?variant=preview` : '')
      || product?.product_image
      || product?.product_images?.[0]
      || '';
  }
  return product?.product_image_preview || product?.product_image || product?.product_images?.[0] || '';
}

function backendAssetUrl(path) {
  const raw = String(path || '').trim();
  if (!raw) return '';
  return new URL(raw, API_BASE_URL).toString();
}

async function openImagePreview(product) {
  const src = productFullImageUrl(product);
  if (!src) return;
  const requestId = imagePreview.requestId + 1;
  imagePreview.requestId = requestId;
  if (imagePreview.objectUrl) URL.revokeObjectURL(imagePreview.objectUrl);
  imagePreview.objectUrl = '';
  imagePreview.src = '';
  imagePreview.title = product.abbr || product.label || '产品图片';
  imagePreview.open = true;
  imagePreview.loading = true;
  if (!isExternalMode.value) {
    imagePreview.src = new URL(src, API_BASE_URL).toString();
    imagePreview.loading = false;
    return;
  }
  try {
    const response = await fetch(new URL(src, API_BASE_URL).toString(), {
      method: 'GET',
      headers: authHeadersForFileRequest(),
      credentials: 'same-origin',
    });
    if (!response.ok) throw new Error('图片暂时不可用');
    const objectUrl = URL.createObjectURL(await response.blob());
    if (imagePreview.requestId !== requestId || !imagePreview.open) {
      URL.revokeObjectURL(objectUrl);
      return;
    }
    imagePreview.objectUrl = objectUrl;
    imagePreview.src = objectUrl;
  } catch {
    if (imagePreview.requestId === requestId) imagePreview.src = '';
  } finally {
    if (imagePreview.requestId === requestId) imagePreview.loading = false;
  }
}

function closeImagePreview() {
  imagePreview.requestId += 1;
  if (imagePreview.objectUrl) URL.revokeObjectURL(imagePreview.objectUrl);
  imagePreview.objectUrl = '';
  imagePreview.open = false;
  imagePreview.src = '';
  imagePreview.title = '';
  imagePreview.loading = false;
}

const categoryChipPalette = [
  { color: '#1d4ed8', borderColor: '#bfdbfe', background: '#eff6ff' },
  { color: '#047857', borderColor: '#bbf7d0', background: '#f0fdf4' },
  { color: '#b45309', borderColor: '#fed7aa', background: '#fff7ed' },
  { color: '#7e22ce', borderColor: '#e9d5ff', background: '#faf5ff' },
  { color: '#be123c', borderColor: '#fecdd3', background: '#fff1f2' },
  { color: '#0f766e', borderColor: '#99f6e4', background: '#f0fdfa' },
  { color: '#4338ca', borderColor: '#c7d2fe', background: '#eef2ff' },
  { color: '#525252', borderColor: '#d4d4d4', background: '#fafafa' },
];

function categoryChipStyle(value) {
  const text = String(value || '');
  const index = [...text].reduce((sum, char) => sum + char.charCodeAt(0), 0) % categoryChipPalette.length;
  return categoryChipPalette[index];
}

function setMessage(kind, message) {
  window.clearTimeout(messageFadeTimer);
  window.clearTimeout(messageClearTimer);
  messageFadeTimer = null;
  messageClearTimer = null;
  messageLeaving.value = false;
  if (kind === 'error') {
    error.value = message;
    notice.value = '';
  } else {
    notice.value = message;
    error.value = '';
  }
  messageFadeTimer = window.setTimeout(() => {
    messageLeaving.value = true;
    messageClearTimer = window.setTimeout(() => {
      clearGlobalMessages();
    }, 280);
  }, 1000);
}

function authHeadersForFileRequest() {
  if (props.externalMode) {
    const token = String(props.externalSession?.token || '').trim();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }
  return {};
}

const fetchedTextNormalizeSkipKeys = new Set([
  'id',
  'token',
  'password',
  'old_password',
  'new_password',
  'confirm_password',
  'username',
  'product_archive_id',
  'product_id',
  'project_id',
  'external_account_id',
  'owner_user_id',
  'bound_product_id',
  'shipping_address_id',
  'excel_url',
  'pdf_url',
  'product_image',
  'product_images',
  'product_thumb',
  'avatar',
  'avatarUrl',
]);

function shouldSkipFetchedTextNormalize(key, value) {
  const normalizedKey = String(key || '');
  if (
    fetchedTextNormalizeSkipKeys.has(normalizedKey)
    || normalizedKey.endsWith('_id')
    || normalizedKey.endsWith('_url')
    || normalizedKey.includes('image')
    || normalizedKey.includes('thumb')
    || normalizedKey.includes('path')
    || normalizedKey.includes('href')
    || normalizedKey.includes('token')
    || normalizedKey.includes('password')
  ) {
    return true;
  }
  return /^(https?:)?\/\//i.test(value)
    || /^data:/i.test(value)
    || /^blob:/i.test(value)
    || /^\/(api|media|static|files)\//i.test(value);
}

function normalizeFetchedText(value, key = '') {
  if (typeof value === 'string') {
    if (shouldSkipFetchedTextNormalize(key, value)) return value;
    return value.replace(/\(/g, '（').replace(/\)/g, '）');
  }
  if (Array.isArray(value)) {
    return value.map((item) => normalizeFetchedText(item, key));
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([itemKey, itemValue]) => [
      itemKey,
      normalizeFetchedText(itemValue, itemKey),
    ]));
  }
  return value;
}

async function request(path, options = {}) {
  const method = String(options.method || 'GET').toUpperCase();
  const body = options.body ? JSON.parse(options.body) : null;
  if (props.externalMode) {
    const externalPath = `/api/external-cable-mall${path}`;
    const token = String(props.externalSession?.token || '').trim();
    const headers = {};
    if (token) headers.Authorization = `Bearer ${token}`;
    if (method !== 'GET') headers['Content-Type'] = 'application/json';
    const response = await fetch(new URL(externalPath, API_BASE_URL).toString(), {
      method,
      headers,
      body: method === 'GET' ? null : JSON.stringify(body || {}),
    });
    let data = {};
    try {
      data = await response.json();
    } catch {
      data = {};
    }
    if (response.status === 401 || response.status === 403) {
      const message = data?.error || data?.message || '密码错误，请重新登录';
      emit('external-logout', message);
      throw new Error(message);
    }
    if (!response.ok) throw new Error(data?.error || data?.message || '请求失败');
    return normalizeFetchedText(data);
  }
  if (method === 'GET') {
    const [pathname, rawQuery = ''] = path.split('?');
    const params = Object.fromEntries(new URLSearchParams(rawQuery));
    return normalizeFetchedText(await apiGet(`/api${pathname}`, params));
  }
  if (method === 'POST') return normalizeFetchedText(await apiPost(`/api${path}`, body));
  if (method === 'PATCH') return normalizeFetchedText(await apiPatch(`/api${path}`, body));
  if (method === 'PUT') return normalizeFetchedText(await apiPut(`/api${path}`, body));
  if (method === 'DELETE') return normalizeFetchedText(await apiDelete(`/api${path}`));
  throw new Error(`不支持的请求方法：${method}`);
}

async function fileRequest(path, options = {}) {
  const method = String(options.method || 'POST').toUpperCase();
  const basePath = props.externalMode ? `/api/external-cable-mall${path}` : `/api${path}`;
  const response = await fetch(new URL(basePath, API_BASE_URL).toString(), {
    method,
    headers: authHeadersForFileRequest(),
    credentials: props.externalMode ? 'same-origin' : 'include',
    body: options.body || null,
  });
  let data = {};
  try {
    data = await response.json();
  } catch {
    data = {};
  }
  if (props.externalMode && (response.status === 401 || response.status === 403)) {
    const message = data?.error || data?.message || '密码错误，请重新登录';
    emit('external-logout', message);
    throw new Error(message);
  }
  if (!response.ok) throw new Error(data?.error || data?.message || '请求失败');
  return normalizeFetchedText(data);
}

async function run(task, successMessage = '') {
  busy.value = true;
  error.value = '';
  try {
    const result = await task();
    if (successMessage) setMessage('notice', successMessage);
    return result;
  } catch (err) {
    setMessage('error', err.message || String(err));
    return null;
  } finally {
    busy.value = false;
  }
}

async function loadProducts(sync = false) {
  const loadSeq = ++productLoadSeq;
  const pageSize = productPagination.page_size;
  const buildQuery = (page) => {
    const query = new URLSearchParams();
    if (filters.q) query.set('q', filters.q);
    if (filters.category_a) query.set('category_a', filters.category_a);
    if (filters.category_b) query.set('category_b', filters.category_b);
    if (sync) query.set('sync', '1');
    query.set('page', String(page));
    query.set('page_size', String(pageSize));
    return query;
  };
  const firstData = await request(`/products/?${buildQuery(1).toString()}`);
  if (loadSeq !== productLoadSeq) return;
  const total = Number(firstData.total || 0);
  const resolvedPageSize = Number(firstData.page_size || pageSize) || 200;
  const allItems = [...(firstData.items || [])];
  let page = 2;
  while (allItems.length < total && page <= 50) {
    const query = buildQuery(page);
    query.set('page_size', String(resolvedPageSize));
    const pageData = await request(`/products/?${query.toString()}`);
    if (loadSeq !== productLoadSeq) return;
    allItems.push(...(pageData.items || []));
    page += 1;
  }
  productPagination.total = total;
  productPagination.page_size = resolvedPageSize;
  productPagination.page = 1;
  products.value = sortCableProducts(allItems);
  categoriesA.value = firstData.categories_a || [];
  categoriesB.value = firstData.categories_b || firstData.categories || [];
  if (!filters.category_a && categoriesA.value.length) {
    filters.category_a = categoriesA.value[0];
    await loadProducts(false);
    return;
  }
  if (!filters.category_b && categoriesB.value.length) {
    filters.category_b = categoriesB.value[0];
    await loadProducts(false);
    return;
  }
  if (firstData.source_error) setMessage('error', firstData.source_error);
}

async function loadAddCableProducts(sync = false) {
  const buildQuery = (page) => {
    const query = new URLSearchParams();
    if (addCableFilters.q) query.set('q', addCableFilters.q);
    if (addCableFilters.category_a) query.set('category_a', addCableFilters.category_a);
    if (addCableFilters.category_b) query.set('category_b', addCableFilters.category_b);
    if (sync) query.set('sync', '1');
    query.set('page', String(page));
    query.set('page_size', '200');
    return query;
  };
  const firstData = await request(`/products/?${buildQuery(1).toString()}`);
  const total = Number(firstData.total || 0);
  const resolvedPageSize = Number(firstData.page_size || 200) || 200;
  const allItems = [...(firstData.items || [])];
  let page = 2;
  while (allItems.length < total && page <= 50) {
    const query = buildQuery(page);
    query.set('page_size', String(resolvedPageSize));
    const pageData = await request(`/products/?${query.toString()}`);
    allItems.push(...(pageData.items || []));
    page += 1;
  }
  addCableProducts.value = sortCableProducts(allItems);
  addCableCategoriesA.value = firstData.categories_a || [];
  addCableCategoriesB.value = firstData.categories_b || firstData.categories || [];
  if (!addCableFilters.category_a && addCableCategoriesA.value.length) {
    addCableFilters.category_a = addCableCategoriesA.value[0];
    await loadAddCableProducts(false);
    return;
  }
  if (!addCableFilters.category_b && addCableCategoriesB.value.length) {
    addCableFilters.category_b = addCableCategoriesB.value[0];
    await loadAddCableProducts(false);
    return;
  }
  if (firstData.source_error) setMessage('error', firstData.source_error);
}

async function loadDrawerProducts() {
  const allProducts = [];
  let page = 1;
  let total = 0;
  do {
    const data = await request(`/products/?page=${page}&page_size=200`);
    const items = data.items || [];
    total = Number(data.total || items.length);
    allProducts.push(...items);
    page += 1;
  } while (allProducts.length < total && page <= 20);
  drawerProducts.value = sortCableProducts(allProducts);
  drawerProducts.value.forEach((product) => {
    if (packageProductQuantities[`product:${product.id}`] === undefined) packageProductQuantities[`product:${product.id}`] = 0;
  });
}

function selectCategoryA(value) {
  hideParameterTooltip();
  filters.category_a = value;
  filters.category_b = '';
  productPagination.page = 1;
  loadProducts(false);
}

function selectCategoryB(value) {
  hideParameterTooltip();
  filters.category_b = value;
  productPagination.page = 1;
  loadProducts(false);
}

function selectAddCableCategoryA(value) {
  hideParameterTooltip();
  addCableFilters.category_a = value;
  addCableFilters.category_b = '';
  loadAddCableProducts(false);
}

function selectAddCableCategoryB(value) {
  hideParameterTooltip();
  addCableFilters.category_b = value;
  loadAddCableProducts(false);
}

function selectProjectStatsCategoryA(value) {
  projectStatsFilters.category_a = value;
  projectStatsFilters.category_b = '';
}

function selectProjectStatsCategoryB(value) {
  projectStatsFilters.category_b = value;
}

function scheduleProductSearch() {
  window.clearTimeout(productSearchTimer);
  productSearchTimer = window.setTimeout(() => {
    hideParameterTooltip();
    productPagination.page = 1;
    loadProducts(false);
  }, 300);
}

function reloadProductsFromFirstPage(sync = false) {
  hideParameterTooltip();
  productPagination.page = 1;
  return loadProducts(sync);
}

function scheduleAddCableSearch() {
  window.clearTimeout(addCableSearchTimer);
  addCableSearchTimer = window.setTimeout(() => {
    loadAddCableProducts(false);
  }, 300);
}

async function syncProducts() {
  await run(async () => {
    await request('/products/sync/', { method: 'POST' });
    await Promise.all([loadProducts(false), loadDrawerProducts()]);
  }, '线材库已同步');
}

async function loadPackages() {
  const data = await request('/packages/');
  packages.value = data.items || [];
  const selectedExists = activePackages.value.some((item) => Number(item.id) === Number(selectedPackageId.value));
  if (selectedPackageId.value && !selectedExists) selectedPackageId.value = '';
}

async function loadProjects() {
  const data = await request('/projects/');
  projects.value = data.items || [];
  if (selectedProjectId.value) {
    const stillExists = activeProjects.value.some((item) => Number(item.id) === Number(selectedProjectId.value));
    if (!stillExists) {
      selectedProjectId.value = '';
      projectView.value = 'list';
    }
  }
}

async function loadArchivedProjects() {
  const data = await request('/projects/?archived=1');
  archivedProjectRows.value = data.items || [];
}

async function openRecycleDrawer() {
  recycleDrawerOpen.value = true;
  deletingProjectId.value = null;
  recycleSearch.value = '';
  await loadArchivedProjects();
}

function closeRecycleDrawer() {
  recycleDrawerOpen.value = false;
  recycleSearch.value = '';
}

async function loadCustomRequests() {
  const data = await request('/custom-requests/');
  customRequests.value = data.items || [];
}

async function loadOrders() {
  const data = await request('/orders/');
  orders.value = data.items || [];
}

async function loadShippingAddresses() {
  const data = await request('/shipping-addresses/');
  shippingAddresses.value = data.items || [];
}

async function loadSigningInfos() {
  const data = await request('/signing-infos/');
  signingInfos.value = data.items || [];
}

async function loadExternalAccounts() {
  const data = await request('/external-accounts/');
  externalAccounts.value = data.items || [];
}

function resetExternalAccountForm() {
  Object.assign(externalAccountForm, { display_name: '', credit_code: '', username: '', password: '' });
}

function openExternalAccountCreateModal() {
  resetExternalAccountForm();
  externalAccountFormInitial.value = formSnapshot(externalAccountForm);
  externalAccountCreatedCredential.value = null;
  externalAccountCreating.value = true;
}

function closeExternalAccountCreateModal() {
  closeWithUnsavedGuard(externalAccountCreateHasChanges.value, () => {
    externalAccountCreating.value = false;
    externalAccountCreatedCredential.value = null;
    resetExternalAccountForm();
    externalAccountFormInitial.value = {};
  });
}

async function createExternalAccount() {
  const displayName = externalAccountForm.display_name.trim();
  const creditCode = externalAccountForm.credit_code.trim();
  const username = externalAccountForm.username.trim();
  const password = externalAccountForm.password.trim();
  if (!displayName) return setMessage('error', '请填写公司名称');
  if (!creditCode) return setMessage('error', '请填写统一社会信用代码');
  if (!username) return setMessage('error', '请填写登录账号');
  if (!password) return setMessage('error', '请填写登录密码');
  if (password.length < 6) return setMessage('error', '登录密码至少 6 位');
  await run(async () => {
    const data = await request('/external-accounts/', {
      method: 'POST',
      body: JSON.stringify({
        display_name: displayName,
        credit_code: creditCode,
        username,
        password,
      }),
    });
    externalAccountCreatedCredential.value = {
      username: data.item?.username || username,
      password: data.item?.initial_password || password,
    };
    resetExternalAccountForm();
    externalAccountFormInitial.value = formSnapshot(externalAccountForm);
    await loadExternalAccounts();
  }, '外部账号已创建');
}

function startExternalAccountEdit(item) {
  editingExternalAccountId.value = item.id;
  Object.assign(externalAccountEditForm, {
    display_name: item.display_name || '',
    credit_code: item.credit_code || '',
    status: item.status || 'active',
    password: '',
  });
  externalAccountEditInitial.value = formSnapshot(externalAccountEditForm);
}

function cancelExternalAccountEdit() {
  closeWithUnsavedGuard(externalAccountEditHasChanges.value, () => {
    forceCancelExternalAccountEdit();
  });
}

function forceCancelExternalAccountEdit() {
  editingExternalAccountId.value = null;
  Object.assign(externalAccountEditForm, { display_name: '', credit_code: '', status: 'active', password: '' });
  externalAccountEditInitial.value = {};
}

async function saveExternalAccountEdit(item) {
  if (!externalAccountEditForm.display_name.trim()) return setMessage('error', '请填写公司名称');
  if (!externalAccountEditForm.credit_code.trim()) return setMessage('error', '请填写统一社会信用代码');
  await run(async () => {
    const payload = {
      display_name: externalAccountEditForm.display_name.trim(),
      credit_code: externalAccountEditForm.credit_code.trim(),
      status: externalAccountEditForm.status,
    };
    if (externalAccountEditForm.password.trim()) payload.password = externalAccountEditForm.password.trim();
    await request(`/external-accounts/${item.id}/`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
    forceCancelExternalAccountEdit();
    await loadExternalAccounts();
  }, '外部账号已保存');
}

async function toggleExternalAccountStatus(item) {
  const nextStatus = item.status === 'active' ? 'disabled' : 'active';
  await run(async () => {
    await request(`/external-accounts/${item.id}/`, {
      method: 'PATCH',
      body: JSON.stringify({ status: nextStatus }),
    });
    await loadExternalAccounts();
  }, nextStatus === 'active' ? '外部账号已启用' : '外部账号已停用');
}

function resetAccountPasswordForm() {
  Object.assign(accountPasswordForm, { old_password: '', new_password: '', confirm_password: '' });
}

async function resetExternalAccountPassword() {
  const oldPassword = accountPasswordForm.old_password.trim();
  const newPassword = accountPasswordForm.new_password.trim();
  const confirmPassword = accountPasswordForm.confirm_password.trim();
  if (!oldPassword) return setMessage('error', '请填写原密码');
  if (!newPassword) return setMessage('error', '请填写新密码');
  if (newPassword.length < 6) return setMessage('error', '新密码至少 6 位');
  if (newPassword !== confirmPassword) return setMessage('error', '两次输入的新密码不一致');
  await run(async () => {
    await request('/password/', {
      method: 'POST',
      body: JSON.stringify({
        old_password: oldPassword,
        new_password: newPassword,
        confirm_password: confirmPassword,
      }),
    });
    resetAccountPasswordForm();
  }, '密码已重置');
}

function resetShippingAddressForm() {
  Object.assign(shippingAddressForm, { detail_address: '', receiver_name: '', receiver_phone: '' });
}

function openShippingAddressCreateModal(source = 'manager') {
  if (shippingAddressEditing.value && shippingAddressEditHasChanges.value) {
    requestDiscardChanges(() => {
      forceCancelShippingAddressEdit();
      openShippingAddressCreateModal(source);
    });
    return;
  }
  if (shippingAddressEditing.value) forceCancelShippingAddressEdit();
  resetShippingAddressForm();
  shippingAddressFormInitial.value = formSnapshot(shippingAddressForm);
  shippingAddressCreateSource.value = source;
  shippingAddressCreating.value = true;
}

function closeShippingAddressCreateModal() {
  closeWithUnsavedGuard(shippingAddressCreateHasChanges.value, () => {
    forceCloseShippingAddressCreateModal();
  });
}

function forceCloseShippingAddressCreateModal() {
  shippingAddressCreating.value = false;
  shippingAddressCreateSource.value = 'manager';
  resetShippingAddressForm();
  shippingAddressFormInitial.value = {};
}

function validateShippingAddressForm(form) {
  if (!form.detail_address.trim()) return '请填写详细地址与门牌号';
  if (!form.receiver_name.trim()) return '请填写收货人名字';
  if (!form.receiver_phone.trim()) return '请填写手机号';
  return '';
}

function resetShippingAddressEditForm() {
  Object.assign(shippingAddressEditForm, { detail_address: '', receiver_name: '', receiver_phone: '' });
}

async function createShippingAddress() {
  const message = validateShippingAddressForm(shippingAddressForm);
  if (message) return setMessage('error', message);
  await run(async () => {
    const data = await request('/shipping-addresses/', {
      method: 'POST',
      body: JSON.stringify({
        detail_address: shippingAddressForm.detail_address.trim(),
        receiver_name: shippingAddressForm.receiver_name.trim(),
        receiver_phone: shippingAddressForm.receiver_phone.trim(),
        created_by: accountName.value,
      }),
    });
    await loadShippingAddresses();
    if (shippingAddressCreateSource.value === 'order' && data.item) {
      pendingOrderShippingAddressId.value = data.item.id;
      orderAddressSearch.value = '';
    }
    forceCloseShippingAddressCreateModal();
  }, '收货地址已新增');
}

function startShippingAddressEdit(item, source = 'manager') {
  editingShippingAddressId.value = item.id;
  deletingShippingAddressId.value = null;
  shippingAddressEditSource.value = source;
  shippingAddressCreating.value = false;
  Object.assign(shippingAddressEditForm, {
    detail_address: item.detail_address || '',
    receiver_name: item.receiver_name || '',
    receiver_phone: item.receiver_phone || '',
  });
  shippingAddressEditInitial.value = formSnapshot(shippingAddressEditForm);
  shippingAddressEditing.value = true;
}

function cancelShippingAddressEdit() {
  closeWithUnsavedGuard(shippingAddressEditHasChanges.value, () => {
    forceCancelShippingAddressEdit();
  });
}

function forceCancelShippingAddressEdit() {
  shippingAddressEditing.value = false;
  shippingAddressEditSource.value = 'manager';
  editingShippingAddressId.value = null;
  resetShippingAddressEditForm();
  shippingAddressEditInitial.value = {};
}

async function saveShippingAddressEdit() {
  const message = validateShippingAddressForm(shippingAddressEditForm);
  if (message) return setMessage('error', message);
  const addressId = editingShippingAddressId.value;
  if (!addressId) return;
  await run(async () => {
    const payload = {
      detail_address: shippingAddressEditForm.detail_address.trim(),
      receiver_name: shippingAddressEditForm.receiver_name.trim(),
      receiver_phone: shippingAddressEditForm.receiver_phone.trim(),
    };
    const data = await request(`/shipping-addresses/${addressId}/`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
    await loadShippingAddresses();
    if (shippingAddressEditSource.value === 'order') {
      pendingOrderShippingAddressId.value = addressId;
      orderAddressSearch.value = '';
    } else if (Number(orderForm.shipping_address_id) === Number(addressId)) {
      const updatedAddress = shippingAddresses.value.find((item) => Number(item.id) === Number(addressId)) || data.item;
      applyOrderShippingAddress(updatedAddress);
    }
    forceCancelShippingAddressEdit();
  }, '收货地址已保存');
}

function startShippingAddressDelete(item) {
  deletingShippingAddressId.value = item.id;
  if (editingShippingAddressId.value === item.id) forceCancelShippingAddressEdit();
}

function cancelShippingAddressDelete() {
  deletingShippingAddressId.value = null;
}

async function deleteShippingAddress(item) {
  await run(async () => {
    await request(`/shipping-addresses/${item.id}/`, { method: 'DELETE' });
    await loadShippingAddresses();
    deletingShippingAddressId.value = null;
    if (Number(orderForm.shipping_address_id) === Number(item.id)) {
      orderForm.shipping_address_id = '';
      applyOrderShippingAddress(null);
    }
  }, '收货地址已删除');
}

function resetSigningInfoForm() {
  Object.assign(signingInfoForm, { company_name: '', opening_bank: '', tax_number: '', bank_account: '' });
}

function resetSigningInfoEditForm() {
  Object.assign(signingInfoEditForm, { company_name: '', opening_bank: '', tax_number: '', bank_account: '' });
}

function validateSigningInfoForm(form) {
  if (!form.company_name.trim()) return '请填写公司名称';
  if (!form.opening_bank.trim()) return '请填写开户银行';
  if (!form.tax_number.trim()) return '请填写税号';
  if (!form.bank_account.trim()) return '请填写账号';
  return '';
}

function openSigningInfoCreateModal(source = 'manager') {
  if (signingInfoEditing.value && signingInfoEditHasChanges.value) {
    requestDiscardChanges(() => {
      forceCancelSigningInfoEdit();
      openSigningInfoCreateModal(source);
    });
    return;
  }
  if (signingInfoEditing.value) forceCancelSigningInfoEdit();
  resetSigningInfoForm();
  signingInfoFormInitial.value = formSnapshot(signingInfoForm);
  signingInfoCreateSource.value = source;
  signingInfoCreating.value = true;
}

function closeSigningInfoCreateModal() {
  closeWithUnsavedGuard(signingInfoCreateHasChanges.value, () => {
    forceCloseSigningInfoCreateModal();
  });
}

function forceCloseSigningInfoCreateModal() {
  signingInfoCreating.value = false;
  signingInfoCreateSource.value = 'manager';
  resetSigningInfoForm();
  signingInfoFormInitial.value = {};
}

async function createSigningInfo() {
  const message = validateSigningInfoForm(signingInfoForm);
  if (message) return setMessage('error', message);
  await run(async () => {
    const data = await request('/signing-infos/', {
      method: 'POST',
      body: JSON.stringify({
        company_name: signingInfoForm.company_name.trim(),
        opening_bank: signingInfoForm.opening_bank.trim(),
        tax_number: signingInfoForm.tax_number.trim(),
        bank_account: signingInfoForm.bank_account.trim(),
        created_by: accountName.value,
      }),
    });
    await loadSigningInfos();
    if (signingInfoCreateSource.value === 'order' && data.item) {
      pendingOrderSigningInfoId.value = data.item.id;
      orderSigningInfoSearch.value = '';
    }
    forceCloseSigningInfoCreateModal();
  }, '公司抬头已新增');
}

function startSigningInfoEdit(item, source = 'manager') {
  editingSigningInfoId.value = item.id;
  deletingSigningInfoId.value = null;
  signingInfoEditSource.value = source;
  signingInfoCreating.value = false;
  Object.assign(signingInfoEditForm, {
    company_name: item.company_name || '',
    opening_bank: item.opening_bank || '',
    tax_number: item.tax_number || '',
    bank_account: item.bank_account || '',
  });
  signingInfoEditInitial.value = formSnapshot(signingInfoEditForm);
  signingInfoEditing.value = true;
}

function cancelSigningInfoEdit() {
  closeWithUnsavedGuard(signingInfoEditHasChanges.value, () => {
    forceCancelSigningInfoEdit();
  });
}

function forceCancelSigningInfoEdit() {
  signingInfoEditing.value = false;
  signingInfoEditSource.value = 'manager';
  editingSigningInfoId.value = null;
  resetSigningInfoEditForm();
  signingInfoEditInitial.value = {};
}

async function saveSigningInfoEdit() {
  const message = validateSigningInfoForm(signingInfoEditForm);
  if (message) return setMessage('error', message);
  const infoId = editingSigningInfoId.value;
  if (!infoId) return;
  await run(async () => {
    await request(`/signing-infos/${infoId}/`, {
      method: 'PATCH',
      body: JSON.stringify({
        company_name: signingInfoEditForm.company_name.trim(),
        opening_bank: signingInfoEditForm.opening_bank.trim(),
        tax_number: signingInfoEditForm.tax_number.trim(),
        bank_account: signingInfoEditForm.bank_account.trim(),
      }),
    });
    await loadSigningInfos();
    if (signingInfoEditSource.value === 'order') {
      pendingOrderSigningInfoId.value = infoId;
      orderSigningInfoSearch.value = '';
    }
    forceCancelSigningInfoEdit();
  }, '公司抬头已保存');
}

function startSigningInfoDelete(item) {
  deletingSigningInfoId.value = item.id;
  if (editingSigningInfoId.value === item.id) forceCancelSigningInfoEdit();
}

function cancelSigningInfoDelete() {
  deletingSigningInfoId.value = null;
}

async function deleteSigningInfo(item) {
  await run(async () => {
    await request(`/signing-infos/${item.id}/`, { method: 'DELETE' });
    await loadSigningInfos();
    deletingSigningInfoId.value = null;
    if (Number(orderForm.signing_info_id) === Number(item.id)) {
      orderForm.signing_info_id = '';
    }
    if (Number(pendingOrderSigningInfoId.value) === Number(item.id)) {
      pendingOrderSigningInfoId.value = '';
    }
  }, '公司抬头已删除');
}

function selectProject(item) {
  selectedProjectId.value = item.id;
}

function formatProjectDate(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '-';
  const yyyy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, '0');
  const dd = String(date.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

function enterProjectDetail(item) {
  selectedProjectId.value = item.id;
  projectInfoForm.name = item.name || '';
  projectInfoForm.note = item.note || '';
  projectDetailTab.value = 'packages';
  projectView.value = 'detail';
}

function backToProjectList() {
  projectView.value = 'list';
}

function startDeleteProject(item) {
  deletingProjectId.value = item.id;
}

function cancelDeleteProject() {
  deletingProjectId.value = null;
}

async function confirmDeleteProject(item) {
  if (!item) return cancelDeleteProject();
  await run(async () => {
    await request(`/projects/${item.id}/`, { method: 'DELETE' });
    deletingProjectId.value = null;
    await loadProjects();
  }, '项目已删除');
}

async function restoreProject(item) {
  await run(async () => {
    await request(`/projects/${item.id}/`, {
      method: 'PATCH',
      body: JSON.stringify({ is_archived: false }),
    });
    await Promise.all([loadProjects(), loadArchivedProjects()]);
  }, '项目已恢复');
}

function projectOrderQuantity(project) {
  return projectPackages(project).reduce((sum, item) => sum + Number(item.quantity || 0), 0);
}

function orderPackageQuantity(item) {
  return Math.max(Math.floor(Number(orderPackageQuantities[item.order_key] || item.order_quantity_default || 1)), 1);
}

function orderPackageAmount(item) {
  if (['cart-product', 'copy-product'].includes(item.order_source)) {
    return productLineAmount(item.product, orderPackageQuantity(item));
  }
  return (Number(item.order_amount || 0) * orderPackageQuantity(item)).toFixed(2);
}

function toggleOrderPackage(item, checked) {
  selectedOrderPackageIds[item.order_key] = checked;
  if (checked && !orderPackageQuantities[item.order_key]) {
    orderPackageQuantities[item.order_key] = Math.max(Math.floor(Number(item.order_quantity_default || 1)), 1);
  }
}

function toggleOrderPackageRow(item) {
  toggleOrderPackage(item, !selectedOrderPackageIds[item.order_key]);
}

function resetOrderForm() {
  Object.assign(orderForm, {
    external_account_id: props.externalMode ? (currentSession.value.id || '') : '',
    shipping_address_id: '',
    signing_info_id: '',
    customer_name: '',
    customer_phone: '',
    project_name: '',
    shipping_method: '快递',
    arrival_date: '',
    remark: '',
  });
  orderAddressSearch.value = '';
  orderSigningInfoSearch.value = '';
  orderAddressPickerOpen.value = false;
  orderSigningInfoPickerOpen.value = false;
  pendingOrderShippingAddressId.value = '';
  pendingOrderSigningInfoId.value = '';
  orderFormInitial.value = {};
  orderSelectionInitial.value = {};
}

function openOrderAddressDrawer() {
  orderAddressSearch.value = '';
  pendingOrderShippingAddressId.value = orderForm.shipping_address_id || '';
  orderAddressPickerOpen.value = true;
}

function closeOrderAddressDrawer() {
  closeWithUnsavedGuard(orderAddressPickerHasChanges.value, () => {
    forceCloseOrderAddressDrawer();
  });
}

function confirmOrderAddressDrawer() {
  if (!pendingOrderShippingAddress.value) return setMessage('error', '请选择收货地址');
  orderForm.shipping_address_id = pendingOrderShippingAddress.value.id;
  applyOrderShippingAddress(pendingOrderShippingAddress.value);
  forceCloseOrderAddressDrawer();
}

function confirmOrderAddressSelection(address) {
  if (!address) return;
  pendingOrderShippingAddressId.value = address.id;
  confirmOrderAddressDrawer();
}

function forceCloseOrderAddressDrawer() {
  orderAddressPickerOpen.value = false;
  pendingOrderShippingAddressId.value = orderForm.shipping_address_id || '';
}

function openOrderSigningInfoDrawer() {
  orderSigningInfoSearch.value = '';
  pendingOrderSigningInfoId.value = orderForm.signing_info_id || '';
  orderSigningInfoPickerOpen.value = true;
}

function closeOrderSigningInfoDrawer() {
  closeWithUnsavedGuard(orderSigningInfoPickerHasChanges.value, () => {
    forceCloseOrderSigningInfoDrawer();
  });
}

function confirmOrderSigningInfoDrawer() {
  if (!pendingOrderSigningInfo.value) return setMessage('error', '请选择公司抬头');
  orderForm.signing_info_id = pendingOrderSigningInfo.value.id;
  forceCloseOrderSigningInfoDrawer();
}

function confirmOrderSigningInfoSelection(info) {
  if (!info) return;
  pendingOrderSigningInfoId.value = info.id;
  confirmOrderSigningInfoDrawer();
}

function forceCloseOrderSigningInfoDrawer() {
  orderSigningInfoPickerOpen.value = false;
  pendingOrderSigningInfoId.value = orderForm.signing_info_id || '';
}

function applyOrderShippingAddress(address) {
  if (!address) {
    Object.assign(orderForm, {
      customer_name: '',
      customer_phone: '',
      project_name: '',
    });
    return;
  }
  Object.assign(orderForm, {
    customer_name: address.receiver_name || '',
    customer_phone: address.receiver_phone || '',
    project_name: address.detail_address || '',
  });
}

function selectOrderShippingAddress(address) {
  if (!address) return;
  pendingOrderShippingAddressId.value = address.id;
  orderAddressSearch.value = '';
}

function selectOrderSigningInfo(info) {
  if (!info) return;
  pendingOrderSigningInfoId.value = info.id;
  orderSigningInfoSearch.value = '';
}

function clearOrderSelection() {
  Object.keys(selectedOrderPackageIds).forEach((key) => {
    delete selectedOrderPackageIds[key];
  });
  Object.keys(orderPackageQuantities).forEach((key) => {
    delete orderPackageQuantities[key];
  });
}

async function openOrderCreate(initialTab = 'cart-products') {
  const nextTab = (
    orderCreateModes.includes(initialTab)
    || ['order-copy', 'order-edit'].includes(initialTab)
  ) ? initialTab : 'cart-products';
  await Promise.all([
    loadShippingAddresses(),
    loadSigningInfos(),
    props.externalMode ? Promise.resolve() : loadExternalAccounts(),
  ]);
  if (props.externalMode) {
    orderForm.external_account_id = currentSession.value.id || '';
  }
  orderCreateOpen.value = true;
  orderCreateTab.value = nextTab;
  orderProjectViewMode.value = 'cables';
  orderCreateSearch.value = '';
  orderAddressSearch.value = '';
  orderSigningInfoSearch.value = '';
  orderAddressPickerOpen.value = false;
  orderSigningInfoPickerOpen.value = false;
  if (nextTab === 'cart-products') selectAllProductCartRows();
  if (nextTab === 'project-classrooms') {
    orderableProjectRows.value
      .filter((item) => selectedOrderPackageIds[item.order_key])
      .forEach((item) => {
        orderPackageQuantities[item.order_key] = 1;
        projectOrderCableRows(item).forEach((row) => {
          orderPackageQuantities[`project-cable:${item.id}:${row.key}`] = row.quantity;
        });
      });
  }
  if (nextTab === 'order-copy') {
    orderCopyRows.value.forEach((item) => {
      selectedOrderPackageIds[item.order_key] = true;
      orderPackageQuantities[item.order_key] = Math.max(Math.floor(Number(item.order_quantity_default || 1)), 1);
    });
  }
  if (nextTab === 'order-edit') {
    orderEditRows.value.forEach((item) => {
      selectedOrderPackageIds[item.order_key] = true;
      orderPackageQuantities[item.order_key] = Math.max(Math.floor(Number(item.order_quantity_default || 1)), 1);
    });
  }
  orderFormInitial.value = formSnapshot(orderForm);
  orderSelectionInitial.value = {
    tab: orderCreateTab.value,
    form: formSnapshot(orderForm),
    selected: formSnapshot(selectedOrderPackageIds),
    quantities: formSnapshot(orderPackageQuantities),
  };
}

function closeOrderCreate() {
  closeWithUnsavedGuard(orderCreateHasChanges.value, () => {
    forceCloseOrderCreate();
  });
}

function forceCloseOrderCreate() {
  orderCreateOpen.value = false;
  orderCreateTab.value = 'cart-products';
  orderCreateSearch.value = '';
  orderCopyDraft.value = null;
  orderCopyWarnings.value = [];
  orderEditDraft.value = null;
  resetOrderForm();
}

function closeOrderDetail() {
  orderDetailOpen.value = false;
  orderDetailTab.value = 'info';
  orderDetailProductView.value = 'cables';
}

function orderPackageItemsCount(order) {
  return (order?.packages || []).reduce((sum, item) => sum + (item.items || []).length, 0);
}

function projectNameExists(name, ignoreProjectId = null) {
  const normalizedName = name.trim();
  if (!normalizedName) return false;
  return projects.value.some(
    (item) => item.id !== ignoreProjectId && String(item.name || '').trim() === normalizedName
  );
}

async function createProject() {
  const name = projectForm.name.trim();
  if (!name) return setMessage('error', '项目名称不能为空');
  if (projectNameExists(name)) return setMessage('error', '项目名称已存在，请换一个');
  await run(async () => {
    const data = await request('/projects/', {
      method: 'POST',
      body: JSON.stringify({
        name,
        created_by: accountName.value,
        note: projectForm.note.trim(),
      }),
    });
    Object.assign(projectForm, { name: '', note: '' });
    forceCloseProjectCreateModal();
    await loadProjects();
    enterProjectDetail(data.item);
  }, '项目已创建');
}

function openProjectCreateModal() {
  Object.assign(projectForm, { name: '', note: '' });
  projectFormInitial.value = formSnapshot(projectForm);
  projectCreating.value = true;
}

function closeProjectCreateModal() {
  closeWithUnsavedGuard(projectCreateHasChanges.value, () => {
    forceCloseProjectCreateModal();
  });
}

function forceCloseProjectCreateModal() {
  projectCreating.value = false;
  Object.assign(projectForm, { name: '', note: '' });
  projectFormInitial.value = {};
}

async function saveProjectInfo() {
  if (!selectedProject.value) return;
  const name = projectInfoForm.name.trim();
  if (!name) return setMessage('error', '项目名称不能为空');
  if (projectNameExists(name, selectedProject.value.id)) return setMessage('error', '项目名称已存在，请换一个');
  await run(async () => {
    await request(`/projects/${selectedProject.value.id}/`, {
      method: 'PATCH',
      body: JSON.stringify({
        name,
        note: projectInfoForm.note.trim(),
      }),
    });
    await loadProjects();
  }, '项目信息已保存');
}

async function createProjectClassroom() {
  if (!selectedProject.value) return setMessage('error', '请先选择项目');
  const classroomName = classroomCreateForm.name.trim();
  if (!classroomName) return setMessage('error', '教室类别不能为空');
  await run(async () => {
    await Promise.all(['教室内', '教室外'].map((scope) => request('/packages/', {
      method: 'POST',
      body: JSON.stringify({
        project_id: selectedProject.value.id,
        classroom_name: classroomName,
        classroom_scope: scope,
        name: `${classroomName}-${scope}`,
      }),
    })));
    Object.assign(classroomCreateForm, { name: '' });
    forceCloseClassroomCreateModal();
    await loadPackages();
    await loadProjects();
  }, '教室类别已创建');
}

function openClassroomCreateModal() {
  classroomCreateForm.name = '';
  classroomCreateInitial.value = formSnapshot(classroomCreateForm);
  classroomCreating.value = true;
}

function fillClassroomNamePreset(name) {
  classroomCreateForm.name = name;
  nextTick(() => {
    const input = classroomNameInput.value;
    if (!input) return;
    input.focus();
    input.setSelectionRange(name.length, name.length);
  });
}

function closeClassroomCreateModal() {
  closeWithUnsavedGuard(classroomCreateHasChanges.value, () => {
    forceCloseClassroomCreateModal();
  });
}

function forceCloseClassroomCreateModal() {
  classroomCreating.value = false;
  classroomCreateForm.name = '';
  classroomCreateInitial.value = {};
}

async function updateProjectClassroomRoomCount(classroom, value) {
  const quantity = Math.max(Math.floor(Number(value || 1)), 1);
  const items = classroomPackages(classroom);
  if (!items.length) return;
  await run(async () => {
    await Promise.all(items.map((item) => request(`/packages/${item.id}/`, {
      method: 'PATCH',
      body: JSON.stringify({ quantity }),
    })));
    await loadPackages();
    await loadProjects();
  });
}

function openProjectPackageDetail(item) {
  if (!item) return;
  openPackageDetail(item);
}

function openProjectClassroomDetail(classroom, event) {
  if (event?.target?.closest('button, input, a, select, textarea')) return;
  openProjectPackageDetail(classroomIndoorPackage(classroom));
}

function openProjectClassroomScopeDetail(classroom, scopeRow, event) {
  if (event?.target?.closest('button, input, a, select, textarea')) return;
  openProjectPackageDetail(scopeRow?.package || classroomIndoorPackage(classroom));
}

async function confirmAddCableProducts() {
  const targetPackageId = detailPackage.value?.id || selectedPackageId.value;
  if (!targetPackageId) return setMessage('error', '请先选择线材清单');
  const selectedItems = Object.entries(addCableQuantities)
    .map(([productId, value]) => ({
      product: addCableSelectedProducts[productId],
      quantity: Math.floor(Number(value || 0)),
    }))
    .filter((item) => item.product && item.quantity >= 0);

  const selectedSources = new Set(selectedItems.map((item) => String(item.product.product_archive_id)));
  const representedSources = new Set(addCableProductRows.value.map(({ product }) => String(product.product_archive_id)));
  const currentItemsBySource = (detailPackage.value?.items || []).reduce((map, item) => {
    const key = String(item.product_archive_id);
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(item);
    return map;
  }, new Map());
  const tasks = [];

  selectedItems.forEach((item) => {
    const sourceKey = String(item.product.product_archive_id);
    const currentItems = currentItemsBySource.get(sourceKey) || [];
    if (item.quantity >= 1) {
      if (currentItems.length) {
        const [primaryItem, ...duplicateItems] = currentItems;
        tasks.push(request(`/package-items/${primaryItem.id}/`, {
          method: 'PATCH',
          body: JSON.stringify({ quantity: item.quantity }),
        }));
        duplicateItems.forEach((duplicateItem) => {
          tasks.push(request(`/package-items/${duplicateItem.id}/`, { method: 'DELETE' }));
        });
        return;
      }
      tasks.push(request(`/packages/${targetPackageId}/items/`, {
        method: 'POST',
        body: JSON.stringify({ product_id: item.product.id, quantity: item.quantity }),
      }));
      return;
    }
    currentItems.forEach((currentItem) => {
      tasks.push(request(`/package-items/${currentItem.id}/`, { method: 'DELETE' }));
    });
  });

  currentItemsBySource.forEach((items, sourceKey) => {
    if (selectedSources.has(sourceKey)) return;
    if (!representedSources.has(sourceKey)) return;
    items.forEach((item) => {
      tasks.push(request(`/package-items/${item.id}/`, { method: 'DELETE' }));
    });
  });

  await run(async () => {
    await Promise.all(tasks);
    await loadPackages();
    addCableProductRows.value.forEach(({ product }) => {
      packageProductQuantities[`product:${product.id}`] = Math.max(Math.floor(Number(addCableQuantities[product.id] || 0)), 0);
    });
    clearAddCableDraft();
    forceCloseAddCableModal();
  }, '已修改线材');
}

function updateDetailRowQuantity(row, quantity) {
  const normalizedQuantity = Math.max(Math.floor(Number(quantity || 1)), 1);
  packageProductQuantities[detailRowKey(row)] = normalizedQuantity;
}

function startDeleteDetailRow(row) {
  deletingDetailRowKey.value = detailRowKey(row);
}

function cancelDeleteDetailRow() {
  deletingDetailRowKey.value = '';
}

function confirmDeleteDetailRow(row) {
  const key = detailRowKey(row);
  detailDeletedRowKeys[key] = true;
  row.packageItems.forEach((item) => {
    detailDeletedItemIds[item.id] = true;
  });
  packageProductQuantities[key] = 0;
  deletingDetailRowKey.value = '';
}

function updateAddCableQuantity(product, value) {
  const quantity = value === '' ? '' : Math.max(Math.floor(Number(value || 0)), 0);
  addCableQuantities[product.id] = quantity;
  if (quantity !== '') {
    addCableQuantities[product.id] = quantity;
    addCableSelectedProducts[product.id] = product;
    return;
  }
  delete addCableSelectedProducts[product.id];
}

function isAddCableProductSelected(product) {
  return Math.floor(Number(addCableQuantities[product.id] || 0)) >= 1;
}

function addCableQuantityDisplay(product) {
  const value = addCableQuantities[product.id];
  return value === undefined ? '' : value;
}

function cancelPackageEdit() {
  closeWithUnsavedGuard(packageEditHasChanges.value, () => {
    forceCancelPackageEdit();
  });
}

function forceCancelPackageEdit() {
  editingPackageId.value = null;
  packageEditForm.name = '';
  packageEditForm.note = '';
  packageEditInitial.value = {};
}

function startPackageDelete(item) {
  deletingPackageId.value = item.id;
  editingPackageId.value = null;
  packageEditForm.name = '';
  packageEditForm.note = '';
}

function cancelPackageDelete() {
  deletingPackageId.value = null;
}

function startClassroomDelete() {
  if (!detailIsClassroomPackage.value || !detailPackage.value) return;
  closeWithUnsavedGuard(detailHasUnsavedChanges.value, () => {
    deletingClassroom.value = {
      projectId: detailPackage.value.project_id,
      classroomName: detailPackage.value.classroom_name,
    };
  });
}

function cancelClassroomDelete() {
  deletingClassroom.value = null;
}

async function removePackageItem(item) {
  await run(async () => {
    await request(`/package-items/${item.id}/`, { method: 'DELETE' });
    await loadPackages();
  }, '已删除明细');
}

async function archivePackage(item) {
  if (!item) return cancelPackageDelete();
  await run(async () => {
    await request(`/packages/${item.id}/`, { method: 'DELETE' });
    await loadPackages();
    deletingPackageId.value = null;
    if (Number(packageDetailId.value) === Number(item.id)) closePackageDetail();
  }, '线材清单已删除');
}

async function archiveClassroom() {
  const target = deletingClassroom.value;
  if (!target) return;
  const targetPackages = activePackages.value.filter((item) => (
    Number(item.project_id) === Number(target.projectId)
    && item.classroom_name === target.classroomName
  ));
  if (!targetPackages.length) {
    deletingClassroom.value = null;
    closePackageDetail();
    return;
  }
  await run(async () => {
    await Promise.all(targetPackages.map((item) => request(`/packages/${item.id}/`, { method: 'DELETE' })));
    await loadPackages();
    deletingClassroom.value = null;
    discardPackageDetailChanges();
  }, '教室已删除');
}

async function submitCustomRequest() {
  const categoryA = customCategoryContext.category_a.trim();
  const categoryB = customCategoryContext.category_b.trim();
  if (!categoryA || !categoryB) {
    return setMessage('error', '请选择线材分类');
  }
  if (!customForm.length_m) {
    return setMessage('error', '请填写长度');
  }
  if (customForm.head_a_gender === '其他' && !customForm.head_a_other.trim()) {
    return setMessage('error', '请填写第一头其他描述');
  }
  if (customForm.head_b_gender === '其他' && !customForm.head_b_other.trim()) {
    return setMessage('error', '请填写第二头其他描述');
  }
  const headAType = customForm.head_a_gender === '其他' ? customForm.head_a_other.trim() : customForm.head_a_gender;
  const headBType = customForm.head_b_gender === '其他' ? customForm.head_b_other.trim() : customForm.head_b_gender;
  const payload = {
    head_a_type: headAType,
    head_a_gender: customForm.head_a_gender,
    head_b_type: headBType,
    head_b_gender: customForm.head_b_gender,
    length_m: customForm.length_m,
    quantity: customForm.quantity,
    category_a: categoryA,
    category_b: categoryB,
    note: customForm.note,
    contact_name: accountName.value,
    contact_phone: currentUserId.value,
    scenario: '',
  };
  await run(async () => {
    if (restartingCustomRequestId.value) {
      const targetRequest = customRequests.value.find((item) => Number(item.id) === Number(restartingCustomRequestId.value));
      if (!isRequesterCanceledCustom(targetRequest)) throw new Error('内部取消的定制需求不能重新发起');
      await request(`/custom-requests/${restartingCustomRequestId.value}/`, {
        method: 'PATCH',
        body: JSON.stringify({
          ...payload,
          status: '待处理',
          handle_result: '重新发起',
          bound_product_id: null,
        }),
      });
    } else {
      await request('/custom-requests/', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
    }
    resetCustomForm();
    await loadCustomRequests();
    forceCloseCustomCreateModal();
  }, restartingCustomRequestId.value ? '定制需求已重新发起' : '定制需求已提交');
}

async function updateRequestStatus(item, status) {
  await run(async () => {
    await request(`/custom-requests/${item.id}/`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    });
    await loadCustomRequests();
  });
}

async function updateCustomRequestAction(item, payload, successMessage) {
  if (!item?.id) return;
  await run(async () => {
    await request(`/custom-requests/${item.id}/`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
    await loadCustomRequests();
  }, successMessage);
}

function cancelCustomRequest(item) {
  updateCustomRequestAction(item, {
    status: '已取消',
    handle_result: isExternalMode.value ? '外部用户取消' : '内部取消',
  }, '定制需求已取消');
}

function restartCustomRequest(item) {
  openCustomRestartModal(item);
}

function ignoreCustomRequest(item) {
  updateCustomRequestAction(item, {
    status: '已忽略',
    handle_result: '暂不考虑',
  }, '已标记为暂不考虑');
}

function openCustomBoundDetail(item) {
  customBoundDetailRequest.value = item;
  customBoundDetailOpen.value = true;
}

function closeCustomBoundDetail() {
  customBoundDetailOpen.value = false;
  customBoundDetailRequest.value = null;
}

async function openCustomBindModal(item) {
  customBindForm.requestId = item?.id || null;
  customBindForm.productId = item?.bound_product_id || '';
  customBindInitial.value = formSnapshot(customBindForm, ['productId']);
  customBindSearch.value = '';
  customBinding.value = true;
  if (!drawerProducts.value.length) await loadDrawerProducts();
}

function closeCustomBindModal() {
  closeWithUnsavedGuard(customBindHasChanges.value, () => {
    forceCloseCustomBindModal();
  });
}

function forceCloseCustomBindModal() {
  customBinding.value = false;
  customBindSearch.value = '';
  customBindInitial.value = {};
  Object.assign(customBindForm, { requestId: null, productId: '' });
}

async function bindCustomRequestToProduct() {
  const requestItem = activeCustomBindRequest.value;
  const product = drawerProducts.value.find((item) => Number(item.id) === Number(customBindForm.productId));
  if (!requestItem) return setMessage('error', '请选择定制需求');
  if (!product) return setMessage('error', '请选择要绑定的现有线材');
  await run(async () => {
    await request(`/custom-requests/${requestItem.id}/`, {
      method: 'PATCH',
      body: JSON.stringify({
        status: '已绑定',
        bound_product_id: product.id,
        handle_result: `已绑定：${customBoundProductTitle(product)}`,
      }),
    });
    forceCloseCustomBindModal();
    await loadCustomRequests();
  }, '定制需求已绑定现有线材');
}

async function createOrder() {
  if (!selectedOrderPackages.value.length) return setMessage('error', '请选择需要下单的线材或项目');
  if (!selectedOrderCustomer.value?.display_name) return setMessage('error', '请选择客户');
  if (!selectedOrderShippingAddress.value) return setMessage('error', '请选择收货地址');
  if (!selectedOrderSigningInfo.value) return setMessage('error', '请选择公司抬头');
  if (!orderForm.customer_name.trim()) return setMessage('error', '请填写收货人');
  if (!orderForm.customer_phone.trim()) return setMessage('error', '请填写手机号');
  if (!orderForm.project_name.trim()) return setMessage('error', '请填写详细地址与门牌号');
  const payload = {
    ...orderForm,
    save_as_package: false,
    packages: selectedOrderPackages.value.flatMap((item) => {
      const orderQuantity = orderPackageQuantity(item);
      if (item.order_source === 'cart-product') return [];
      if (item.order_source === 'copy-product') return [];
      if (item.order_source === 'project') {
        return item.order_packages.map((packageItem) => ({
          package_id: packageItem.id,
          source: 'project',
          quantity: Math.max(Math.floor(Number(packageItem.quantity || 1)), 1) * orderQuantity,
        }));
      }
      return [];
    }),
    products: selectedOrderPackages.value
      .filter((item) => ['cart-product', 'copy-product', 'edit-product'].includes(item.order_source))
      .map((item) => ({
        product_id: item.product_id || item.product.id,
        quantity: orderPackageQuantity(item),
      })),
  };
  if (orderCreateTab.value === 'order-edit') {
    if (!orderEditDraft.value?.id) return setMessage('error', '缺少要编辑的订单');
    payload.save_as_package = false;
    await run(async () => {
      const data = await request(`/orders/${orderEditDraft.value.id}/`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
      });
      selectedOrder.value = sortOrderDetailCables(data.item);
      resetOrderDetailView();
      orderStatusFilter.value = '未锁定';
      await loadOrders();
      clearOrderSelection();
      forceCloseOrderCreate();
      orderDetailOpen.value = true;
    }, '订单已保存');
    return;
  }
  await run(async () => {
    const data = await request('/orders/checkout/', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    selectedOrder.value = sortOrderDetailCables(data.item);
    resetOrderDetailView();
    if (data.item?.status) orderStatusFilter.value = data.item.status === '未锁定' ? '未锁定' : '进行中';
    await loadOrders();
    clearOrderSelection();
    if (payload.products.length && orderCreateTab.value !== 'order-copy') {
      const orderedProductIds = new Set(payload.products.map((item) => Number(item.product_id)));
      productCartItems.value = productCartItems.value.filter((item) => !orderedProductIds.has(Number(item.product?.id)));
      await loadProductCart();
    }
    forceCloseOrderCreate();
    orderDetailOpen.value = true;
  }, '订单已创建');
}

async function openOrderDetail(order) {
  await run(async () => {
    const data = await request(`/orders/${order.id}/`);
    selectedOrder.value = sortOrderDetailCables(data.item);
    resetOrderDetailView();
    orderDetailOpen.value = true;
  });
}

async function copyOrder(order) {
  await run(async () => {
    const data = await request(`/orders/${order.id}/copy/`);
    const draft = data.item || {};
    orderCopyDraft.value = draft;
    orderCopyWarnings.value = draft.warnings || [];
    orderDetailOpen.value = false;
    clearOrderSelection();
    await Promise.all([loadShippingAddresses(), loadSigningInfos()]);
    Object.assign(orderForm, {
      external_account_id: draft.customer_external_account_id || draft.external_account_id || '',
      shipping_address_id: draft.shipping_address_id || '',
      signing_info_id: draft.signing_info_id || '',
      customer_name: draft.customer_name || '',
      customer_phone: draft.customer_phone || '',
      project_name: draft.project_name || '',
      shipping_method: draft.shipping_method || '快递',
      arrival_date: draft.arrival_date || '',
      remark: draft.remark || '',
    });
    orderDetailOpen.value = false;
    await openOrderCreate('order-copy');
    if (orderCopyWarnings.value.length) {
      setMessage('error', orderCopyWarnings.value.map((item) => item.message).join('；'));
    } else {
      setMessage('notice', '已生成复制订单草稿');
    }
  });
}

async function printOrderPdf(order = selectedOrder.value) {
  if (!order?.id) return setMessage('error', '请先选择订单');
  if (!order.can_export_pdf) return setMessage('error', '锁单后才能下载 PDF');
  const pdfPath = order.pdf_url || `/api/orders/${order.id}/export.pdf`;
  const url = new URL(pdfPath, API_BASE_URL).toString();
  await run(async () => {
    const response = await fetch(url, {
      headers: authHeadersForFileRequest(),
      credentials: props.externalMode ? 'same-origin' : 'include',
    });
    if (response.status === 401 || response.status === 403) {
      throw new Error('登录已失效，请刷新后重试');
    }
    if (!response.ok) {
      let message = 'PDF 生成失败';
      try {
        const data = await response.json();
        message = data?.error || data?.message || message;
      } catch {
        message = `${message}（${response.status}）`;
      }
      throw new Error(message);
    }
    const blob = await response.blob();
    if (!blob.size) throw new Error('PDF 文件为空');
    const objectUrl = URL.createObjectURL(new Blob([blob], { type: 'application/pdf' }));
    const link = document.createElement('a');
    link.href = objectUrl;
    link.download = `${order.order_no || '线材订单'}.pdf`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
  }, 'PDF 已开始下载');
}

async function refreshOrderDetail(orderId) {
  if (!orderId) return;
  const data = await request(`/orders/${orderId}/`);
  selectedOrder.value = sortOrderDetailCables(data.item);
  if (orderDetailProductView.value === 'classrooms' && !selectedOrderHasProjectView.value) {
    orderDetailProductView.value = 'cables';
  }
}

function patchOrderRow(nextOrder) {
  if (!nextOrder?.id) return;
  const index = orders.value.findIndex((item) => Number(item.id) === Number(nextOrder.id));
  if (index >= 0) orders.value.splice(index, 1, { ...orders.value[index], ...nextOrder });
  if (selectedOrder.value && Number(selectedOrder.value.id) === Number(nextOrder.id)) {
    selectedOrder.value = sortOrderDetailCables({ ...selectedOrder.value, ...nextOrder });
    if (orderDetailProductView.value === 'classrooms' && !selectedOrderHasProjectView.value) {
      orderDetailProductView.value = 'cables';
    }
  }
}

function orderDetailToProductDraft(order) {
  const productMap = new Map(drawerProducts.value.map((product) => [String(product.product_archive_id), product]));
  const quantityMap = new Map();
  (order.packages || []).forEach((orderPackage) => {
    (orderPackage.items || []).forEach((item) => {
      const product = productMap.get(String(item.product_archive_id));
      if (!product) return;
      const key = String(product.id);
      const current = quantityMap.get(key) || { product_id: product.id, quantity: 0, product };
      current.quantity += Number(item.total_quantity || item.quantity_per_package || 1);
      quantityMap.set(key, current);
    });
  });
  return Array.from(quantityMap.values());
}

async function editOrder(order) {
  if (!order?.id) return setMessage('error', '请先选择订单');
  await run(async () => {
    const data = await request(`/orders/${order.id}/`);
    const detail = sortOrderDetailCables(data.item);
    if (detail.status !== '未锁定') throw new Error('锁单后不能修改订单，只能复制下单');
    await Promise.all([loadShippingAddresses(), loadSigningInfos(), loadDrawerProducts()]);
    const products = orderDetailToProductDraft(detail);
    if (!products.length) throw new Error('订单内线材已不存在，请复制订单重新选择');
    orderEditDraft.value = {
      id: detail.id,
      order_no: detail.order_no,
      products,
    };
    orderCopyDraft.value = null;
    orderCopyWarnings.value = [];
    selectedOrder.value = detail;
    Object.assign(orderForm, {
      external_account_id: detail.customer_external_account_id || detail.external_account_id || '',
      shipping_address_id: detail.source_shipping_address_id || '',
      signing_info_id: detail.source_signing_info_id || detail.signing_info_id || '',
      customer_name: detail.customer_name || '',
      customer_phone: detail.customer_phone || '',
      project_name: detail.project_name || '',
      shipping_method: detail.shipping_method || '快递',
      arrival_date: detail.arrival_date || '',
      remark: detail.remark || '',
    });
    orderDetailOpen.value = false;
    clearOrderSelection();
    await openOrderCreate('order-edit');
    setMessage('notice', '已进入未锁定订单编辑');
  });
}

function confirmEditOrder(order) {
  if (!order?.id) return setMessage('error', '请先选择订单');
  requestDiscardChanges(() => editOrder(order), {
    title: '确认编辑订单',
    message: `确定要编辑订单 ${order.order_no || ''} 吗？编辑会重新进入下单页面，未保存前不会影响当前订单。`,
    cancelText: '取消',
    confirmText: '确认编辑',
    confirmClass: 'primary-confirm',
  });
}

async function runOrderStatusAction(order, action, successMessage, formData = null) {
  if (!order?.id) return setMessage('error', '请先选择订单');
  await run(async () => {
    const data = formData
      ? await fileRequest(`/orders/${order.id}/${action}/`, { method: 'POST', body: formData })
      : await request(`/orders/${order.id}/${action}/`, { method: 'POST' });
    patchOrderRow(data.item);
    if (data.item?.status) {
      orderStatusFilter.value = ['已完结', '未锁定', '已删除'].includes(data.item.status) ? data.item.status : '进行中';
    }
    if (selectedOrder.value && Number(selectedOrder.value.id) === Number(order.id)) {
      await refreshOrderDetail(order.id);
    }
    await loadOrders();
  }, successMessage);
}

function askOrderFile(accept = '') {
  return new Promise((resolve) => {
    const input = document.createElement('input');
    input.type = 'file';
    if (accept) input.accept = accept;
    input.style.position = 'fixed';
    input.style.left = '-9999px';
    let settled = false;
    const finish = (file = null) => {
      if (settled) return;
      settled = true;
      window.removeEventListener('focus', handleFocus);
      input.remove();
      resolve(file);
    };
    const handleFocus = () => {
      window.setTimeout(() => finish(input.files?.[0] || null), 300);
    };
    input.addEventListener('change', () => {
      const [file] = input.files || [];
      finish(file || null);
    }, { once: true });
    input.addEventListener('cancel', () => finish(null), { once: true });
    document.body.appendChild(input);
    window.addEventListener('focus', handleFocus, { once: true });
    input.click();
  });
}

async function lockOrder(order) {
  return runOrderStatusAction(order, 'lock', '订单已锁定，已进入待签合同');
}

async function deleteOrder(order) {
  return runOrderStatusAction(order, 'delete', '订单已删除');
}

function confirmDeleteOrder(order) {
  if (!order?.id) return setMessage('error', '请先选择订单');
  requestDiscardChanges(() => deleteOrder(order), {
    title: '确认删除订单',
    message: `确定要删除订单 ${order.order_no || ''} 吗？删除后订单会进入已删除状态。`,
    cancelText: '取消',
    confirmText: '确认删除',
    confirmClass: 'danger-confirm',
  });
}

async function restoreOrder(order) {
  return runOrderStatusAction(order, 'restore', '订单已恢复');
}

function orderProgressAction(key) {
  if (key === 'shipment') return 'ship';
  return key;
}

function orderProgressUploadLabel(key) {
  if (key === 'contract') return '合同附件';
  if (key === 'shipment') return '发货附件';
  if (key === 'invoice') return '开票附件';
  if (key === 'payment') return '收款附件';
  return '附件';
}

async function uploadOrderProgress(order, key) {
  const file = await askOrderFile(orderWorkflowFileAccept);
  if (!file) return null;
  const formData = new FormData();
  formData.append('file', file);
  formData.append('action', 'upload');
  return runOrderStatusAction(order, orderProgressAction(key), `${orderProgressUploadLabel(key)}已上传`, formData);
}

function updateOrderProgress(order, key, updates = {}, successMessage = '进度已保存') {
  const formData = new FormData();
  formData.append('action', 'update');
  if (Object.prototype.hasOwnProperty.call(updates, 'status')) formData.append('status', updates.status || '');
  if (Object.prototype.hasOwnProperty.call(updates, 'note')) formData.append('note', updates.note || '');
  return runOrderStatusAction(order, orderProgressAction(key), successMessage, formData);
}

async function changeOrderProgressStatus(order, key, status) {
  if (!order?.id) return;
  await updateOrderProgress(order, key, {
    status,
    note: orderProgressNote(order, key),
  }, '进度状态已保存');
  clearOrderProgressNoteDraft(order, key);
}

async function saveOrderProgressNote(order, key) {
  if (!order?.id) return;
  const note = orderProgressNote(order, key);
  const current = order?.[orderProgressNoteField(key)] || '';
  if (String(note || '') === String(current || '')) return;
  await updateOrderProgress(order, key, { note }, '进度备注已保存');
  clearOrderProgressNoteDraft(order, key);
}

function completeOrderProgress(order, key) {
  const label = orderDetailProgressBubbles.find((item) => item.key === key)?.label || '进度';
  const formData = new FormData();
  formData.append('action', 'complete');
  formData.append('note', orderProgressNote(order, key));
  return runOrderStatusAction(order, orderProgressAction(key), `${label}已完成`, formData);
}

function toggleOrderProgressComplete(order, key) {
  if (orderProgressTime(order, key)) {
    return changeOrderProgressStatus(order, key, orderProgressPendingStatus(key));
  }
  return completeOrderProgress(order, key);
}

async function receiveOrder(order) {
  return runOrderStatusAction(order, 'receive', '订单已签收，已完结');
}

function orderActionButtons(order) {
  if (!order) return [];
  if (order.status === '未锁定') return [
    { key: 'edit', label: '编辑', handler: confirmEditOrder },
    { key: 'lock', label: '锁定', className: 'primary-action', handler: lockOrder },
    { key: 'delete', label: '删除', className: 'danger-action', handler: confirmDeleteOrder },
  ];
  if (order.status === '已删除') return [
    { key: 'restore', label: '恢复', className: 'primary-action', handler: restoreOrder },
  ];
  return [
    { key: 'copy', label: '再次下单', className: 'primary-action', handler: copyOrder },
  ];
}

function normalizePermissionRule(item = {}) {
  const rawScopeType = item.scopeType || item.scope_type || '';
  return {
    permission: item.permission || '',
    permissionLabel: item.permissionLabel || '',
    scopeType: rawScopeType,
    scopeLabel: item.scopeLabel || '',
    targetId: String(item.targetId || item.target_id || ''),
    targetName: item.targetName || item.target_name || '',
    sortOrder: Number(item.sortOrder || item.sort_order || 0),
  };
}

function permissionRuleKey(permission, scopeType, targetId) {
  return `${permission}:${scopeType}:${targetId}`;
}

function rulesForPermission(permission, scopeType) {
  return adminPermissionRules.value.filter((rule) => (
    rule.permission === permission
    && (
      rule.scopeType === scopeType
      || (scopeType === 'department' && rule.scopeType === 'departmentSub')
    )
  ));
}

function permissionRuleExists(permission, scopeType, targetId) {
  return adminPermissionRules.value.some((rule) => permissionRuleKey(rule.permission, rule.scopeType, rule.targetId) === permissionRuleKey(permission, scopeType, targetId));
}

function permissionSelectedCount(permission) {
  return permissionMemberRows(permission).length;
}

function permissionSourceCount(permission) {
  return adminPermissionRules.value.filter((rule) => (
    rule.permission === permission && rule.scopeType !== 'excludedEmployee'
  )).length;
}

function normalizePermissionDepartmentTree(rows = [], depth = 0) {
  return (Array.isArray(rows) ? rows : []).map((item) => {
    const id = String(item.deptId || item.dept_id || item.id || '');
    if (!id) return null;
    const children = normalizePermissionDepartmentTree(item.children || [], depth + 1);
    return {
      id,
      name: String(item.name || id),
      depth,
      parentId: String(item.parentDeptId || item.parent_dept_id || ''),
      pinyinInitials: String(item.pinyinInitials || item.pinyin_initials || '').toLowerCase(),
      departmentPathText: String(item.departmentPathText || item.department_path_text || ''),
      childIds: children.flatMap((child) => [child.id, ...(child.childIds || [])]),
      children,
    };
  }).filter(Boolean);
}

function flattenPermissionDepartments(rows = [], output = []) {
  rows.forEach((item) => {
    output.push(item);
    flattenPermissionDepartments(item.children || [], output);
  });
  return output;
}

function normalizePermissionEmployeeDepartment(item = {}) {
  return {
    id: String(item.deptId || item.dept_id || item.id || ''),
    name: String(item.name || ''),
    pinyinInitials: String(item.pinyinInitials || item.pinyin_initials || '').toLowerCase(),
    departmentPathText: String(item.departmentPathText || item.department_path_text || ''),
  };
}

function normalizePermissionEmployee(item = {}) {
  const id = String(item.userId || item.user_id || item.id || '');
  return {
    id,
    name: String(item.name || item.rawName || id),
    avatarUrl: String(item.avatarUrl || item.avatar_url || ''),
    pinyinInitials: String(item.pinyinInitials || item.pinyin_initials || '').toLowerCase(),
    departments: (Array.isArray(item.departments) ? item.departments : [])
      .map(normalizePermissionEmployeeDepartment)
      .filter((department) => department.id || department.name),
  };
}

function permissionDepartmentMatches(item, keyword) {
  if (!keyword) return true;
  return [item.name, item.id, item.pinyinInitials, item.departmentPathText]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
    .includes(keyword);
}

function permissionEmployeeMatches(item, keyword) {
  if (!keyword) return true;
  const departmentKeywords = (item.departments || []).flatMap((department) => [
    department.name,
    department.id,
    department.pinyinInitials,
    department.departmentPathText,
  ]);
  return [item.name, item.id, item.pinyinInitials, ...departmentKeywords]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
    .includes(keyword);
}

function filterPermissionDepartmentTree(rows = [], keyword = '') {
  if (!keyword) return rows;
  return rows.map((item) => {
    const children = filterPermissionDepartmentTree(item.children || [], keyword);
    if (permissionDepartmentMatches(item, keyword)) return item;
    return children.length ? { ...item, children } : null;
  }).filter(Boolean);
}

function flattenPermissionPickerDepartments(rows = [], depth = 0, forceOpen = false, output = []) {
  rows.forEach((item) => {
    const hasChildren = Boolean(item.children?.length);
    output.push({
      ...item,
      depth,
      hasChildren,
      expanded: forceOpen || expandedPermissionDepartmentIds.value.has(item.id),
      selected: permissionDepartmentChecked(item.id),
      forced: permissionDepartmentForced(item.id),
      includeSubDepartments: permissionDepartmentIncludesChildren(item.id),
      subtitle: `${permissionDepartmentEmployeeCount(item, true)}人`,
    });
    if (hasChildren && (forceOpen || expandedPermissionDepartmentIds.value.has(item.id))) {
      flattenPermissionPickerDepartments(item.children, depth + 1, forceOpen, output);
    }
  });
  return output;
}

function permissionEmployeeDepartmentIds(employee) {
  return (employee?.departments || []).map((department) => String(department.id || '')).filter(Boolean);
}

function permissionEmployeeDepartmentText(employee) {
  return (employee?.departments || []).map((department) => department.name).filter(Boolean).join(' / ') || '未分配部门';
}

function permissionDepartmentEmployeeCount(department, includeSubDepartments = false) {
  const ids = new Set([
    department?.id,
    ...(includeSubDepartments ? (department?.childIds || []) : []),
  ].map(String));
  return permissionEmployeeRows.value.filter((employee) => (
    permissionEmployeeDepartmentIds(employee).some((departmentId) => ids.has(departmentId))
  )).length;
}

function permissionDepartmentSource(permission, departmentId) {
  return adminPermissionRules.value.find((rule) => (
    rule.permission === permission
    && ['department', 'departmentSub'].includes(rule.scopeType)
    && String(rule.targetId) === String(departmentId)
  ));
}

function permissionDepartmentForced(departmentId) {
  return adminPermissionRules.value.some((rule) => {
    if (rule.permission !== permissionPicker.permission || rule.scopeType !== 'departmentSub') return false;
    return permissionDepartmentById.value.get(String(rule.targetId))?.childIds?.includes(String(departmentId));
  });
}

function permissionDepartmentChecked(departmentId) {
  return Boolean(permissionDepartmentSource(permissionPicker.permission, departmentId) || permissionDepartmentForced(departmentId));
}

function permissionDepartmentIncludesChildren(departmentId) {
  return permissionDepartmentSource(permissionPicker.permission, departmentId)?.scopeType === 'departmentSub';
}

function togglePermissionDepartmentExpanded(row) {
  if (!row?.hasChildren) return;
  const next = new Set(expandedPermissionDepartmentIds.value);
  if (next.has(row.id)) next.delete(row.id);
  else next.add(row.id);
  expandedPermissionDepartmentIds.value = next;
}

function togglePermissionDepartment(row) {
  if (!row?.id || permissionDepartmentForced(row.id)) return;
  const source = permissionDepartmentSource(permissionPicker.permission, row.id);
  if (source) {
    removePermissionRule(source);
    return;
  }
  adminPermissionRules.value.push({
    permission: permissionPicker.permission,
    scopeType: 'department',
    targetId: row.id,
    targetName: row.name,
    sortOrder: rulesForPermission(permissionPicker.permission, 'department').length,
  });
}

function setPermissionDepartmentIncludeChildren(row, checked) {
  if (!row?.id || permissionDepartmentForced(row.id)) return;
  const source = permissionDepartmentSource(permissionPicker.permission, row.id);
  if (source) {
    source.scopeType = checked ? 'departmentSub' : 'department';
  } else if (checked) {
    adminPermissionRules.value.push({
      permission: permissionPicker.permission,
      scopeType: 'departmentSub',
      targetId: row.id,
      targetName: row.name,
      sortOrder: rulesForPermission(permissionPicker.permission, 'department').length,
    });
  } else {
    return;
  }
  if (checked) {
    const descendants = new Set(permissionDepartmentById.value.get(row.id)?.childIds || []);
    adminPermissionRules.value = adminPermissionRules.value.filter((rule) => (
      rule.permission !== permissionPicker.permission
      || !['department', 'departmentSub'].includes(rule.scopeType)
      || String(rule.targetId) === String(row.id)
      || !descendants.has(String(rule.targetId))
    ));
    const next = new Set(expandedPermissionDepartmentIds.value);
    next.add(row.id);
    expandedPermissionDepartmentIds.value = next;
  }
}

function togglePermissionEmployee(row) {
  if (!row?.id) return;
  const directRule = adminPermissionRules.value.find((rule) => (
    rule.permission === permissionPicker.permission
    && rule.scopeType === 'employee'
    && String(rule.targetId) === String(row.id)
  ));
  if (directRule) {
    removePermissionRule(directRule);
    return;
  }
  adminPermissionRules.value = [
    ...adminPermissionRules.value.filter((rule) => !(
      rule.permission === permissionPicker.permission
      && rule.scopeType === 'excludedEmployee'
      && String(rule.targetId) === String(row.id)
    )),
    {
      permission: permissionPicker.permission,
      scopeType: 'employee',
      targetId: row.id,
      targetName: row.name,
      sortOrder: rulesForPermission(permissionPicker.permission, 'employee').length,
    },
  ];
}

function permissionSourceDisplayName(rule) {
  if (['department', 'departmentSub'].includes(rule?.scopeType)) {
    return permissionDepartmentById.value.get(String(rule.targetId))?.name || rule.targetName || rule.targetId;
  }
  return permissionEmployeeById.value.get(String(rule?.targetId))?.name || rule?.targetName || rule?.targetId || '';
}

function permissionDepartmentIdsForSources(permission, items = adminPermissionRules.value) {
  const ids = new Set();
  items.filter((rule) => (
    rule.permission === permission && ['department', 'departmentSub'].includes(rule.scopeType)
  )).forEach((rule) => {
    const department = permissionDepartmentById.value.get(String(rule.targetId));
    ids.add(String(rule.targetId));
    if (rule.scopeType === 'departmentSub') {
      (department?.childIds || []).forEach((id) => ids.add(String(id)));
    }
  });
  return ids;
}

function permissionMemberBaseRows(permission) {
  const departmentIds = permissionDepartmentIdsForSources(permission);
  const directEmployeeIds = new Set(rulesForPermission(permission, 'employee').map((rule) => String(rule.targetId)));
  return permissionEmployeeRows.value.map((employee) => {
    const matchedDepartments = (employee.departments || [])
      .filter((department) => departmentIds.has(String(department.id)))
      .map((department) => department.name)
      .filter(Boolean);
    const includedByDepartment = matchedDepartments.length > 0;
    const includedByEmployee = directEmployeeIds.has(employee.id);
    if (!includedByDepartment && !includedByEmployee) return null;
    return {
      id: employee.id,
      name: employee.name,
      employee,
      departmentText: permissionEmployeeDepartmentText(employee),
      sourceText: [...(includedByEmployee ? ['人员'] : []), ...matchedDepartments].join(' / '),
      includedByDepartment,
      includedByEmployee,
    };
  }).filter(Boolean).sort((left, right) => (
    left.name.localeCompare(right.name, 'zh-Hans-CN') || left.id.localeCompare(right.id)
  ));
}

function permissionDepartmentIncludedEmployeeIds(permission, items = adminPermissionRules.value) {
  const departmentIds = permissionDepartmentIdsForSources(permission, items);
  return new Set(permissionEmployeeRows.value
    .filter((employee) => permissionEmployeeDepartmentIds(employee).some((id) => departmentIds.has(id)))
    .map((employee) => employee.id));
}

function permissionRulesForSave(items = adminPermissionRules.value) {
  const includedByPermission = new Map(permissionGroups.map((permission) => [
    permission.id,
    permissionDepartmentIncludedEmployeeIds(permission.id, items),
  ]));
  return items.filter((rule) => (
    rule.scopeType !== 'excludedEmployee'
    || includedByPermission.get(rule.permission)?.has(String(rule.targetId))
  ));
}

function permissionExcludedEmployeeIds(permission) {
  return new Set(adminPermissionRules.value
    .filter((rule) => rule.permission === permission && rule.scopeType === 'excludedEmployee')
    .map((rule) => String(rule.targetId)));
}

function permissionMemberRows(permission) {
  const excludedIds = permissionExcludedEmployeeIds(permission);
  return permissionMemberBaseRows(permission).filter((row) => !excludedIds.has(row.id));
}

function permissionExcludedMemberRows(permission) {
  const excludedIds = permissionExcludedEmployeeIds(permission);
  return permissionMemberBaseRows(permission).filter((row) => row.includedByDepartment && excludedIds.has(row.id));
}

function excludePermissionMember(row) {
  const permission = activeAdminPermissionId.value;
  adminPermissionRules.value = adminPermissionRules.value.filter((rule) => !(
    rule.permission === permission
    && rule.scopeType === 'employee'
    && String(rule.targetId) === String(row.id)
  ));
  if (row.includedByDepartment && !permissionExcludedEmployeeIds(permission).has(row.id)) {
    adminPermissionRules.value.push({
      permission,
      scopeType: 'excludedEmployee',
      targetId: row.id,
      targetName: row.name,
      sortOrder: 0,
    });
  }
}

function restorePermissionMember(row) {
  adminPermissionRules.value = adminPermissionRules.value.filter((rule) => !(
    rule.permission === activeAdminPermissionId.value
    && rule.scopeType === 'excludedEmployee'
    && String(rule.targetId) === String(row.id)
  ));
}

function serializeAdminPermissionRules(items = adminPermissionRules.value) {
  return JSON.stringify(permissionRulesForSave(items || []).map((rule) => ({
    permission: rule.permission,
    scopeType: rule.scopeType,
    targetId: String(rule.targetId),
    targetName: rule.targetName || '',
  })).sort((left, right) => (
    `${left.permission}:${left.scopeType}:${left.targetId}`.localeCompare(`${right.permission}:${right.scopeType}:${right.targetId}`)
  )));
}

function selectAdminPermission(permissionId) {
  if (!permissionGroups.some((item) => item.id === permissionId)) return;
  activeAdminPermissionId.value = permissionId;
  closePermissionPicker();
}

function openPermissionPicker(permission, scopeType) {
  if (scopeType === 'role') return;
  permissionPicker.open = true;
  permissionPicker.permission = permission;
  permissionPicker.scopeType = scopeType;
  permissionPicker.keyword = '';
  if (scopeType === 'department') {
    const next = new Set(permissionDepartmentTree.value.map((item) => item.id));
    rulesForPermission(permission, 'department').forEach((rule) => {
      let current = permissionDepartmentById.value.get(String(rule.targetId));
      while (current?.parentId) {
        next.add(current.parentId);
        current = permissionDepartmentById.value.get(current.parentId);
      }
      if (rule.scopeType === 'departmentSub') next.add(String(rule.targetId));
    });
    expandedPermissionDepartmentIds.value = next;
  }
  nextTick(() => permissionPickerInput.value?.focus?.());
}

function closePermissionPicker() {
  permissionPicker.open = false;
  permissionPicker.keyword = '';
}

function handlePermissionPickerKeydown(event) {
  if (event.key === 'Escape') {
    closePermissionPicker();
    return;
  }
  if (event.key !== 'Enter' || !permissionPickerRows.value.length) return;
  event.preventDefault();
  const first = permissionPickerRows.value[0];
  if (permissionPicker.scopeType === 'department') togglePermissionDepartment(first);
  else togglePermissionEmployee(first);
}

function removePermissionRule(rule) {
  const key = permissionRuleKey(rule.permission, rule.scopeType, rule.targetId);
  adminPermissionRules.value = adminPermissionRules.value.filter((item) => permissionRuleKey(item.permission, item.scopeType, item.targetId) !== key);
}

async function loadCurrentCableMallPermission() {
  if (props.externalMode) {
    try {
      const data = await request('/me/');
      if (data.account && props.externalSession) {
        props.externalSession.account = data.account;
      }
    } catch (err) {
      // request() handles invalid external sessions by emitting logout.
      throw err;
    }
    cableMallPermission.value = {
      canAccessCableMall: true,
      canManageCableMall: false,
      permission: 'external',
      permissionLabel: '线材商城外部用户',
      rulesConfigured: true,
    };
    return;
  }
  const data = await apiGet('/api/cable-mall/permissions/current');
  cableMallPermission.value = {
    permission: data.permission || '',
    permissionLabel: data.permissionLabel || '',
    canAccessCableMall: Boolean(data.canAccessCableMall),
    canManageCableMall: Boolean(data.canManageCableMall),
    rulesConfigured: Boolean(data.rulesConfigured),
  };
  if (!cableMallPermission.value.canManageCableMall && activeTab.value === 'admin-settings') {
    activeTab.value = 'products';
  }
  return data;
}

async function loadAdminPermissionData() {
  if (!cableMallPermission.value.canManageCableMall) return;
  adminPermissionLoading.value = true;
  adminPermissionError.value = '';
  try {
    const [directory, rules] = await Promise.all([
      apiGet('/api/cable-mall/permissions/directory'),
      apiGet('/api/cable-mall/permissions'),
    ]);
    permissionDirectory.departments = directory.departments || [];
    permissionDirectory.roles = [];
    permissionDirectory.employees = directory.employees || [];
    adminPermissionOrgRevision.value = String(directory.orgRevision ?? '');
    adminPermissionRevision.value = String(rules.revision || '');
    adminPermissionRules.value = (rules.items || [])
      .map(normalizePermissionRule)
      .filter((item) => item.scopeType !== 'role');
    adminPermissionInitialRules.value = adminPermissionRules.value.map((rule) => ({ ...rule }));
    adminPermissionSnapshot.value = serializeAdminPermissionRules(adminPermissionRules.value);
    expandedPermissionDepartmentIds.value = new Set(
      permissionDepartmentTree.value.map((department) => department.id),
    );
    return true;
  } catch (err) {
    adminPermissionError.value = err instanceof Error ? err.message : '线材权限加载失败';
    return false;
  } finally {
    adminPermissionLoading.value = false;
  }
}

async function saveAdminPermissionRules() {
  adminPermissionSaving.value = true;
  adminPermissionError.value = '';
  adminPermissionNotice.value = '';
  try {
    const data = await apiPost('/api/cable-mall/permissions', {
      revision: adminPermissionRevision.value,
      orgRevision: adminPermissionOrgRevision.value,
      items: permissionRulesForSave(adminPermissionRules.value)
        .filter((item) => item.scopeType !== 'role')
        .map((item, index) => ({
        permission: item.permission,
        scopeType: item.scopeType,
        targetId: item.targetId,
        targetName: item.targetName,
        sortOrder: index,
      })),
    });
    adminPermissionRules.value = (data.items || []).map(normalizePermissionRule);
    adminPermissionInitialRules.value = adminPermissionRules.value.map((rule) => ({ ...rule }));
    adminPermissionSnapshot.value = serializeAdminPermissionRules(adminPermissionRules.value);
    adminPermissionRevision.value = String(data.revision || '');
    adminPermissionOrgRevision.value = String(data.orgRevision ?? adminPermissionOrgRevision.value);
    adminPermissionNotice.value = '线材权限已保存';
    await loadCurrentCableMallPermission();
  } catch (err) {
    const message = err instanceof Error ? err.message : '线材权限保存失败';
    if (err?.status === 409) {
      const reloaded = await loadAdminPermissionData();
      const reloadError = adminPermissionError.value;
      adminPermissionError.value = reloaded
        ? `${message}；已加载最新配置，请重新确认后保存`
        : `${message}；自动刷新失败：${reloadError || '请点击刷新后重试'}`;
    } else {
      adminPermissionError.value = message;
    }
  } finally {
    adminPermissionSaving.value = false;
  }
}

async function bootstrapModule() {
  loginSession.value = props.externalMode ? {} : (loadLoginSession() || {});
  permissionLoading.value = !props.externalMode;
  permissionError.value = '';
  try {
    await loadCurrentCableMallPermission();
    if (!cableMallPermission.value.canAccessCableMall) return;
    await bootstrap();
    if (cableMallPermission.value.canManageCableMall) {
      loadAdminPermissionData();
    }
  } catch (err) {
    permissionError.value = err instanceof Error ? err.message : '线材商城加载失败';
  } finally {
    moduleBootstrapped.value = true;
    permissionLoading.value = false;
  }
}

async function bootstrap() {
  await run(async () => {
    await loadPackages();
    if (props.externalMode) {
      await Promise.all([loadProducts(false), loadProductCart(), loadDrawerProducts(), loadProjects(), loadCustomRequests(), loadOrders(), loadShippingAddresses(), loadSigningInfos()]);
    } else {
      await Promise.all([loadProducts(false), loadProductCart(), loadDrawerProducts(), loadProjects(), loadCustomRequests(), loadOrders(), loadExternalAccounts()]);
      await ensureDemoData();
    }
  });
}

onMounted(async () => {
  document.addEventListener('keydown', handleKeydown);
  window.addEventListener('resize', refreshCustomBottomScroll);
  await bootstrapModule();
});

onBeforeUnmount(() => {
  document.removeEventListener('keydown', handleKeydown);
  window.removeEventListener('resize', refreshCustomBottomScroll);
  hideParameterTooltip();
  window.clearTimeout(productSearchTimer);
  window.clearTimeout(addCableSearchTimer);
  window.clearTimeout(productCartSaveTimer);
  window.clearTimeout(messageFadeTimer);
  window.clearTimeout(messageClearTimer);
});



watch(activeTab, (value, oldValue) => {
  hideParameterTooltip();
  if (value === 'registration' || oldValue === 'registration') clearSettingsFeedback();
  if (value === 'admin-settings') loadAdminPermissionData();
  if (value === 'products' && oldValue && oldValue !== 'products') {
    productPagination.page = 1;
    loadProducts(false);
  }
  if (value === 'custom') refreshCustomBottomScroll();
});

watch(filteredCustomRequests, () => {
  if (activeTab.value === 'custom') refreshCustomBottomScroll();
}, { flush: 'post' });

</script>

<template>
  <main class="cable-mall-shell app-shell">
    <div v-if="permissionLoading && !moduleBootstrapped" class="cable-mall-state">正在校验线材商城权限...</div>
    <div v-else-if="permissionError || !cableMallPermission.canAccessCableMall" class="cable-mall-state">
      <h2>暂无线材商城访问权限</h2>
      <p>{{ permissionError || '请联系线材商城管理员启用权限。' }}</p>
      <button v-if="isExternalMode" class="state-back-button" type="button" @click="requestExternalLogout">
        <ArrowLeft :size="16" />
        退出登录
      </button>
    </div>

    <div v-else class="app-layout" :class="{ 'module-loading-soft': !moduleBootstrapped }">
      <PlatformSidebar
        module-title="智慧教室线材商城"
        :module-icon="FolderKanban"
        :sections="platformSidebarSections"
        :active-item-id="activeTab"
        :footer-label="isExternalMode ? '退出登录' : ''"
        @item-click="switchActiveTab($event.key || $event.id)"
        @footer-click="requestExternalLogout"
      />

      <section class="content-region">
        <div v-if="unsavedConfirm.open" class="unsaved-top-mask" v-backdrop-dismiss="closeUnsavedConfirm">
          <section class="unsaved-top-confirm" @click.stop>
            <div>
              <h3>{{ unsavedConfirm.title }}</h3>
              <p>{{ unsavedConfirm.message }}</p>
            </div>
            <div class="unsaved-top-actions">
              <button class="unsaved-continue-button" type="button" @click="closeUnsavedConfirm">{{ unsavedConfirm.cancelText }}</button>
              <button
                class="unsaved-discard-button"
                :class="unsavedConfirm.confirmClass"
                type="button"
                @click="confirmDiscardChanges"
              >
                {{ unsavedConfirm.confirmText }}
              </button>
            </div>
          </section>
        </div>
        <div
          v-if="!['products', 'projects', 'custom', 'suggestions'].includes(activeTab)"
          class="content-header"
          :class="{
            'settings-header': activeTab === 'registration' || activeTab === 'admin-settings',
            'orders-header': activeTab === 'orders',
          }"
        >
          <div>
            <h2>{{ activeTabMeta?.pageTitle || activeTabMeta?.label }}</h2>
          </div>
        </div>
        <div v-if="notice || error" class="message-toast" :class="{ leaving: messageLeaving }">
          <div class="message" :class="notice ? 'notice' : 'error'">
            {{ notice || error }}
          </div>
        </div>

    <section v-if="activeTab === 'suggestions' && !isExternalMode" class="platform-suggestions-page"><PlatformSoftwareSuggestions ref="suggestionsRef" app-id="cable-mall" :api-get="apiGet" :api-post="apiPost" :api-patch="apiPatch" :api-upload="apiUpload" :api-delete="apiDelete" :suspended="suggestionsConfirmOpen" @dirty-change="suggestionsDirty=$event" @busy-change="suggestionsBusy=$event" @request-leave="requestSuggestionsAction($event)" /></section>
    <section v-show="activeTab === 'products'" class="product-table-page">
      <section class="main-panel">
        <div class="product-filter-panel product-catalog-filter-panel">
          <div class="category-filter-tabs">
            <div class="category-filter-row">
              <span>搜索</span>
              <div class="search-box category-search-box">
                <Search :size="18" />
                <input
                  v-model="filters.q"
                  placeholder="搜索产品"
                  @input="scheduleProductSearch"
                  @keyup.enter="reloadProductsFromFirstPage(false)"
                />
              </div>
            </div>
            <div class="category-filter-row">
              <span>一级分类</span>
              <div class="category-filter-pills">
                <button
                  v-for="category in categoriesA"
                  :key="category"
                  type="button"
                  :class="{ active: filters.category_a === category }"
                  @click="selectCategoryA(category)"
                >
                  {{ category }}
                </button>
              </div>
            </div>
            <div class="category-filter-row">
              <span>二级分类</span>
              <div class="category-filter-pills">
                <button
                  v-for="category in categoriesB"
                  :key="category"
                  type="button"
                  :class="{ active: filters.category_b === category }"
                  @click="selectCategoryB(category)"
                >
                  {{ category }}
                </button>
              </div>
            </div>
          </div>
          <aside class="product-cart-panel">
            <div class="product-cart-icon">
              <ShoppingCart :size="20" />
            </div>
            <div class="product-cart-current">
              <span>已选：</span>
              <strong>{{ productCartSummary.count }}</strong>
            </div>
            <div class="product-cart-actions">
              <button class="product-cart-detail-button" type="button" :disabled="!productCartItems.length" @click="openProductCartDetail">
                详情
              </button>
              <button class="product-cart-order-button" type="button" :disabled="!productCartItems.length" @click="openProductCartOrder">
                去下单
              </button>
            </div>
          </aside>
        </div>

        <div class="table-shell">
          <table class="product-catalog-table product-main-catalog-table">
            <thead>
              <tr>
                <th>序号</th>
                <th>产品图片</th>
                <th>产品简称</th>
                <th>方案参数</th>
                <th>A1价格</th>
                <th>业务员价格</th>
                <th>单位</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(product, index) in products" :key="product.id">
                <td class="row-index">{{ (productPagination.page - 1) * productPagination.page_size + index + 1 }}</td>
                <td>
                  <button
                    v-if="productImageUrl(product)"
                    class="product-thumb-button"
                    type="button"
                    title="查看大图"
                    @click="openImagePreview(product)"
                  >
                    <img
                      class="product-thumb"
                      :src="productImageUrl(product)"
                      loading="lazy"
                      decoding="async"
                      alt="产品图片"
                      @error="$event.target.style.display = 'none'"
                    />
                  </button>
                  <span v-else class="muted">暂无</span>
                </td>
                <td>
                  <strong>{{ product.abbr || product.label || '-' }}</strong>
                </td>
                <td>
                  <span
                    class="param-cell product-param-cell"
                    :class="{ 'has-param': productParameterText(product) }"
                    @mouseenter="showParameterTooltip(product, $event)"
                    @mousemove="moveParameterTooltip"
                    @mouseleave="hideParameterTooltip"
                  >
                    {{ productParameterText(product) || '-' }}
                  </span>
                </td>
                <td>{{ product.unit_price }}</td>
                <td>{{ product.salesperson_price }}</td>
                <td>{{ productUnit(product) }}</td>
                <td class="center-cell">
                  <div class="product-cart-row-action">
                    <span v-if="productCartQuantity(product)" class="product-cart-row-quantity">
                      【{{ productCartQuantity(product) }}】
                    </span>
                    <button
                      class="product-row-cart-button"
                      :class="{ added: productCartQuantity(product) }"
                      type="button"
                      @click="openProductCartModal(product)"
                    >
                      {{ productCartQuantity(product) ? '修改' : '加入购物车' }}
                    </button>
                  </div>
                </td>
              </tr>
              <tr v-if="products.length === 0">
                <td class="empty-cell" colspan="8">暂无产品</td>
              </tr>
              <tr class="product-custom-table-row">
                <td colspan="8">
                  <button
                    class="add-cable-custom-link product-footer-custom-link flashing"
                    type="button"
                    @click="goCustomFromProductCatalog"
                  >
                    没有线材，去定制
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </section>

    <section v-show="activeTab === 'projects'" class="project-page" :class="{ 'project-detail-page': projectView !== 'list' }">
      <template v-if="projectView === 'list'">
        <div class="project-list-toolbar">
          <div class="package-search-box project-search-box">
            <Search :size="18" />
            <input v-model="projectSearch" placeholder="搜索项目" />
          </div>
          <button class="project-recycle-toggle" type="button" @click="openRecycleDrawer">
            进入回收站
          </button>
          <button class="primary project-create-toggle" type="button" @click="openProjectCreateModal">
            <Plus :size="17" />
            新增项目
          </button>
        </div>

        <div class="table-shell project-list-table-shell">
          <table class="project-list-table">
            <thead>
              <tr>
                <th>序号</th>
                <th>项目名称</th>
                <th>项目备注</th>
                <th>总价</th>
                <th>创建人</th>
                <th>创建日期</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(item, index) in filteredProjects"
                :key="item.id"
                class="clickable-row"
                tabindex="0"
                @click="enterProjectDetail(item)"
                @keydown.enter.prevent="enterProjectDetail(item)"
              >
                <td class="row-index">{{ index + 1 }}</td>
                <td><strong>{{ item.name }}</strong></td>
                <td class="project-note-cell">{{ item.note || '-' }}</td>
                <td class="package-table-price">￥{{ projectAmount(item) }}</td>
                <td class="center-cell">{{ item.created_by || accountName }}</td>
                <td class="center-cell">{{ formatProjectDate(item.created_at) }}</td>
                <td class="center-cell">
                  <div class="project-row-actions">
                    <button class="text-action" type="button" @click.stop="enterProjectDetail(item)">详情</button>
                    <button class="text-action order-text" type="button" @click.stop="openProjectOrder(item)">去下单</button>
                  </div>
                </td>
              </tr>
              <tr v-if="filteredProjects.length === 0">
                <td class="empty-cell" colspan="7">暂无项目</td>
              </tr>
            </tbody>
          </table>
        </div>

</template>

      <template v-else-if="selectedProject">
        <div class="project-detail-topbar">
          <div class="project-detail-header">
            <div class="project-title-line">
              <div class="project-title-main">
                <button class="project-back-icon" type="button" title="返回项目列表" @click="backToProjectList">&lt;</button>
                <h2>{{ selectedProject.name }}</h2>
              </div>
              <button
                class="project-detail-order-button"
                type="button"
                @click="openProjectOrder(selectedProject)"
              >
                <ShoppingCart :size="16" />
                去下单
              </button>
            </div>
          </div>

          <nav class="project-detail-tabs">
            <button type="button" :class="{ active: projectDetailTab === 'info' }" @click="projectDetailTab = 'info'">项目信息</button>
            <button type="button" :class="{ active: projectDetailTab === 'stats' }" @click="projectDetailTab = 'stats'">项目统计</button>
            <button type="button" :class="{ active: projectDetailTab === 'packages' }" @click="projectDetailTab = 'packages'">按教室添加线材</button>
          </nav>
        </div>

        <section v-if="projectDetailTab === 'info'" class="project-info-tab">
          <label class="field project-info-field">
            <span>项目名称</span>
            <input v-model="projectInfoForm.name" placeholder="请输入项目名称" />
          </label>
          <label class="field project-info-field project-info-field-wide">
            <span>项目备注</span>
            <textarea v-model="projectInfoForm.note" rows="3" placeholder="请输入项目备注"></textarea>
          </label>
          <div class="project-info-actions">
            <button class="primary" type="button" @click="saveProjectInfo">保存修改</button>
            <button class="project-info-delete-button" type="button" @click="startDeleteProject(selectedProject)">删除项目</button>
          </div>
        </section>

        <section v-if="projectDetailTab === 'stats'" class="project-stats-tab">
          <div class="product-filter-panel project-stats-filter-panel">
            <div class="category-filter-tabs">
              <div class="category-filter-row">
                <span>搜索</span>
                <div class="search-box category-search-box">
                  <Search :size="18" />
                  <input v-model="projectStatsFilters.q" placeholder="搜索产品" />
                </div>
              </div>
              <div class="category-filter-row">
                <span>一级分类</span>
                <div class="category-filter-pills">
                  <button type="button" :class="{ active: projectStatsFilters.category_a === '' }" @click="selectProjectStatsCategoryA('')">全部</button>
                  <button
                    v-for="category in projectStatsCategoriesA"
                    :key="category"
                    type="button"
                    :class="{ active: projectStatsFilters.category_a === category }"
                    @click="selectProjectStatsCategoryA(category)"
                  >
                    {{ category }}
                  </button>
                </div>
              </div>
              <div class="category-filter-row">
                <span>二级分类</span>
                <div class="category-filter-pills">
                  <button type="button" :class="{ active: projectStatsFilters.category_b === '' }" @click="selectProjectStatsCategoryB('')">全部</button>
                  <button
                    v-for="category in projectStatsCategoriesB"
                    :key="category"
                    type="button"
                    :class="{ active: projectStatsFilters.category_b === category }"
                    @click="selectProjectStatsCategoryB(category)"
                  >
                    {{ category }}
                  </button>
                </div>
              </div>
            </div>
            <div class="project-stats-summary">
              <div class="project-stats-summary-item">
                <span>总数量</span>
                <strong>{{ filteredProjectStatsSummary.quantity }}</strong>
              </div>
              <div class="project-stats-summary-item amount">
                <span>总金额</span>
                <strong>￥{{ filteredProjectStatsSummary.amount }}</strong>
              </div>
            </div>
          </div>

          <div class="table-shell project-stats-table-shell">
            <table class="product-catalog-table project-stats-table">
              <thead>
                <tr>
                  <th class="stats-col-category-a">一级分类</th>
                  <th class="stats-col-category-b">二级分类</th>
                  <th class="stats-col-index">序号</th>
                  <th class="stats-col-image">产品图片</th>
                  <th class="stats-col-name">产品简称</th>
                  <th class="stats-col-model">产品型号</th>
                  <th class="stats-col-price">A1价格</th>
                  <th class="stats-col-quantity">数量</th>
                  <th class="stats-col-amount">金额</th>
                  <th class="stats-col-param">方案参数</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="entry in groupedProjectStatsRows" :key="entry.row.key">
                  <td
                    v-if="entry.categoryARowspan"
                    class="drawer-category-cell stats-col-category-a"
                    :rowspan="entry.categoryARowspan"
                  >
                    {{ entry.categoryA }}
                  </td>
                  <td
                    v-if="entry.categoryBRowspan"
                    class="drawer-category-cell secondary stats-col-category-b"
                    :rowspan="entry.categoryBRowspan"
                  >
                    {{ entry.categoryB }}
                  </td>
                  <td class="row-index stats-col-index">{{ entry.index }}</td>
                  <td class="stats-col-image">
                    <span class="muted">暂无</span>
                  </td>
                  <td class="stats-col-name">
                    <strong>{{ entry.row.product_abbr || entry.row.product_label || '-' }}</strong>
                  </td>
                  <td class="stats-col-model">{{ entry.row.product_model || '-' }}</td>
                  <td class="stats-col-price">{{ entry.row.unit_price }}</td>
                  <td class="center-cell stats-col-quantity">{{ entry.row.quantity }}</td>
                  <td class="package-table-price stats-col-amount">￥{{ entry.row.amount_text }}</td>
                  <td class="stats-col-param">
                    <span class="param-cell">{{ entry.row.plan_para || '-' }}</span>
                  </td>
                </tr>
                <tr v-if="groupedProjectStatsRows.length === 0">
                  <td class="empty-cell" colspan="10">暂无统计数据</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section v-if="projectDetailTab === 'packages'" class="project-packages-tab">
          <div class="classroom-create-bar">
            <label>
              <span>搜索</span>
              <input v-model="classroomForm.name" placeholder="搜索教室类别" />
            </label>
            <button class="primary classroom-create-button" type="button" @click="openClassroomCreateModal">新增教室类别</button>
            <div class="project-stats-summary classroom-summary">
              <div class="project-stats-summary-item">
                <span>单间金额</span>
                <strong>￥{{ filteredProjectClassroomSummary.packageAmount }}</strong>
              </div>
              <div class="project-stats-summary-item amount">
                <span>总价</span>
                <strong>￥{{ filteredProjectClassroomSummary.grandAmount }}</strong>
              </div>
            </div>
          </div>

          <div class="project-classroom-table-shell">
            <table class="project-classroom-table">
              <colgroup>
                <col class="project-classroom-col-index" />
                <col class="project-classroom-col-name" />
                <col class="project-classroom-col-type" />
                <col class="project-classroom-col-kind" />
                <col class="project-classroom-col-cable" />
                <col class="project-classroom-col-room" />
                <col class="project-classroom-col-price" />
                <col class="project-classroom-col-total" />
                <col class="project-classroom-col-action" />
              </colgroup>
              <thead>
                <tr>
                  <th>序号</th>
                  <th>教室类别</th>
                  <th>类型</th>
                  <th>线材种类</th>
                  <th>线材数量</th>
                  <th>教室间数</th>
                  <th>单间金额</th>
                  <th>总价</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <template v-for="(classroom, classroomIndex) in filteredProjectClassrooms" :key="classroom.name">
                  <tr
                    v-for="(scopeRow, scopeIndex) in classroomScopeRows(classroom)"
                    :key="`${classroom.name}-${scopeRow.key}`"
                    class="clickable-row project-classroom-row"
                    tabindex="0"
                    @click="openProjectClassroomScopeDetail(classroom, scopeRow, $event)"
                    @keydown.enter.prevent="openProjectClassroomScopeDetail(classroom, scopeRow)"
                  >
                    <td v-if="scopeIndex === 0" class="row-index project-classroom-merged-cell" rowspan="2">
                      {{ classroomIndex + 1 }}
                    </td>
                    <td v-if="scopeIndex === 0" class="project-classroom-name project-classroom-merged-cell" rowspan="2">
                      <strong>{{ classroom.name }}</strong>
                    </td>
                    <td class="center-cell project-classroom-type">{{ scopeRow.label }}</td>
                    <td class="center-cell">{{ classroomScopeKindCount(scopeRow) }}</td>
                    <td class="center-cell">{{ classroomScopeCableCount(scopeRow) }}</td>
                    <td v-if="scopeIndex === 0" class="center-cell project-classroom-merged-cell" rowspan="2">
                      <input
                        :value="classroomRoomCount(classroom)"
                        class="qty"
                        type="number"
                        min="1"
                        step="1"
                        @change="updateProjectClassroomRoomCount(classroom, $event.target.value)"
                        @click.stop
                      />
                    </td>
                    <td v-if="scopeIndex === 0" class="package-table-price project-classroom-merged-cell" rowspan="2">
                      ￥{{ classroomTotalAmount(classroom) }}
                    </td>
                    <td v-if="scopeIndex === 0" class="package-table-price project-classroom-merged-cell" rowspan="2">
                      ￥{{ classroomGrandAmount(classroom) }}
                    </td>
                    <td v-if="scopeIndex === 0" class="project-classroom-merged-cell" rowspan="2">
                      <div class="package-table-actions">
                        <button class="text-action" type="button" :disabled="!classroomIndoorPackage(classroom)" @click.stop="openProjectPackageDetail(classroomIndoorPackage(classroom))">详情</button>
                      </div>
                    </td>
                  </tr>
                </template>
                <tr v-if="filteredProjectClassrooms.length === 0">
                  <td class="empty-cell" colspan="9">暂无教室类别</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </template>

      <div v-else class="project-empty-state">项目不存在或已被删除</div>
    </section>

    <div v-if="deletingProjectId" class="project-delete-confirm-mask" v-backdrop-dismiss="cancelDeleteProject">
      <section class="project-delete-confirm" @click.stop>
        <h3>确认删除</h3>
        <p>删除后项目会进入回收站，可以在回收站中恢复。</p>
        <div class="project-delete-name">
          {{ activeProjects.find((item) => item.id === deletingProjectId)?.name || '当前项目' }}
        </div>
        <div class="project-delete-actions">
          <button class="danger-inline-button" type="button" @click="confirmDeleteProject(activeProjects.find((item) => item.id === deletingProjectId))">确认删除</button>
          <button type="button" @click="cancelDeleteProject">取消</button>
        </div>
      </section>
    </div>

    <div v-if="recycleDrawerOpen" class="recycle-drawer-mask" v-backdrop-dismiss="closeRecycleDrawer">
      <aside class="recycle-drawer" @click.stop>
        <header class="recycle-drawer-head">
          <div>
            <h2>项目回收站</h2>
            <p>已删除项目仅作查看</p>
          </div>
          <button class="drawer-close" type="button" title="关闭" @click="closeRecycleDrawer">
            <X :size="18" />
          </button>
        </header>
        <div class="recycle-drawer-toolbar">
          <div class="package-search-box recycle-search-box">
            <Search :size="18" />
            <input v-model="recycleSearch" placeholder="搜索项目" />
          </div>
        </div>
        <div class="table-shell recycle-table-shell">
          <table class="recycle-table">
            <thead>
              <tr>
                <th>序号</th>
                <th>项目名称</th>
                <th>项目备注</th>
                <th>创建人</th>
                <th>创建日期</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(item, index) in filteredArchivedProjects" :key="item.id">
                <td class="row-index">{{ index + 1 }}</td>
                <td><strong>{{ item.name }}</strong></td>
                <td class="project-note-cell">{{ item.note || '-' }}</td>
                <td class="center-cell">{{ item.created_by || '系统' }}</td>
                <td class="center-cell">{{ formatProjectDate(item.created_at) }}</td>
                <td class="center-cell">
                  <button class="text-action restore-action" type="button" @click="restoreProject(item)">恢复</button>
                </td>
              </tr>
              <tr v-if="filteredArchivedProjects.length === 0">
                <td class="empty-cell" colspan="6">{{ recycleSearch.trim() ? '没有匹配的项目' : '回收站暂无项目' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </aside>
    </div>

    <div v-if="detailPackage" class="drawer-mask" v-backdrop-dismiss="closePackageDetail">
      <aside class="package-detail-drawer" @click.stop>
        <header class="drawer-header">
          <div class="drawer-title-block">
            <h2>线材清单编辑</h2>
          </div>
          <div class="drawer-header-right">
            <div class="drawer-summary">
              <div class="drawer-summary-item primary">
                <span>总合计</span>
                <strong>￥{{ detailClassroomSummary.amount }}</strong>
              </div>
              <div class="drawer-summary-item">
                <span>线种类</span>
                <strong>{{ detailClassroomSummary.kindCount }}</strong>
              </div>
              <div class="drawer-summary-item">
                <span>线数量</span>
                <strong>{{ detailClassroomSummary.cableCount }}</strong>
              </div>
            </div>
            <button class="drawer-close" type="button" title="关闭" @click="closePackageDetail">
              <X :size="18" />
            </button>
          </div>
        </header>

        <nav v-if="detailScopeTabs.length" class="drawer-scope-tabs" aria-label="线材区域">
          <button
            v-for="scope in detailScopeTabs"
            :key="scope.key"
            type="button"
            :class="{ active: detailPackage.classroom_scope === scope.key }"
            :disabled="!scope.package || busy"
            @click="switchDetailScope(scope.key)"
          >
            {{ scope.label }}
          </button>
        </nav>

        <section class="drawer-section">
          <div class="drawer-package-form">
            <label>
              <span>清单名称</span>
              <input
                v-model="packageDetailForm.name"
                placeholder="请输入清单名称"
                @keyup.enter="savePackageDetailDraft"
              />
            </label>
            <label>
              <span>备注</span>
              <input
                v-model="packageDetailForm.note"
                placeholder="请输入备注"
                @keyup.enter="savePackageDetailDraft"
              />
            </label>
          </div>
          <div class="drawer-section-head">
            <h3>产品明细</h3>
            <div class="drawer-section-actions">
              <button
                class="add-cable-custom-link product-footer-custom-link flashing"
                type="button"
                @click="goCustomFromAddCable"
              >
                没有线材，去定制
              </button>
              <button class="text-action add-cable-button" type="button" @click="openAddCableModal">新增线材</button>
            </div>
          </div>
          <div class="drawer-table-shell">
            <table class="drawer-detail-table">
              <colgroup>
                <col class="drawer-col-category-a" />
                <col class="drawer-col-category-b" />
                <col class="drawer-col-index" />
                <col class="drawer-col-name" />
                <col class="drawer-col-model" />
                <col class="drawer-col-price" />
                <col class="drawer-col-qty" />
                <col class="drawer-col-total" />
                <col class="drawer-col-action" />
              </colgroup>
              <thead>
                <tr>
                  <th>一级分类</th>
                  <th>二级分类</th>
                  <th>序号</th>
                  <th>产品简称</th>
                  <th>产品型号</th>
                  <th>单价</th>
                  <th>
                    <span class="drawer-total-head">
                      <span>数量</span>
                      <strong>{{ detailPackageCableCount }}</strong>
                    </span>
                  </th>
                  <th>
                    <span class="drawer-total-head">
                      <span>小计</span>
                      <strong>￥{{ detailPackageAmount }}</strong>
                    </span>
                  </th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="entry in detailGroupedRows"
                  :key="detailRowKey(entry.row)"
                  @click="handleDetailProductRowClick(entry.row, $event)"
                >
                  <td v-if="entry.categoryARowspan" class="drawer-category-cell" :rowspan="entry.categoryARowspan">
                    {{ entry.categoryA }}
                  </td>
                  <td v-if="entry.categoryBRowspan" class="drawer-category-cell secondary" :rowspan="entry.categoryBRowspan">
                    {{ entry.categoryB }}
                  </td>
                  <td class="row-index">{{ entry.index }}</td>
                  <td class="drawer-text-cell">
                    <strong>{{ detailRowProduct(entry.row).abbr || detailRowProduct(entry.row).product_abbr || detailRowProduct(entry.row).label || detailRowProduct(entry.row).product_label || '-' }}</strong>
                  </td>
                  <td class="drawer-text-cell">{{ detailRowProduct(entry.row).product_model || '-' }}</td>
                  <td class="drawer-price-cell">{{ entry.row.unit_price || '0.00' }}</td>
                  <td class="drawer-qty-cell">
                    <input
                      :ref="(el) => setDetailQuantityInputRef(detailRowKey(entry.row), el)"
                      :value="detailRowQuantityDisplay(entry.row)"
                      class="drawer-qty"
                      type="number"
                      min="1"
                      step="1"
                      @focus="handleDetailQuantityFocus(entry.row)"
                      @input="setDetailRowQuantity(entry.row, $event.target.value)"
                      @change="updateDetailRowQuantity(entry.row, $event.target.value)"
                    />
                  </td>
                  <td class="package-table-price">￥{{ detailRowLineAmount(entry.row) }}</td>
                  <td>
                    <div class="drawer-row-actions">
                      <template v-if="deletingDetailRowKey === detailRowKey(entry.row)">
                        <button class="text-action danger-text" type="button" @click.stop="confirmDeleteDetailRow(entry.row)">确认删除</button>
                        <button class="text-action muted-action" type="button" @click.stop="cancelDeleteDetailRow">取消</button>
                      </template>
                      <template v-else>
                        <button class="text-action danger-text" type="button" @click.stop="startDeleteDetailRow(entry.row)">删除</button>
                      </template>
                    </div>
                  </td>
                </tr>
                <tr v-if="!detailGroupedRows.length">
                  <td class="empty-cell" colspan="9">暂无已选线材</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
        <footer class="drawer-footer">
          <button
            class="primary drawer-save-button"
            type="button"
            :disabled="!detailHasUnsavedChanges"
            @click="savePackageDetailDraft"
          >
            保存
          </button>
          <button
            v-if="detailIsClassroomPackage"
            class="drawer-delete-button"
            type="button"
            @click="startClassroomDelete"
          >
            删除教室
          </button>
          <button
            v-else
            class="drawer-delete-button"
            type="button"
            @click="startPackageDelete(detailPackage)"
          >
            删除
          </button>
        </footer>
      </aside>
    </div>

    <div v-if="deletingClassroom" class="project-delete-confirm-mask" v-backdrop-dismiss="cancelClassroomDelete">
      <section class="project-delete-confirm" @click.stop>
        <h3>确认删除教室</h3>
        <p>删除后该教室的讲桌内、讲桌外线材清单会进入回收站。</p>
        <div class="project-delete-name">
          {{ deletingClassroom.classroomName || '当前教室' }}
        </div>
        <div class="project-delete-actions">
          <button class="danger-inline-button" type="button" @click="archiveClassroom">确认删除</button>
          <button type="button" @click="cancelClassroomDelete">取消</button>
        </div>
      </section>
    </div>

    <div v-if="addCableModalOpen" class="add-cable-modal-mask" v-backdrop-dismiss="closeAddCableModal">
      <section class="add-cable-modal" @click.stop>
        <button class="add-cable-modal-close" type="button" title="关闭" @click="closeAddCableModal">
          <X :size="18" />
        </button>

        <div class="add-cable-filter-panel">
          <div class="add-cable-filter-tabs">
            <div class="add-cable-filter-row">
              <span>搜索</span>
              <div class="search-box add-cable-search-box">
                <Search :size="18" />
                <input
                  v-model="addCableFilters.q"
                  placeholder="搜索产品"
                  @input="scheduleAddCableSearch"
                  @keyup.enter="loadAddCableProducts(false)"
                />
              </div>
            </div>
            <div class="add-cable-filter-row">
              <span>一级分类</span>
              <div class="category-filter-pills">
                <button
                  v-for="category in addCableCategoriesA"
                  :key="category"
                  type="button"
                  :class="{ active: addCableFilters.category_a === category }"
                  @click="selectAddCableCategoryA(category)"
                >
                  {{ category }}
                </button>
              </div>
            </div>
            <div class="add-cable-filter-row">
              <span>二级分类</span>
              <div class="category-filter-pills">
                <button
                  v-for="category in addCableCategoriesB"
                  :key="category"
                  type="button"
                  :class="{ active: addCableFilters.category_b === category }"
                  @click="selectAddCableCategoryB(category)"
                >
                  {{ category }}
                </button>
              </div>
            </div>
          </div>
        </div>

        <div class="add-cable-table-shell">
          <table class="add-cable-product-table">
            <thead>
              <tr>
                <th>序号</th>
                <th>产品图片</th>
                <th>产品简称</th>
                <th>方案参数</th>
                <th>A1价格</th>
                <th>业务员价格</th>
                <th>单位</th>
                <th>当前数量</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(entry, index) in addCableProductRows"
                :key="entry.product.id"
                :class="{ 'add-cable-row-selected': isAddCableProductSelected(entry.product) }"
              >
                <td class="row-index">{{ index + 1 }}</td>
                <td>
                  <img
                    v-if="productImageUrl(entry.product)"
                    class="product-thumb"
                    :src="productImageUrl(entry.product)"
                    loading="lazy"
                    decoding="async"
                    alt="产品图片"
                    @error="$event.target.style.display = 'none'"
                  />
                  <span v-else class="muted">暂无</span>
                </td>
                <td>
                  <strong>{{ entry.product.abbr || entry.product.label || '-' }}</strong>
                </td>
                <td>
                  <span
                    class="param-cell product-param-cell"
                    :class="{ 'has-param': productParameterText(entry.product) }"
                    @mouseenter="showParameterTooltip(entry.product, $event)"
                    @mousemove="moveParameterTooltip"
                    @mouseleave="hideParameterTooltip"
                  >
                    {{ productParameterText(entry.product) || '-' }}
                  </span>
                </td>
                <td>{{ entry.product.unit_price }}</td>
                <td>{{ entry.product.salesperson_price }}</td>
                <td>{{ productUnit(entry.product) }}</td>
                <td>
                  <div class="add-cable-qty-cell">
                    <input
                      :value="addCableQuantityDisplay(entry.product)"
                      class="qty"
                      type="number"
                      min="0"
                      step="1"
                      @input="updateAddCableQuantity(entry.product, $event.target.value)"
                    />
                  </div>
                </td>
              </tr>
              <tr v-if="addCableProductRows.length === 0">
                <td class="empty-cell" colspan="8">暂无产品</td>
              </tr>
              <tr class="product-custom-table-row add-cable-custom-table-row">
                <td colspan="8">
                  <button
                    class="add-cable-custom-link product-footer-custom-link flashing"
                    type="button"
                    @click="goCustomFromAddCable"
                  >
                    没有线材，去定制
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <footer class="add-cable-modal-footer">
          <div class="add-cable-footer-actions">
            <button class="primary add-cable-confirm" type="button" @click="confirmAddCableProducts">确定修改</button>
            <button class="add-cable-cancel" type="button" @click="closeAddCableModal">取消</button>
          </div>
        </footer>
      </section>
    </div>

    <div v-if="projectCreating" class="project-modal-mask" v-backdrop-dismiss="closeProjectCreateModal">
      <section class="project-create-modal" @click.stop>
        <header class="project-create-modal-head">
          <h2>新增项目</h2>
          <button class="drawer-close" type="button" title="关闭" @click="closeProjectCreateModal">
            <X :size="18" />
          </button>
        </header>
        <div class="project-create-modal-body">
          <label class="field">
            <span>项目名称</span>
            <input v-model="projectForm.name" placeholder="请输入项目名称" autofocus @keyup.enter="createProject" />
          </label>
          <label class="field">
            <span>项目备注</span>
            <textarea v-model="projectForm.note" rows="4" placeholder="请输入项目备注"></textarea>
          </label>
        </div>
        <footer class="project-create-modal-footer">
          <button class="primary" type="button" @click="createProject">确定新增</button>
          <button type="button" @click="closeProjectCreateModal">取消</button>
        </footer>
      </section>
    </div>

    <div v-if="classroomCreating" class="project-modal-mask" v-backdrop-dismiss="closeClassroomCreateModal">
      <section class="project-create-modal classroom-create-modal" @click.stop>
        <header class="project-create-modal-head">
          <h2>新增教室类别</h2>
          <button class="drawer-close" type="button" title="关闭" @click="closeClassroomCreateModal">
            <X :size="18" />
          </button>
        </header>
        <div class="project-create-modal-body">
          <label class="field">
            <span>教室类别</span>
            <input
              ref="classroomNameInput"
              v-model="classroomCreateForm.name"
              placeholder="请输入教室类别"
              autofocus
              @keyup.enter="createProjectClassroom"
            />
          </label>
          <div class="classroom-preset-row">
            <span>快速填入</span>
            <div class="classroom-preset-options">
              <button
                v-for="preset in classroomNamePresets"
                :key="preset"
                type="button"
                :class="{ active: classroomCreateForm.name === preset }"
                @click="fillClassroomNamePreset(preset)"
              >
                {{ preset }}
              </button>
            </div>
          </div>
        </div>
        <footer class="project-create-modal-footer">
          <button class="primary" type="button" @click="createProjectClassroom">确定新增</button>
          <button type="button" @click="closeClassroomCreateModal">取消</button>
        </footer>
      </section>
    </div>

    <div v-if="customCreating" class="project-modal-mask custom-modal-mask" v-backdrop-dismiss="closeCustomCreateModal">
      <section class="project-create-modal custom-create-modal" @click.stop>
        <header class="project-create-modal-head">
          <h2>{{ restartingCustomRequestId ? '重新发起定制' : '新增定制' }}</h2>
          <button class="drawer-close" type="button" title="关闭" @click="closeCustomCreateModal">
            <X :size="18" />
          </button>
        </header>
        <form class="project-create-modal-body custom-create-form" @submit.prevent="submitCustomRequest">
          <div v-if="customCategoryLocked && customCategoryContextText()" class="custom-category-context">
            <span class="required-label">当前分类</span>
            <strong>{{ customCategoryContextText() }}</strong>
          </div>
          <div v-else class="custom-category-selects">
            <label class="custom-field">
              <span class="required-label">一级分类</span>
              <select
                :value="customCategoryContext.category_a"
                @change="selectCustomCategoryA($event.target.value)"
              >
                <option value="" disabled>请选择一级分类</option>
                <option
                  v-for="category in systemCategoryAOptions"
                  :key="category"
                  :value="category"
                >
                  {{ category }}
                </option>
              </select>
            </label>
            <label class="custom-field">
              <span class="required-label">二级分类</span>
              <select
                :value="customCategoryContext.category_b"
                :disabled="!customCategoryContext.category_a"
                @change="selectCustomCategoryB($event.target.value)"
              >
                <option value="" disabled>请选择二级分类</option>
                <option
                  v-for="category in systemCategoryBOptions"
                  :key="category"
                  :value="category"
                >
                  {{ category }}
                </option>
              </select>
            </label>
          </div>
          <div class="custom-head-pair">
            <div class="custom-head-group">
              <div class="custom-head-label required-label">第一头</div>
              <div class="custom-head-fields">
                <label class="custom-field">
                  <span>公母</span>
                  <div class="custom-gender-choice">
                    <div class="custom-gender-pills" aria-label="第一头公母类型">
                      <button
                        v-for="option in ['公头', '母头', '其他']"
                        :key="`a-${option}`"
                        type="button"
                        :class="{ active: customForm.head_a_gender === option }"
                        @click="customForm.head_a_gender = option"
                      >
                        {{ option }}
                      </button>
                    </div>
                    <input
                      v-if="customForm.head_a_gender === '其他'"
                      v-model="customForm.head_a_other"
                      class="custom-other-input"
                      placeholder="其他描述"
                    />
                  </div>
                </label>
              </div>
            </div>
            <div class="custom-head-group">
              <div class="custom-head-label required-label">第二头</div>
              <div class="custom-head-fields">
                <label class="custom-field">
                  <span>公母</span>
                  <div class="custom-gender-choice">
                    <div class="custom-gender-pills" aria-label="第二头公母类型">
                      <button
                        v-for="option in ['公头', '母头', '其他']"
                        :key="`b-${option}`"
                        type="button"
                        :class="{ active: customForm.head_b_gender === option }"
                        @click="customForm.head_b_gender = option"
                      >
                        {{ option }}
                      </button>
                    </div>
                    <input
                      v-if="customForm.head_b_gender === '其他'"
                      v-model="customForm.head_b_other"
                      class="custom-other-input"
                      placeholder="其他描述"
                    />
                  </div>
                </label>
              </div>
            </div>
          </div>
          <div class="custom-length-quantity-row">
            <label class="custom-field">
              <span>长度(米)</span>
              <input v-model="customForm.length_m" type="number" min="0.1" step="0.1" />
            </label>
            <label class="custom-field">
              <span>数量</span>
              <span class="custom-unit-input">
                <input v-model.number="customForm.quantity" type="number" min="1" />
                <em>根</em>
              </span>
            </label>
          </div>
          <label class="custom-field">
            <span>使用场景及补充说明</span>
            <textarea
              v-model="customForm.note"
              rows="5"
              placeholder="示例：智慧教室讲台到显示屏使用，需要耐弯折；线长 3 米，黑色外皮；两端接头朝向有空间限制。"
            ></textarea>
          </label>
          <footer class="project-create-modal-footer custom-create-footer">
            <button class="primary" type="submit" :disabled="busy">
              {{ restartingCustomRequestId ? '重新发起' : '确定新增' }}
            </button>
            <button type="button" @click="closeCustomCreateModal">取消</button>
          </footer>
        </form>
      </section>
    </div>

    <div v-if="customBinding" class="project-modal-mask custom-bind-modal-mask" v-backdrop-dismiss="closeCustomBindModal">
      <section class="project-create-modal custom-bind-modal" @click.stop>
        <header class="project-create-modal-head">
          <div>
            <h2>绑定现有线材</h2>
            <p v-if="activeCustomBindRequest">{{ customCableText(activeCustomBindRequest) }}</p>
          </div>
          <button class="drawer-close" type="button" title="关闭" @click="closeCustomBindModal">
            <X :size="18" />
          </button>
        </header>
        <div class="custom-bind-body">
          <label class="custom-bind-search">
            <Search :size="18" />
            <input v-model="customBindSearch" placeholder="搜索线材简称、型号、分类、参数" autofocus />
          </label>
          <div class="custom-bind-table-shell">
            <table class="management-table custom-bind-table">
              <thead>
                <tr>
                  <th>选择</th>
                  <th>图片</th>
                  <th>线材</th>
                  <th>分类</th>
                  <th>参数</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="product in filteredCustomBindProducts"
                  :key="product.id"
                  :class="{ selected: Number(customBindForm.productId) === Number(product.id) }"
                  @click="customBindForm.productId = product.id"
                >
                  <td class="center-cell">
                    <input v-model="customBindForm.productId" type="radio" :value="product.id" />
                  </td>
                  <td class="center-cell">
                    <img
                      v-if="productImageUrl(product)"
                      class="product-thumb"
                      :src="productImageUrl(product)"
                      loading="lazy"
                      decoding="async"
                      alt="产品图片"
                      @error="$event.target.style.display = 'none'"
                    />
                    <span v-else class="muted">暂无</span>
                  </td>
                  <td>
                    <strong>{{ customBoundProductTitle(product) }}</strong>
                    <span class="custom-bind-product-meta">{{ customBoundProductMeta(product) }}</span>
                  </td>
                  <td class="center-cell">
                    <span class="product-category-inline">
                      <span class="category-chip" :style="categoryChipStyle(product.category_a)">
                        {{ product.category_a || '-' }}
                      </span>
                      <span class="category-chip" :style="categoryChipStyle(product.category_b)">
                        {{ product.category_b || '-' }}
                      </span>
                    </span>
                  </td>
                  <td>
                    <span class="param-cell">{{ productParameterText(product) || '-' }}</span>
                  </td>
                </tr>
                <tr v-if="filteredCustomBindProducts.length === 0">
                  <td class="empty-cell" colspan="5">没有匹配的线材</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <footer class="project-create-modal-footer">
          <button class="primary" type="button" :disabled="busy" @click="bindCustomRequestToProduct">确定绑定</button>
          <button type="button" @click="closeCustomBindModal">取消</button>
        </footer>
      </section>
    </div>

    <section v-show="activeTab === 'registration' && isExternalMode" class="settings-page">
      <section class="account-settings-page">
        <section class="side-panel account-settings-card">
          <h2>账号信息设置</h2>
          <form class="account-settings-form" @submit.prevent="resetExternalAccountPassword">
            <label class="password-form-row account-readonly">
              <span>公司名称</span>
              <strong class="account-value">{{ currentSession.display_name || '-' }}</strong>
            </label>
            <label class="password-form-row account-readonly">
              <span>统一社会信用代码</span>
              <strong class="account-value">{{ currentSession.credit_code || '-' }}</strong>
            </label>
            <label class="password-form-row account-readonly">
              <span>登录账号</span>
              <strong class="account-value">{{ currentSession.username || '-' }}</strong>
            </label>
            <label class="password-form-row">
              <span class="required-label">原密码</span>
              <input v-model="accountPasswordForm.old_password" type="password" autocomplete="current-password" placeholder="请输入原密码" />
            </label>
            <label class="password-form-row">
              <span class="required-label">新密码</span>
              <input v-model="accountPasswordForm.new_password" type="password" autocomplete="new-password" placeholder="请输入新密码" />
            </label>
            <label class="password-form-row">
              <span class="required-label">再次输入新密码</span>
              <input v-model="accountPasswordForm.confirm_password" type="password" autocomplete="new-password" placeholder="请再次输入新密码" />
            </label>
            <footer class="account-settings-actions">
              <button class="primary" type="submit" :disabled="busy">重置密码</button>
            </footer>
          </form>
        </section>
      </section>
    </section>

    <section v-show="activeTab === 'admin-settings'" class="management-page admin-settings-page">
      <div class="admin-settings-head">
        <div>
          <h2>线材商城权限分配</h2>
          <p>平台系统管理员默认拥有线材商城管理权限；部门和成员数据实时取自统一 Auth 组织架构。</p>
        </div>
        <div class="admin-settings-actions">
          <button type="button" :disabled="adminPermissionLoading || adminPermissionSaving" @click="loadAdminPermissionData">
            刷新
          </button>
          <button class="primary" type="button" :disabled="adminPermissionLoading || adminPermissionSaving || !adminPermissionDirty" @click="saveAdminPermissionRules">
            {{ adminPermissionSaving ? '保存中...' : '保存权限' }}
          </button>
        </div>
      </div>
      <div v-if="adminPermissionError" class="message error">{{ adminPermissionError }}</div>
      <div v-if="adminPermissionNotice" class="message notice">{{ adminPermissionNotice }}</div>
      <div v-if="adminPermissionLoading" class="admin-loading">正在加载线材权限...</div>
      <div v-else class="permission-workspace">
        <section class="permission-nav-panel">
          <header>
            <ShieldCheck :size="17" />
            <strong>权限项</strong>
          </header>
          <div class="permission-nav-list">
            <button
              v-for="permission in permissionGroups"
              :key="permission.id"
              type="button"
              class="permission-nav-item"
              :class="{ active: activeAdminPermissionId === permission.id }"
              @click="selectAdminPermission(permission.id)"
            >
              <span class="permission-nav-icon"><component :is="permission.icon" :size="17" /></span>
              <span class="permission-nav-copy">
                <strong>{{ permission.label }}</strong>
                <small>{{ permission.note }}</small>
                <em>{{ permissionSelectedCount(permission.id) }} 人 · {{ permissionSourceCount(permission.id) }} 来源</em>
              </span>
            </button>
          </div>
        </section>

        <section class="permission-detail-panel">
          <header class="permission-detail-head">
            <div>
              <component :is="activeAdminPermission.icon" :size="18" />
              <span>
                <strong>{{ activeAdminPermission.label }}</strong>
                <small>{{ activePermissionMemberRows.length }} 人有效 · {{ activePermissionExcludedRows.length }} 人已排除</small>
              </span>
            </div>
            <em>{{ permissionSourceCount(activeAdminPermissionId) }} 个来源</em>
          </header>

          <div class="permission-source-grid">
            <section v-for="scope in permissionScopeGroups" :key="scope.id" class="permission-source-card">
              <div class="permission-source-head">
                <div>
                  <component :is="scope.icon" :size="16" />
                  <strong>{{ scope.label }}</strong>
                </div>
                <button class="primary" type="button" @click="openPermissionPicker(activeAdminPermissionId, scope.id)">
                  <Plus :size="14" />添加
                </button>
              </div>
              <div class="permission-tags">
                <span v-if="!rulesForPermission(activeAdminPermissionId, scope.id).length" class="permission-empty">{{ scope.empty }}</span>
                <span
                  v-for="rule in rulesForPermission(activeAdminPermissionId, scope.id)"
                  :key="permissionRuleKey(rule.permission, rule.scopeType, rule.targetId)"
                  class="permission-tag"
                >
                  <span>{{ permissionSourceDisplayName(rule) }}</span>
                  <em v-if="rule.scopeType === 'departmentSub'">含下级</em>
                  <button type="button" title="移除" @click="removePermissionRule(rule)">
                    <X :size="13" />
                  </button>
                </span>
              </div>
            </section>
          </div>

          <div class="permission-member-shell">
            <table v-if="activePermissionMemberRows.length || activePermissionExcludedRows.length" class="permission-member-table">
              <thead>
                <tr>
                  <th>姓名</th>
                  <th>所在部门</th>
                  <th>权限来源</th>
                  <th>状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in activePermissionMemberRows" :key="`${activeAdminPermissionId}:member:${row.id}`">
                  <td>
                    <div class="permission-member-name">
                      <span class="permission-member-avatar">
                        <img v-if="row.employee.avatarUrl" :src="row.employee.avatarUrl" :alt="row.name" referrerpolicy="no-referrer" />
                        <b v-else>{{ row.name.slice(0, 1) }}</b>
                      </span>
                      <strong>{{ row.name }}</strong>
                    </div>
                  </td>
                  <td :title="row.departmentText">{{ row.departmentText }}</td>
                  <td :title="row.sourceText">{{ row.sourceText || '-' }}</td>
                  <td class="center-cell"><span class="permission-state valid">有效</span></td>
                  <td class="center-cell">
                    <button class="permission-member-action" type="button" @click="excludePermissionMember(row)">
                      <UserMinus :size="14" />{{ row.includedByDepartment ? '踢掉' : '移除' }}
                    </button>
                  </td>
                </tr>
                <tr v-for="row in activePermissionExcludedRows" :key="`${activeAdminPermissionId}:excluded:${row.id}`" class="excluded">
                  <td>
                    <div class="permission-member-name">
                      <span class="permission-member-avatar"><b>{{ row.name.slice(0, 1) }}</b></span>
                      <strong>{{ row.name }}</strong>
                    </div>
                  </td>
                  <td :title="row.departmentText">{{ row.departmentText }}</td>
                  <td :title="row.sourceText">{{ row.sourceText || '-' }}</td>
                  <td class="center-cell"><span class="permission-state excluded">已排除</span></td>
                  <td class="center-cell"><button class="permission-member-action restore" type="button" @click="restorePermissionMember(row)">恢复</button></td>
                </tr>
              </tbody>
            </table>
            <div v-else class="permission-member-empty">暂无权限成员</div>
          </div>
        </section>
      </div>
    </section>

    <section v-show="activeTab === 'custom'" class="management-page custom-page">
      <div class="management-toolbar">
        <label class="management-search">
          <span>搜索</span>
          <input v-model="customSearch" placeholder="搜索定制需求" />
        </label>
        <button class="primary management-create-button" type="button" @click="openCustomCreateModal">新增定制</button>
      </div>

      <div
        ref="customTableShellRef"
        class="management-table-shell custom-table-shell"
        @scroll="syncCustomBottomScrollFromTable"
      >
        <table class="management-table custom-table">
          <colgroup>
            <col class="custom-col-category" />
            <col class="custom-col-head" />
            <col class="custom-col-length" />
            <col class="custom-col-quantity" />
            <col class="custom-col-note" />
            <col class="custom-col-submitter" />
            <col class="custom-col-status-result" />
            <col class="custom-col-action" />
          </colgroup>
          <thead>
            <tr>
              <th>分类</th>
              <th>头1-头2</th>
              <th>长度</th>
              <th>数量</th>
              <th>使用场景及说明</th>
              <th>提交人</th>
              <th>状态 / 处理结果</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in filteredCustomRequests" :key="item.id">
              <td><span class="custom-info-bubble">{{ customCategoryText(item) }}</span></td>
              <td><span class="custom-info-bubble head">{{ customHeadPairText(item) }}</span></td>
              <td class="center-cell">{{ item.length_m }}m</td>
              <td class="center-cell">{{ item.quantity }}</td>
              <td>{{ item.note || item.scenario || '-' }}</td>
              <td class="center-cell">{{ customSubmitterText(item) }}</td>
              <td>
                <div class="custom-status-result-cell">
                  <span class="status-pill" :class="customStatusClass(item)">{{ customStatusText(item) }}</span>
                  <span class="custom-handle-result-text">{{ customHandleResultText(item) }}</span>
                </div>
              </td>
              <td>
                <div class="custom-row-actions">
                  <template v-if="isExternalMode">
                    <button
                      v-if="item.status === '待处理'"
                      class="text-action danger-text"
                      type="button"
                      @click="cancelCustomRequest(item)"
                    >
                      取消
                    </button>
                    <button
                      v-if="isRequesterCanceledCustom(item)"
                      class="text-action copy-text"
                      type="button"
                      @click="restartCustomRequest(item)"
                    >
                      重新发起
                    </button>
                    <button
                      v-if="item.bound_product_id || item.bound_product"
                      class="text-action copy-text"
                      type="button"
                      @click="openCustomBoundDetail(item)"
                    >
                      详情
                    </button>
                  </template>
                  <template v-else>
                    <button
                      v-if="!['已绑定', '已完成', '已取消', '已忽略', '已关闭'].includes(item.status)"
                      class="text-action copy-text"
                      type="button"
                      @click="openCustomBindModal(item)"
                    >
                      处理绑定
                    </button>
	                    <button
	                      v-if="!['已绑定', '已完成', '已取消', '已忽略', '已关闭'].includes(item.status)"
	                      class="text-action warning-text"
	                      type="button"
	                      @click="ignoreCustomRequest(item)"
	                    >
	                      暂不考虑
	                    </button>
	                  </template>
	                  <span
	                    v-if="(isExternalMode && !['待处理'].includes(item.status) && !isRequesterCanceledCustom(item) && !(item.bound_product_id || item.bound_product)) || (!isExternalMode && ['已绑定', '已完成', '已取消', '已忽略', '已关闭'].includes(item.status))"
	                    class="custom-action-empty"
	                  >
                    -
                  </span>
                </div>
              </td>
            </tr>
            <tr v-if="filteredCustomRequests.length === 0">
              <td class="empty-cell" colspan="8">暂无定制需求</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div
        v-show="activeTab === 'custom' && customBottomScrollVisible"
        ref="customBottomScrollRef"
        class="custom-bottom-scroll"
        @scroll="syncCustomTableScrollFromBottom"
      >
        <div :style="{ width: `${customBottomScrollWidth}px` }"></div>
      </div>
    </section>

    <section v-show="activeTab === 'orders'" class="management-page order-page">
      <div class="order-filter-panel">
        <div class="category-filter-tabs order-filter-tabs">
          <div class="category-filter-row">
            <span>搜索</span>
            <div class="search-box order-search-box">
              <Search :size="18" />
              <input v-model="orderSearch" placeholder="搜索订单号、购买方、业务员、下单人、金额、状态" />
            </div>
          </div>
          <div class="category-filter-row">
            <span>订单状态</span>
            <div class="category-filter-pills order-status-tabs">
              <button
                v-for="tab in orderStatusTabs"
                :key="tab.key"
                type="button"
                :class="{ active: orderStatusFilter === tab.key }"
                @click="orderStatusFilter = tab.key"
              >
                {{ tab.label }}
                <em>{{ orderStatusCounts[tab.key] || 0 }}</em>
              </button>
            </div>
          </div>
        </div>
        <div class="management-toolbar-actions">
          <button class="primary management-create-button" type="button" @click="openOrderCreate">
            <Plus :size="16" />
            去下单
          </button>
        </div>
      </div>

      <div class="management-table-shell">
        <table class="management-table order-list-table">
          <thead>
            <tr>
              <th>订单号</th>
              <th>购买方（签单方）</th>
              <th>对应业务员</th>
              <th>下单人</th>
              <th>总金额</th>
              <th>下单时间</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(order, index) in filteredOrders"
              :key="order.id"
              class="order-clickable-row"
              tabindex="0"
              @click="openOrderDetail(order)"
              @keydown.enter.prevent="openOrderDetail(order)"
              @keydown.space.prevent="openOrderDetail(order)"
            >
              <td><strong>{{ order.order_no }}</strong></td>
              <td>{{ orderBuyerName(order) }}</td>
              <td class="center-cell">{{ orderSalespersonName(order) }}</td>
              <td class="center-cell">{{ orderSubmitterName(order) }}</td>
              <td class="package-table-price">￥{{ order.total_amount }}</td>
              <td class="center-cell">{{ formatDateTime(order.created_at) }}</td>
              <td class="center-cell">
                <span class="order-status-pill" :class="`stage-${orderWorkflowStage(order)}`">{{ orderListStatus(order) }}</span>
              </td>
              <td class="center-cell">
                <div class="order-row-actions">
                  <button
                    v-for="action in orderActionButtons(order)"
                    :key="action.key"
                    class="text-action"
                    :class="action.className"
                    type="button"
                    @click.stop="action.handler(order)"
                  >
                    {{ action.label }}
                  </button>
                </div>
              </td>
            </tr>
            <tr v-if="filteredOrders.length === 0">
              <td class="empty-cell" colspan="8">{{ orderSearch.trim() ? '没有匹配的订单' : '暂无订单' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

	    <section v-show="activeTab === 'external-accounts'" class="management-page external-account-page">
	      <div class="management-toolbar">
	        <div class="management-toolbar-left external-account-toolbar-left">
	          <label class="management-search">
	            <span>搜索</span>
	            <input v-model="externalAccountSearch" placeholder="搜索公司名称、统一社会信用代码、登录账号、归属人" />
	          </label>
	          <div class="account-status-tabs" role="tablist" aria-label="外部账号状态">
	            <button
	              v-for="tab in externalAccountStatusTabs"
	              :key="tab.key"
	              type="button"
	              :class="{ active: externalAccountStatusTab === tab.key }"
	              @click="externalAccountStatusTab = tab.key"
	            >
	              {{ tab.label }}
	              <em>{{ externalAccountStatusCounts[tab.key] || 0 }}</em>
	            </button>
	          </div>
	        </div>
	        <div class="management-toolbar-actions">
	          <button type="button" @click="loadExternalAccounts">
            <RefreshCw :size="16" />
            刷新
          </button>
          <button class="primary management-create-button" type="button" @click="openExternalAccountCreateModal">
            <Plus :size="16" />
            新增外部账号
          </button>
        </div>
      </div>

      <div class="management-table-shell">
        <table class="management-table external-account-table">
          <thead>
            <tr>
              <th>序号</th>
              <th>公司名称</th>
              <th>统一社会信用代码</th>
              <th>登录账号</th>
              <th>登录密码</th>
              <th>归属人</th>
              <th>状态</th>
              <th>订单数</th>
              <th>最后登录</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(item, index) in filteredExternalAccounts" :key="item.id">
              <td class="row-index">{{ index + 1 }}</td>
              <template v-if="editingExternalAccountId === item.id">
                <td><input v-model="externalAccountEditForm.display_name" class="table-input" placeholder="公司名称" /></td>
                <td><input v-model="externalAccountEditForm.credit_code" class="table-input" placeholder="统一社会信用代码" /></td>
                <td><strong>{{ item.username }}</strong></td>
                <td>
                  <input v-model="externalAccountEditForm.password" class="table-input" placeholder="留空不改密码" />
                </td>
                <td>{{ item.owner_name || item.owner_user_id || '-' }}</td>
                <td>
                  <select v-model="externalAccountEditForm.status">
                    <option value="active">启用</option>
                    <option value="disabled">停用</option>
                  </select>
                </td>
                <td class="center-cell">{{ item.order_count || 0 }}</td>
                <td class="center-cell">{{ item.last_login_at ? formatDateTime(item.last_login_at) : '-' }}</td>
                <td class="center-cell">{{ formatDateTime(item.created_at) }}</td>
                <td class="center-cell">
                  <div class="address-row-actions">
                    <button class="text-action" type="button" @click="saveExternalAccountEdit(item)">保存</button>
                    <button class="text-action" type="button" @click="cancelExternalAccountEdit">取消</button>
                  </div>
                </td>
              </template>
              <template v-else>
                <td>{{ item.display_name || '-' }}</td>
                <td class="center-cell">{{ item.credit_code || '-' }}</td>
                <td><strong>{{ item.username }}</strong></td>
                <td class="center-cell muted">已设置</td>
                <td>{{ item.owner_name || item.owner_user_id || '-' }}</td>
                <td class="center-cell">
                  <span class="status-pill" :class="{ muted: item.status !== 'active' }">{{ item.status_label }}</span>
                </td>
                <td class="center-cell">{{ item.order_count || 0 }}</td>
                <td class="center-cell">{{ item.last_login_at ? formatDateTime(item.last_login_at) : '-' }}</td>
                <td class="center-cell">{{ formatDateTime(item.created_at) }}</td>
                <td class="center-cell">
                  <div class="address-row-actions">
                    <button class="text-action" type="button" @click="startExternalAccountEdit(item)">编辑</button>
                    <button class="text-action" type="button" @click="toggleExternalAccountStatus(item)">
                      {{ item.status === 'active' ? '停用' : '启用' }}
                    </button>
                  </div>
                </td>
              </template>
            </tr>
            <tr v-if="filteredExternalAccounts.length === 0">
              <td class="empty-cell" colspan="11">{{ externalAccountSearch.trim() ? '没有匹配的外部账号' : '暂无外部账号' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-show="activeTab === 'shipping-addresses'" class="management-page shipping-address-page">
      <div class="management-toolbar">
        <label class="management-search">
          <span>搜索</span>
          <input v-model="shippingAddressSearch" placeholder="搜索地址、收货人、手机号" />
        </label>
        <div class="management-toolbar-actions">
          <button type="button" @click="loadShippingAddresses">
            <RefreshCw :size="16" />
            刷新
          </button>
          <button class="primary management-create-button" type="button" @click="openShippingAddressCreateModal">
            <Plus :size="16" />
            新增地址
          </button>
        </div>
      </div>

      <div class="management-table-shell">
        <table class="management-table shipping-address-table">
          <thead>
            <tr>
              <th>序号</th>
              <th>详细地址与门牌号</th>
              <th>收货人名字</th>
              <th>手机号</th>
              <th>更新时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(item, index) in filteredShippingAddresses" :key="item.id">
              <td class="row-index">{{ index + 1 }}</td>
              <td>
                <div class="address-main-cell">
                  <strong>{{ item.detail_address }}</strong>
                </div>
              </td>
              <td class="center-cell">{{ item.receiver_name }}</td>
              <td class="center-cell">{{ item.receiver_phone }}</td>
              <td class="center-cell">{{ formatDateTime(item.updated_at) }}</td>
              <td>
                <div v-if="deletingShippingAddressId === item.id" class="address-row-actions">
                  <button class="text-action danger-text" type="button" @click="deleteShippingAddress(item)">确认删除</button>
                  <button class="text-action" type="button" @click="cancelShippingAddressDelete">取消</button>
                </div>
                <div v-else class="address-row-actions">
                  <button class="text-action" type="button" @click="startShippingAddressEdit(item)">编辑</button>
                  <button class="text-action danger-text" type="button" @click="startShippingAddressDelete(item)">删除</button>
                </div>
              </td>
            </tr>
            <tr v-if="filteredShippingAddresses.length === 0">
              <td class="empty-cell" colspan="6">{{ shippingAddressSearch.trim() ? '没有匹配的收货地址' : '暂无收货地址' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-show="activeTab === 'signing-infos'" class="management-page signing-info-page">
      <div class="management-toolbar">
        <label class="management-search">
          <span>搜索</span>
          <input v-model="signingInfoSearch" placeholder="搜索公司名称、开户银行、税号、账号" />
        </label>
        <div class="management-toolbar-actions">
          <button type="button" @click="loadSigningInfos">
            <RefreshCw :size="16" />
            刷新
          </button>
          <button class="primary management-create-button" type="button" @click="openSigningInfoCreateModal">
            <Plus :size="16" />
            新增公司抬头
          </button>
        </div>
      </div>

      <div class="management-table-shell">
        <table class="management-table signing-info-table">
          <thead>
            <tr>
              <th>序号</th>
              <th>公司名称</th>
              <th>开户银行</th>
              <th>税号</th>
              <th>账号</th>
              <th>更新时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(item, index) in filteredSigningInfos" :key="item.id">
              <td class="row-index">{{ index + 1 }}</td>
              <td><strong>{{ item.company_name }}</strong></td>
              <td>{{ item.opening_bank }}</td>
              <td class="center-cell">{{ item.tax_number }}</td>
              <td class="center-cell">{{ item.bank_account }}</td>
              <td class="center-cell">{{ formatDateTime(item.updated_at) }}</td>
              <td>
                <div v-if="deletingSigningInfoId === item.id" class="address-row-actions">
                  <button class="text-action danger-text" type="button" @click="deleteSigningInfo(item)">确认删除</button>
                  <button class="text-action" type="button" @click="cancelSigningInfoDelete">取消</button>
                </div>
                <div v-else class="address-row-actions">
                  <button class="text-action" type="button" @click="startSigningInfoEdit(item)">编辑</button>
                  <button class="text-action danger-text" type="button" @click="startSigningInfoDelete(item)">删除</button>
                </div>
              </td>
            </tr>
            <tr v-if="filteredSigningInfos.length === 0">
              <td class="empty-cell" colspan="7">{{ signingInfoSearch.trim() ? '没有匹配的公司抬头' : '暂无公司抬头' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <div v-if="customBoundDetailOpen" class="project-modal-mask custom-modal-mask" v-backdrop-dismiss="closeCustomBoundDetail">
      <section class="project-create-modal custom-bound-detail-modal" @click.stop>
        <header class="project-create-modal-head">
          <h2>绑定线缆详情</h2>
          <button class="drawer-close" type="button" title="关闭" @click="closeCustomBoundDetail">
            <X :size="18" />
          </button>
        </header>
        <div class="custom-bound-detail-body">
          <template v-if="customBoundDetailRequest?.bound_product">
            <div class="custom-bound-product-title">
              <strong>{{ customBoundProductTitle(customBoundDetailRequest.bound_product) }}</strong>
              <span>{{ customBoundProductMeta(customBoundDetailRequest.bound_product) }}</span>
            </div>
            <div class="custom-bound-product-grid">
              <div>
                <span>一级分类</span>
                <strong>{{ customBoundDetailRequest.bound_product.category_a || '-' }}</strong>
              </div>
              <div>
                <span>二级分类</span>
                <strong>{{ customBoundDetailRequest.bound_product.category_b || '-' }}</strong>
              </div>
              <div>
                <span>产品型号</span>
                <strong>{{ customBoundDetailRequest.bound_product.product_model || '-' }}</strong>
              </div>
              <div>
                <span>A1价格</span>
                <strong>￥{{ customBoundDetailRequest.bound_product.unit_price || '0.00' }}</strong>
              </div>
              <div>
                <span>业务员价格</span>
                <strong>￥{{ customBoundDetailRequest.bound_product.salesperson_price || '0.00' }}</strong>
              </div>
            </div>
            <label class="custom-bound-param">
              <span>方案参数</span>
              <textarea :value="productParameterText(customBoundDetailRequest.bound_product) || '-'" rows="5" readonly></textarea>
            </label>
          </template>
          <div v-else class="custom-bound-empty">
            {{ customBoundDetailRequest?.bound_product_label || customHandleResultText(customBoundDetailRequest || {}) || '暂无绑定线缆详情' }}
          </div>
        </div>
        <footer class="project-create-modal-footer">
          <button class="primary" type="button" @click="closeCustomBoundDetail">关闭</button>
        </footer>
      </section>
    </div>

    <div v-if="externalAccountCreating" class="project-modal-mask custom-modal-mask" v-backdrop-dismiss="closeExternalAccountCreateModal">
      <section class="project-create-modal external-account-modal" @click.stop>
        <header class="project-create-modal-head">
          <h2>新增外部账号</h2>
          <button class="drawer-close" type="button" title="关闭" @click="closeExternalAccountCreateModal">
            <X :size="18" />
          </button>
        </header>
        <form class="project-create-modal-body external-account-form" @submit.prevent="createExternalAccount">
          <div v-if="externalAccountCreatedCredential" class="external-account-credential">
            <strong>账号已创建</strong>
            <span>登录账号：{{ externalAccountCreatedCredential.username }}</span>
            <span>登录密码：{{ externalAccountCreatedCredential.password }}</span>
          </div>
          <label class="field">
            <span class="required-label">公司名称</span>
            <input v-model="externalAccountForm.display_name" placeholder="请输入公司名称" autofocus />
          </label>
          <label class="field">
            <span class="required-label">统一社会信用代码</span>
            <input v-model="externalAccountForm.credit_code" placeholder="请输入统一社会信用代码" />
          </label>
          <label class="field">
            <span class="required-label">登录账号</span>
            <input v-model="externalAccountForm.username" placeholder="请输入登录账号" />
          </label>
          <label class="field">
            <span class="required-label">登录密码</span>
            <input v-model="externalAccountForm.password" placeholder="请输入登录密码" />
          </label>
          <footer class="project-create-modal-footer">
            <button class="primary" type="submit" :disabled="busy">确定新增</button>
            <button type="button" @click="closeExternalAccountCreateModal">取消</button>
          </footer>
        </form>
      </section>
    </div>

    <div v-if="shippingAddressCreating" class="project-modal-mask custom-modal-mask shipping-address-modal-mask" v-backdrop-dismiss="closeShippingAddressCreateModal">
      <section class="project-create-modal shipping-address-modal" @click.stop>
        <header class="project-create-modal-head">
          <h2>新增收货地址</h2>
          <button class="drawer-close" type="button" title="关闭" @click="closeShippingAddressCreateModal">
            <X :size="18" />
          </button>
        </header>
        <form class="project-create-modal-body shipping-address-form" @submit.prevent="createShippingAddress">
          <label class="field">
            <span class="required-label">详细地址与门牌号</span>
            <textarea v-model="shippingAddressForm.detail_address" placeholder="请输入详细地址与门牌号" rows="3" autofocus></textarea>
          </label>
          <label class="field">
            <span class="required-label">收货人名字</span>
            <input v-model="shippingAddressForm.receiver_name" placeholder="请输入收货人名字" />
          </label>
          <label class="field">
            <span class="required-label">手机号</span>
            <input v-model="shippingAddressForm.receiver_phone" placeholder="请输入手机号" />
          </label>
          <footer class="project-create-modal-footer">
            <button class="primary" type="submit" :disabled="busy">确定新增</button>
            <button type="button" @click="closeShippingAddressCreateModal">取消</button>
          </footer>
        </form>
      </section>
    </div>

    <div v-if="shippingAddressEditing" class="project-modal-mask custom-modal-mask shipping-address-modal-mask" v-backdrop-dismiss="cancelShippingAddressEdit">
      <section class="project-create-modal shipping-address-modal" @click.stop>
        <header class="project-create-modal-head">
          <h2>编辑收货地址</h2>
          <button class="drawer-close" type="button" title="关闭" @click="cancelShippingAddressEdit">
            <X :size="18" />
          </button>
        </header>
        <form class="project-create-modal-body shipping-address-form" @submit.prevent="saveShippingAddressEdit">
          <label class="field">
            <span class="required-label">详细地址与门牌号</span>
            <textarea v-model="shippingAddressEditForm.detail_address" placeholder="请输入详细地址与门牌号" rows="3" autofocus></textarea>
          </label>
          <label class="field">
            <span class="required-label">收货人名字</span>
            <input v-model="shippingAddressEditForm.receiver_name" placeholder="请输入收货人名字" />
          </label>
          <label class="field">
            <span class="required-label">手机号</span>
            <input v-model="shippingAddressEditForm.receiver_phone" placeholder="请输入手机号" />
          </label>
          <footer class="project-create-modal-footer shipping-address-edit-footer">
            <button class="primary" type="submit" :disabled="busy">保存</button>
            <button type="button" @click="cancelShippingAddressEdit">取消</button>
          </footer>
        </form>
      </section>
    </div>

    <div v-if="signingInfoCreating" class="project-modal-mask custom-modal-mask shipping-address-modal-mask" v-backdrop-dismiss="closeSigningInfoCreateModal">
      <section class="project-create-modal signing-info-modal" @click.stop>
        <header class="project-create-modal-head">
          <h2>新增公司抬头</h2>
          <button class="drawer-close" type="button" title="关闭" @click="closeSigningInfoCreateModal">
            <X :size="18" />
          </button>
        </header>
        <form class="project-create-modal-body signing-info-form" @submit.prevent="createSigningInfo">
          <label class="field">
            <span class="required-label">公司名称</span>
            <input v-model="signingInfoForm.company_name" placeholder="请输入公司名称" autofocus />
          </label>
          <label class="field">
            <span class="required-label">开户银行</span>
            <input v-model="signingInfoForm.opening_bank" placeholder="请输入开户银行" />
          </label>
          <label class="field">
            <span class="required-label">税号</span>
            <input v-model="signingInfoForm.tax_number" placeholder="请输入税号" />
          </label>
          <label class="field">
            <span class="required-label">账号</span>
            <input v-model="signingInfoForm.bank_account" placeholder="请输入账号" />
          </label>
          <footer class="project-create-modal-footer">
            <button class="primary" type="submit" :disabled="busy">确定新增</button>
            <button type="button" @click="closeSigningInfoCreateModal">取消</button>
          </footer>
        </form>
      </section>
    </div>

    <div v-if="signingInfoEditing" class="project-modal-mask custom-modal-mask shipping-address-modal-mask" v-backdrop-dismiss="cancelSigningInfoEdit">
      <section class="project-create-modal signing-info-modal" @click.stop>
        <header class="project-create-modal-head">
          <h2>编辑公司抬头</h2>
          <button class="drawer-close" type="button" title="关闭" @click="cancelSigningInfoEdit">
            <X :size="18" />
          </button>
        </header>
        <form class="project-create-modal-body signing-info-form" @submit.prevent="saveSigningInfoEdit">
          <label class="field">
            <span class="required-label">公司名称</span>
            <input v-model="signingInfoEditForm.company_name" placeholder="请输入公司名称" autofocus />
          </label>
          <label class="field">
            <span class="required-label">开户银行</span>
            <input v-model="signingInfoEditForm.opening_bank" placeholder="请输入开户银行" />
          </label>
          <label class="field">
            <span class="required-label">税号</span>
            <input v-model="signingInfoEditForm.tax_number" placeholder="请输入税号" />
          </label>
          <label class="field">
            <span class="required-label">账号</span>
            <input v-model="signingInfoEditForm.bank_account" placeholder="请输入账号" />
          </label>
          <footer class="project-create-modal-footer shipping-address-edit-footer">
            <button class="primary" type="submit" :disabled="busy">保存</button>
            <button type="button" @click="cancelSigningInfoEdit">取消</button>
          </footer>
        </form>
      </section>
    </div>

    <div v-if="productCartOpen" class="project-modal-mask custom-modal-mask product-cart-modal-mask" v-backdrop-dismiss="closeProductCartModal">
      <section class="project-create-modal product-cart-modal" @click.stop>
        <header class="project-create-modal-head">
          <h2>加入购物车</h2>
          <button class="drawer-close" type="button" title="关闭" @click="closeProductCartModal">
            <X :size="18" />
          </button>
        </header>
        <div v-if="productCartTarget" class="project-create-modal-body product-cart-modal-body">
          <div class="product-cart-product-card">
            <img
              v-if="productImageUrl(productCartTarget)"
              class="product-thumb"
              :src="productImageUrl(productCartTarget)"
              loading="lazy"
              decoding="async"
              alt="产品图片"
              @error="$event.target.style.display = 'none'"
            />
            <div>
              <strong>{{ productCartTarget.abbr || productCartTarget.label || '-' }}</strong>
              <span>{{ [productCartTarget.product_model, productCartTarget.category_a, productCartTarget.category_b].filter(Boolean).join(' / ') || '-' }}</span>
            </div>
            <em>￥{{ productOrderUnitPrice(productCartTarget).toFixed(2) }}</em>
          </div>
          <div class="product-cart-param">
            {{ productParameterText(productCartTarget) || '-' }}
          </div>
          <div class="product-cart-quantity-row">
            <div class="product-cart-total">小计：￥{{ productLineAmount(productCartTarget, productCartDraftQuantity) }}</div>
            <label class="field">
              <span class="required-label">数量</span>
              <input v-model.number="productCartDraftQuantity" type="number" min="1" step="1" autofocus />
            </label>
          </div>
          <footer class="project-create-modal-footer">
            <button class="primary" type="button" @click="confirmAddProductToCart">加入购物车</button>
            <button type="button" @click="closeProductCartModal">取消</button>
          </footer>
        </div>
      </section>
    </div>

    <div v-if="productCartDetailOpen" class="project-modal-mask custom-modal-mask product-cart-modal-mask" v-backdrop-dismiss="closeProductCartDetail">
      <section class="project-create-modal product-cart-detail-modal" @click.stop>
        <header class="project-create-modal-head">
          <div class="product-cart-detail-title">
            <h2>购物车详情</h2>
            <span>已选 {{ productCartSummary.count }} 种线材</span>
          </div>
          <button class="drawer-close" type="button" title="关闭" @click="closeProductCartDetail">
            <X :size="18" />
          </button>
        </header>
        <div class="product-cart-detail-body">
          <div v-for="item in sortedProductCartItems" :key="item.product.id" class="product-cart-detail-row">
            <img
              v-if="productImageUrl(item.product)"
              class="product-thumb"
              :src="productImageUrl(item.product)"
              loading="lazy"
              decoding="async"
              alt="产品图片"
              @error="$event.target.style.display = 'none'"
            />
            <div class="product-cart-detail-info">
              <strong>{{ item.product.abbr || item.product.label || '-' }}</strong>
              <span>{{ [item.product.product_model, item.product.category_a, item.product.category_b].filter(Boolean).join(' / ') || '-' }}</span>
            </div>
            <div class="product-cart-detail-price">
              <div>
                <span>单价</span>
                <strong>￥{{ productOrderUnitPrice(item.product).toFixed(2) }}</strong>
              </div>
              <div>
                <span>小计</span>
                <strong>￥{{ productCartLineAmount(item) }}</strong>
              </div>
            </div>
            <div class="product-cart-detail-controls">
              <input
                v-model.number="item.quantity"
                class="product-cart-detail-qty"
                type="number"
                min="1"
                step="1"
                @input="updateProductCartQuantity(item, $event.target.value)"
              />
              <button class="product-cart-remove-button" type="button" @click="removeProductCartItem(item)">移除</button>
            </div>
          </div>
          <div v-if="productCartItems.length === 0" class="product-cart-detail-empty">购物车暂无线材</div>
        </div>
        <footer class="project-create-modal-footer product-cart-detail-footer">
          <div class="product-cart-detail-summary">
            <span>合计</span>
            <strong>{{ productCartSummary.count }} 种</strong>
            <span>总价</span>
            <em>￥{{ productCartSummary.amount }}</em>
          </div>
          <button class="primary" type="button" :disabled="!productCartItems.length" @click="openProductCartOrder">去下单</button>
          <button type="button" @click="closeProductCartDetail">关闭</button>
        </footer>
      </section>
    </div>

    <div
      v-if="orderCreateOpen"
      class="project-modal-mask order-modal-mask"
      :class="{ 'order-modal-mask-over-cart': productCartDetailOpen }"
      v-backdrop-dismiss="closeOrderCreate"
    >
        <section class="project-create-modal order-create-modal" @click.stop>
          <header class="project-create-modal-head order-create-head">
          <h2>{{ orderCreateTitle }}</h2>
          <button class="drawer-close" type="button" title="关闭" @click="closeOrderCreate">
            <X :size="18" />
          </button>
        </header>
        <div class="order-create-body">
          <aside class="order-create-side">
            <section class="order-panel-card order-info-bubble">
              <div class="order-summary-list order-info-summary">
                <div class="order-summary-row">
                  <span>数量（根）</span>
                  <strong>{{ selectedOrderSummary.cableCount }}</strong>
                </div>
                <div class="order-summary-row total">
                  <span>总金额（元）</span>
                  <strong>{{ selectedOrderSummary.amount }}</strong>
                </div>
              </div>

              <label v-if="!isExternalMode" class="order-customer-select">
                <span class="order-address-select-label required-label">客户选择</span>
                <select v-model="orderForm.external_account_id">
                  <option value="" disabled>请选择客户</option>
                  <option
                    v-for="account in selectableOrderCustomers"
                    :key="account.id"
                    :value="account.id"
                  >
                    {{ account.display_name }} / {{ account.credit_code }}
                  </option>
                </select>
                <small v-if="selectedOrderCustomer">
                  公司名称：{{ selectedOrderCustomer.display_name }}；统一社会信用代码：{{ selectedOrderCustomer.credit_code || '-' }}
                </small>
              </label>
              <div v-else class="order-customer-readonly">
                <span class="order-address-select-label required-label">客户信息</span>
                <strong>{{ selectedOrderCustomer?.display_name || '-' }}</strong>
                <small>统一社会信用代码：{{ selectedOrderCustomer?.credit_code || '-' }}</small>
              </div>

              <button class="order-address-select" type="button" @click="openOrderSigningInfoDrawer">
                <span v-if="selectedOrderSigningInfo" class="order-address-select-main">
                  <span class="order-address-select-label required-label">公司抬头</span>
                  <strong>{{ selectedOrderSigningInfo.company_name }}</strong>
                  <small>
                    {{ selectedOrderSigningInfo.opening_bank }} / {{ selectedOrderSigningInfo.tax_number }}
                  </small>
                  <small>账号：{{ selectedOrderSigningInfo.bank_account }}</small>
                </span>
                <span v-else class="order-address-select-main">
                  <span class="order-address-select-label required-label">公司抬头</span>
                  <small class="order-address-select-empty">请选择公司抬头</small>
                </span>
                <span class="order-address-select-action">{{ selectedOrderSigningInfo ? '更换' : '选择抬头' }}</span>
              </button>

              <button class="order-address-select" type="button" @click="openOrderAddressDrawer">
                <span v-if="selectedOrderShippingAddress" class="order-address-select-main">
                  <span class="order-address-select-label required-label">收货地址</span>
                  <strong>
                    {{ selectedOrderShippingAddress.receiver_name }} {{ selectedOrderShippingAddress.receiver_phone }}
                  </strong>
                  <small>{{ selectedOrderShippingAddress.detail_address }}</small>
                </span>
                <span v-else class="order-address-select-main">
                  <span class="order-address-select-label required-label">收货地址</span>
                  <small class="order-address-select-empty">请选择收货地址</small>
                </span>
                <span class="order-address-select-action">{{ selectedOrderShippingAddress ? '更换' : '选择地址' }}</span>
              </button>

              <div class="order-delivery-fields">
                <label>
                  <span class="order-address-select-label">收货方式</span>
                  <select v-model="orderForm.shipping_method">
                    <option value="快递">快递</option>
                    <option value="物流">物流</option>
                    <option value="自提">自提</option>
                    <option value="送货上门">送货上门</option>
                    <option value="其他">其他</option>
                  </select>
                </label>
                <label>
                  <span class="order-address-select-label">到货日期</span>
                  <input v-model="orderForm.arrival_date" type="date" />
                </label>
              </div>
            </section>

            <label class="order-panel-card order-remark-field order-remark-bubble">
              <span>下单备注</span>
              <textarea v-model="orderForm.remark" placeholder="请输入备注" rows="5"></textarea>
            </label>
          </aside>

          <div class="order-create-picker">
            <div class="order-create-picker-head">
              <div class="management-toolbar compact order-create-toolbar">
                <div v-if="orderCreateTab === 'project-classrooms'" class="order-project-view-tabs">
                  <button
                    type="button"
                    :class="{ active: orderProjectViewMode === 'classrooms' }"
                    @click="setOrderProjectViewMode('classrooms')"
                  >
                    教室
                  </button>
                  <button
                    type="button"
                    :class="{ active: orderProjectViewMode === 'cables' }"
                    @click="setOrderProjectViewMode('cables')"
                  >
                    线材
                  </button>
                </div>
                <label class="management-search">
                  <span>搜索</span>
                  <input v-model="orderCreateSearch" :placeholder="orderCreateSearchPlaceholder" />
                </label>
              </div>
              <div v-if="orderCreateTab === 'order-edit'" class="order-copy-banner">
                <strong>编辑未锁定订单</strong>
                <span>保存后覆盖当前订单，锁单后不再允许修改。</span>
              </div>
              <div v-else-if="orderCreateTab === 'order-copy'" class="order-copy-banner">
                <strong>复制订单：{{ orderCopyDraft?.source_order_no || '-' }}</strong>
                <span>订单内容按当前产品重新生成，原订单保持不变。</span>
              </div>
            </div>
            <div v-if="orderCopyWarnings.length" class="order-copy-warnings">
              <div v-for="warning in orderCopyWarnings" :key="`${warning.type}-${warning.message}`">
                {{ warning.message }}
              </div>
            </div>

            <div class="management-table-shell order-create-table-shell">
              <table
                v-if="orderCreateTab !== 'project-classrooms' || orderProjectViewMode === 'cables'"
                class="management-table order-package-table"
                :class="{ 'project-order-table': orderCreateTab === 'project-classrooms' }"
              >
                <thead>
                  <tr>
                    <th v-if="orderCreateTab !== 'project-classrooms'">选择</th>
                    <th>{{ orderCreateNameHeader }}</th>
                    <th>单项金额</th>
                    <th>下单数量</th>
                    <th>小计</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="item in orderablePackageRows"
                    :key="item.order_key"
                    class="order-select-row"
                    :class="{ selected: orderCreateTab === 'project-classrooms' || selectedOrderPackageIds[item.order_key], readonly: orderCreateTab === 'project-classrooms' }"
                    tabindex="0"
                    @click="orderCreateTab !== 'project-classrooms' && toggleOrderPackageRow(item)"
                    @keydown.enter.prevent="orderCreateTab !== 'project-classrooms' && toggleOrderPackageRow(item)"
                    @keydown.space.prevent="orderCreateTab !== 'project-classrooms' && toggleOrderPackageRow(item)"
                  >
                    <td v-if="orderCreateTab !== 'project-classrooms'" class="center-cell">
                      <input
                        class="order-select-checkbox"
                        type="checkbox"
                        :checked="Boolean(selectedOrderPackageIds[item.order_key])"
                        @click.stop
                        @change="toggleOrderPackage(item, $event.target.checked)"
                      />
                    </td>
                    <td class="order-source-cell">
                      <strong>{{ item.order_display_name }}</strong>
                      <small>{{ item.order_note }}</small>
                    </td>
                    <td class="order-money-cell">￥{{ Number(item.order_amount || 0).toFixed(2) }}</td>
                    <td class="center-cell">
                      <span v-if="orderCreateTab === 'project-classrooms'" class="order-qty-readonly">
                        {{ orderPackageQuantity(item) }}
                      </span>
                      <input
                        v-else
                        v-model.number="orderPackageQuantities[item.order_key]"
                        class="order-qty-input"
                        type="number"
                        min="1"
                        step="1"
                        :disabled="orderCreateTab === 'project-classrooms' || !selectedOrderPackageIds[item.order_key]"
                        @click.stop
                        @keydown.stop
                        @input="item.order_source === 'cart-product' && updateProductCartQuantity(item, $event.target.value)"
                      />
                    </td>
                    <td class="order-money-cell order-line-total-cell">
                      ￥{{ orderCreateTab === 'project-classrooms' ? Number(item.line_amount || 0).toFixed(2) : (selectedOrderPackageIds[item.order_key] ? orderPackageAmount(item) : '0.00') }}
                    </td>
                  </tr>
                  <tr v-if="orderablePackageRows.length === 0">
                    <td class="empty-cell" :colspan="orderCreateTab === 'project-classrooms' ? 4 : 5">{{ orderCreateEmptyText }}</td>
                  </tr>
                </tbody>
              </table>
              <table v-else class="management-table order-project-classroom-table">
                <thead>
                  <tr>
                    <th>教室</th>
                    <th>类型</th>
                    <th>线材种类</th>
                    <th>线材数量</th>
                    <th>教室间数</th>
                    <th>单间金额</th>
                    <th>小计</th>
                  </tr>
                </thead>
                <tbody>
                  <template v-for="item in orderProjectClassroomRows" :key="item.key">
                    <tr
                      v-for="(scopeRow, scopeIndex) in item.scope_rows"
                      :key="`${item.key}-${scopeRow.key}`"
                      class="order-select-row selected readonly"
                    >
                      <td v-if="scopeIndex === 0" class="order-source-cell order-project-classroom-name" rowspan="2">
                        <strong>{{ item.name }}</strong>
                        <small>{{ item.project_name }}</small>
                      </td>
                      <td class="center-cell order-project-classroom-type">{{ scopeRow.label }}</td>
                      <td class="center-cell">{{ classroomScopeKindCount(scopeRow) }}</td>
                      <td class="center-cell">{{ classroomScopeCableCount(scopeRow) }}</td>
                      <td v-if="scopeIndex === 0" class="center-cell" rowspan="2">
                        <span class="order-qty-readonly">{{ item.room_count }}</span>
                      </td>
                      <td v-if="scopeIndex === 0" class="order-money-cell" rowspan="2">￥{{ item.single_amount }}</td>
                      <td v-if="scopeIndex === 0" class="order-money-cell order-line-total-cell" rowspan="2">￥{{ item.total_amount }}</td>
                    </tr>
                  </template>
                  <tr v-if="orderProjectClassroomRows.length === 0">
                    <td class="empty-cell" colspan="7">{{ orderCreateEmptyText }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
        <footer class="project-create-actions order-create-actions">
          <button type="button" @click="closeOrderCreate">取消</button>
          <button class="primary" type="button" @click="createOrder">{{ orderSubmitText }}</button>
        </footer>
      </section>
    </div>

    <div v-if="orderAddressPickerOpen" class="order-address-drawer-mask" v-backdrop-dismiss="closeOrderAddressDrawer">
      <aside class="order-address-drawer" @click.stop>
        <header class="order-address-drawer-head">
          <div>
            <h3>选择收货地址</h3>
            <span>点确定后填充到下单信息</span>
          </div>
          <button class="drawer-close" type="button" title="关闭" @click="closeOrderAddressDrawer">
            <X :size="18" />
          </button>
        </header>
        <div class="order-address-drawer-tools">
          <label class="order-address-drawer-search">
            <Search :size="15" />
            <input v-model="orderAddressSearch" placeholder="搜索地址、收货人、手机号" autofocus />
          </label>
          <button class="order-address-add-button" type="button" @click="openShippingAddressCreateModal('order')">
            <Plus :size="14" />
            新增地址
          </button>
        </div>
        <div class="order-address-drawer-list">
          <div
            v-for="address in filteredOrderShippingAddresses"
            :key="address.id"
            class="order-address-option"
            :class="{ active: Number(pendingOrderShippingAddressId) === Number(address.id) }"
            tabindex="0"
            @click="selectOrderShippingAddress(address)"
            @dblclick="confirmOrderAddressSelection(address)"
            @keydown.enter.prevent="selectOrderShippingAddress(address)"
            @keydown.space.prevent="selectOrderShippingAddress(address)"
          >
            <div class="order-address-option-main">
              <strong>
                {{ address.receiver_name }} {{ address.receiver_phone }}
              </strong>
              <span>{{ address.detail_address }}</span>
            </div>
            <button
              class="order-address-edit-button"
              type="button"
              @click.stop="startShippingAddressEdit(address, 'order')"
            >
              编辑
            </button>
          </div>
          <div v-if="filteredOrderShippingAddresses.length === 0" class="order-address-empty">
            暂无匹配地址
          </div>
        </div>
        <footer class="order-address-drawer-footer">
          <button type="button" @click="closeOrderAddressDrawer">取消</button>
          <button class="primary" type="button" @click="confirmOrderAddressDrawer">确定</button>
        </footer>
      </aside>
    </div>

    <div v-if="orderSigningInfoPickerOpen" class="order-address-drawer-mask" v-backdrop-dismiss="closeOrderSigningInfoDrawer">
      <aside class="order-address-drawer order-signing-drawer" @click.stop>
        <header class="order-address-drawer-head">
          <div>
            <h3>选择公司抬头</h3>
            <span>点确定后填充到下单信息</span>
          </div>
          <button class="drawer-close" type="button" title="关闭" @click="closeOrderSigningInfoDrawer">
            <X :size="18" />
          </button>
        </header>
        <div class="order-address-drawer-tools">
          <label class="order-address-drawer-search">
            <Search :size="15" />
            <input v-model="orderSigningInfoSearch" placeholder="搜索公司、开户银行、税号、账号" autofocus />
          </label>
          <button class="order-address-add-button" type="button" @click="openSigningInfoCreateModal('order')">
            <Plus :size="14" />
            新增抬头
          </button>
        </div>
        <div class="order-address-drawer-list">
          <div
            v-for="info in filteredOrderSigningInfos"
            :key="info.id"
            class="order-address-option order-signing-option"
            :class="{ active: Number(pendingOrderSigningInfoId) === Number(info.id) }"
            tabindex="0"
            @click="selectOrderSigningInfo(info)"
            @dblclick="confirmOrderSigningInfoSelection(info)"
            @keydown.enter.prevent="selectOrderSigningInfo(info)"
            @keydown.space.prevent="selectOrderSigningInfo(info)"
          >
            <div class="order-address-option-main order-signing-option-main">
              <strong>{{ info.company_name }}</strong>
              <span>开户银行：{{ info.opening_bank }}</span>
              <span>税号：{{ info.tax_number }}</span>
              <span>账号：{{ info.bank_account }}</span>
            </div>
            <button
              class="order-address-edit-button"
              type="button"
              @click.stop="startSigningInfoEdit(info, 'order')"
            >
              编辑
            </button>
          </div>
          <div v-if="filteredOrderSigningInfos.length === 0" class="order-address-empty">
            暂无匹配公司抬头
          </div>
        </div>
        <footer class="order-address-drawer-footer">
          <button type="button" @click="closeOrderSigningInfoDrawer">取消</button>
          <button class="primary" type="button" @click="confirmOrderSigningInfoDrawer">确定</button>
        </footer>
      </aside>
    </div>

    <div v-if="orderDetailOpen" class="order-detail-drawer-mask" v-backdrop-dismiss="closeOrderDetail">
      <aside class="order-detail-drawer" @click.stop>
        <header class="order-detail-drawer-head">
          <div class="order-detail-title-wrap">
            <div class="order-detail-title-icon">
              <FolderKanban :size="20" />
            </div>
            <div class="order-detail-title-text">
              <h3>{{ selectedOrder?.signing_company_name || selectedOrder?.external_account_name || '下单详情' }}</h3>
              <div class="order-detail-title-meta">
                <span>{{ selectedOrder?.order_no || '订单详情' }}</span>
                <b v-if="selectedOrder" class="order-status-pill" :class="`stage-${orderWorkflowStage(selectedOrder)}`">{{ orderListStatus(selectedOrder) }}</b>
              </div>
            </div>
          </div>
          <div class="order-detail-head-actions">
            <button
              v-for="action in orderActionButtons(selectedOrder)"
              :key="action.key"
              type="button"
              :class="action.className"
              :disabled="!selectedOrder"
              @click="action.handler(selectedOrder)"
            >
              {{ action.label }}
            </button>
            <button class="drawer-close" type="button" title="关闭" @click="closeOrderDetail">
              <X :size="18" />
            </button>
          </div>
        </header>
        <nav v-if="selectedOrder" class="order-detail-tabs" aria-label="订单详情切换">
          <button
            v-for="tab in orderDetailTabs"
            :key="tab.key"
            type="button"
            :class="{ active: orderDetailTab === tab.key }"
            @click="orderDetailTab = tab.key"
          >
            {{ tab.label }}
          </button>
        </nav>
        <div v-if="selectedOrder" class="order-detail-modal-body">
          <div v-if="orderDetailTab === 'info'" class="order-detail-overview">
            <section class="order-detail-section order-detail-section-main">
              <header>
                <span>订单信息</span>
                <strong>￥{{ selectedOrder.total_amount }}</strong>
              </header>
              <div class="order-detail-summary-cards">
                <div>
                  <span>订单状态</span>
                  <strong>{{ orderListStatus(selectedOrder) }}</strong>
                </div>
                <div>
                  <span>线材数量</span>
                  <strong>{{ selectedOrder.total_cables }}</strong>
                </div>
                <div>
                  <span>下单时间</span>
                  <strong>{{ formatDateTime(selectedOrder.created_at) }}</strong>
                </div>
                <div>
                  <span>订单金额</span>
                  <strong>￥{{ selectedOrder.total_amount }}</strong>
                </div>
              </div>
              <div class="order-detail-fields">
                <label>
                  <span>公司名称</span>
                  <strong>{{ selectedOrder.external_account_name || selectedOrder.signing_company_name || '-' }}</strong>
                </label>
                <label>
                  <span>统一社会信用代码</span>
                  <strong>{{ selectedOrder.external_account_credit_code || '-' }}</strong>
                </label>
                <label>
                  <span>订单号</span>
                  <strong>{{ selectedOrder.order_no }}</strong>
                </label>
                <label>
                  <span>锁单时间</span>
                  <strong>{{ formatDateTime(selectedOrder.locked_at) }}</strong>
                </label>
                <label class="wide order-detail-progress-field">
                  <span>进度明细</span>
                  <strong class="order-detail-progress-cards">
                    <section
                      v-for="bubble in orderDetailProgressBubbles"
                      :key="bubble.key"
                      class="order-detail-progress-card"
                      :class="orderDetailProgressBubbleClass(selectedOrder, bubble.key)"
	                    >
	                      <div class="order-progress-card-head">
	                        <b>{{ bubble.label }}</b>
	                        <i>{{ orderDetailProgressBubbleText(selectedOrder, bubble.key) }}</i>
	                      </div>
	                      <div class="order-progress-card-row order-progress-status-row">
	                        <span>状态</span>
	                        <select
	                          :value="orderDetailProgressBubbleText(selectedOrder, bubble.key)"
	                          :disabled="isExternalMode || !selectedOrder || selectedOrder.status === '未锁定' || selectedOrder.status === '已删除'"
	                          @change="changeOrderProgressStatus(selectedOrder, bubble.key, $event.target.value)"
	                        >
	                          <option
	                            v-for="option in bubble.statusOptions"
	                            :key="option"
	                            :value="option"
	                          >
	                            {{ option }}
	                          </option>
	                        </select>
	                      </div>
		                      <div class="order-progress-card-row order-progress-complete-row">
		                        <span>完成状态</span>
		                        <div class="order-progress-complete-main">
		                          <button
		                            v-if="canCompleteOrderProgress(selectedOrder, bubble.key)"
		                            type="button"
		                            :class="{ complete: !orderProgressTime(selectedOrder, bubble.key), cancel: orderProgressTime(selectedOrder, bubble.key) }"
		                            @click.stop="toggleOrderProgressComplete(selectedOrder, bubble.key)"
		                          >
		                            <Check v-if="!orderProgressTime(selectedOrder, bubble.key)" :size="13" />
		                            {{ orderProgressTime(selectedOrder, bubble.key) ? '取消完成' : '确认完成' }}
		                          </button>
		                          <em>
		                            {{ orderProgressTime(selectedOrder, bubble.key) ? `完成时间：${formatDateTime(orderProgressTime(selectedOrder, bubble.key))}` : '未完成' }}
		                          </em>
		                        </div>
		                      </div>
		                      <div
		                        v-if="bubble.key === 'contract'"
		                        class="order-progress-card-row order-progress-contract-download-row"
		                      >
		                        <span>合同下载</span>
		                        <button
		                          type="button"
		                          :disabled="!selectedOrder?.can_export_pdf"
		                          :title="selectedOrder?.can_export_pdf ? '按模板下载合同' : '锁单后才能下载合同'"
		                          @click.stop="printOrderPdf(selectedOrder)"
		                        >
		                          <Download :size="13" />
		                          下载合同
		                        </button>
		                      </div>
		                      <div class="order-progress-card-row order-progress-card-file-row">
		                        <span>附件</span>
		                        <div class="order-progress-file-line">
		                          <div class="order-progress-card-file">
		                            <a
		                              v-if="orderProgressFileUrl(selectedOrder, bubble.key)"
		                              :href="backendAssetUrl(orderProgressFileUrl(selectedOrder, bubble.key))"
		                              target="_blank"
		                              rel="noreferrer"
		                            >
		                              <FileText :size="13" />
		                              查看附件
		                            </a>
		                            <em v-else>暂无附件</em>
		                          </div>
		                          <button
		                            v-if="canUploadOrderProgress(selectedOrder, bubble.key)"
		                            type="button"
		                            @click.stop="uploadOrderProgress(selectedOrder, bubble.key)"
		                          >
		                            <Upload :size="13" />
		                            {{ orderProgressFileUrl(selectedOrder, bubble.key) ? '重新上传' : '上传' }}
		                          </button>
		                        </div>
		                      </div>
		                      <label class="order-progress-card-row order-progress-card-note">
		                        <span>备注</span>
		                        <textarea
		                          :value="orderProgressNote(selectedOrder, bubble.key)"
		                          :disabled="isExternalMode || !selectedOrder || selectedOrder.status === '未锁定' || selectedOrder.status === '已删除'"
		                          rows="2"
		                          placeholder="填写备注"
		                          @input="setOrderProgressNote(selectedOrder, bubble.key, $event.target.value)"
		                          @blur="saveOrderProgressNote(selectedOrder, bubble.key)"
		                        ></textarea>
		                      </label>
		                    </section>
                  </strong>
                </label>
              </div>
            </section>

            <section class="order-detail-section">
              <header>
                <span>收货信息</span>
              </header>
              <div class="order-detail-fields two-column">
                <label>
                  <span>收货人</span>
                  <strong>{{ selectedOrder.customer_name || '-' }}</strong>
                </label>
                <label>
                  <span>手机号</span>
                  <strong>{{ selectedOrder.customer_phone || '-' }}</strong>
                </label>
                <label class="wide">
                  <span>收货地址</span>
                  <strong>{{ selectedOrder.project_name || '-' }}</strong>
                </label>
                <label>
                  <span>收货方式</span>
                  <strong>{{ selectedOrder.shipping_method || '-' }}</strong>
                </label>
                <label>
                  <span>到货日期</span>
                  <strong>{{ selectedOrder.arrival_date || '-' }}</strong>
                </label>
              </div>
            </section>

            <section class="order-detail-section">
              <header>
                <span>公司抬头</span>
              </header>
              <div class="order-detail-fields two-column">
                <label>
                  <span>公司名称</span>
                  <strong>{{ selectedOrder.signing_company_name || '-' }}</strong>
                </label>
                <label>
                  <span>开户银行</span>
                  <strong>{{ selectedOrder.signing_opening_bank || '-' }}</strong>
                </label>
                <label>
                  <span>税号</span>
                  <strong>{{ selectedOrder.signing_tax_number || '-' }}</strong>
                </label>
                <label>
                  <span>账号</span>
                  <strong>{{ selectedOrder.signing_bank_account || '-' }}</strong>
                </label>
              </div>
            </section>

            <section v-if="selectedOrder.remark" class="order-detail-section order-detail-section-files">
              <header>
                <span>备注</span>
              </header>
              <div class="order-detail-files">
                <p v-if="selectedOrder.remark">{{ selectedOrder.remark }}</p>
              </div>
            </section>
          </div>
          <div v-else class="order-detail-products">
            <div class="order-detail-product-head">
              <div class="order-detail-product-summary">
                <span>
                  <em>线材数量</em>
                  <strong>{{ selectedOrder.total_cables }}</strong>
                </span>
                <span>
                  <em>总金额</em>
                  <strong>￥{{ selectedOrder.total_amount }}</strong>
                </span>
              </div>
              <div v-if="selectedOrderHasProjectView" class="order-detail-product-tabs" role="tablist">
                <button
                  v-for="view in orderDetailProjectProductViews"
                  :key="view.key"
                  type="button"
                  :class="{ active: orderDetailProductView === view.key }"
                  @click="orderDetailProductView = view.key"
                >
                  {{ view.label }}
                </button>
              </div>
            </div>

            <section
              v-if="selectedOrderHasProjectView && orderDetailProductView === 'classrooms'"
              class="order-detail-section order-detail-product-section"
            >
              <header>
                <span>教室视图</span>
                <strong>{{ selectedOrderClassroomRows.length }} 间</strong>
              </header>
              <div class="order-detail-table-shell">
                <table class="order-detail-product-table order-detail-classroom-table">
                  <thead>
                    <tr>
                      <th>教室</th>
                      <th>线材范围</th>
                      <th>线材种类</th>
                      <th>线材数量</th>
                      <th>教室间数</th>
                      <th>单间金额</th>
                      <th>小计</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="classroom in selectedOrderClassroomRows" :key="classroom.key">
                      <td>
                        <strong class="order-detail-product-name">{{ classroom.name }}</strong>
                        <small v-if="classroom.project_name">{{ classroom.project_name }}</small>
                      </td>
                      <td>
                        <div class="order-detail-scope-chips">
                          <span
                            v-for="scopeRow in classroom.scope_rows"
                            :key="scopeRow.key"
                            :class="{ empty: !scopeRow.package }"
                          >
                            <b>{{ scopeRow.label }}</b>
                            <em v-if="scopeRow.package">
                              {{ classroomScopeKindCount(scopeRow) }} 种 / {{ orderDetailScopeCableCount(scopeRow) }} 根
                            </em>
                            <em v-else>未配置</em>
                          </span>
                        </div>
                      </td>
                      <td class="center-cell">{{ classroom.kind_count }}</td>
                      <td class="center-cell">{{ classroom.cable_count }}</td>
                      <td class="center-cell">{{ classroom.room_count }}</td>
                      <td class="package-table-price">￥{{ classroom.single_amount }}</td>
                      <td class="package-table-price">￥{{ classroom.total_amount }}</td>
                    </tr>
                    <tr v-if="!selectedOrderClassroomRows.length">
                      <td class="order-empty" colspan="7">暂无产品信息</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>

            <section v-else class="order-detail-section order-detail-product-section">
              <header>
                <span>线材视图</span>
                <strong>{{ selectedOrderProductRows.length }} 种</strong>
              </header>
              <div class="order-detail-table-shell">
                <table class="order-detail-product-table">
                  <thead>
                    <tr>
                      <th>线材</th>
                      <th>型号</th>
                      <th>分类</th>
                      <th>单价</th>
                      <th>数量</th>
                      <th>小计</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in selectedOrderProductRows" :key="row.key">
                      <td>
                        <strong class="order-detail-product-name">{{ row.product_abbr || row.product_label }}</strong>
                        <small v-if="row.product_abbr && row.product_label && row.product_abbr !== row.product_label">
                          {{ row.product_label }}
                        </small>
                      </td>
                      <td>{{ row.product_model || '-' }}</td>
                      <td>
                        <span class="order-detail-category-pill">{{ row.category_a || '-' }}</span>
                        <span v-if="row.category_b" class="order-detail-category-pill muted">{{ row.category_b }}</span>
                      </td>
                      <td class="package-table-price">￥{{ row.unit_price }}</td>
                      <td class="center-cell">{{ row.quantity }}</td>
                      <td class="package-table-price">￥{{ row.amount_text }}</td>
                    </tr>
                    <tr v-if="!selectedOrderProductRows.length">
                      <td class="order-empty" colspan="6">暂无产品信息</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        </div>
      </aside>
    </div>

    <div v-if="permissionPicker.open" class="project-modal-mask permission-picker-mask" v-backdrop-dismiss="closePermissionPicker">
      <section class="permission-picker-dialog" :class="permissionPicker.scopeType" @click.stop>
        <header class="project-create-modal-head">
          <h2>{{ permissionPickerTitle }}</h2>
          <button class="drawer-close" type="button" title="关闭" @click="closePermissionPicker">
            <X :size="18" />
          </button>
        </header>
        <div class="permission-picker-search">
          <Search :size="16" />
          <input
            ref="permissionPickerInput"
            v-model.trim="permissionPicker.keyword"
            :placeholder="permissionPicker.scopeType === 'department' ? '搜索部门、编号或者首字母' : '搜索姓名、部门或者首字母'"
            @keydown="handlePermissionPickerKeydown"
          />
        </div>
        <div v-if="permissionPicker.scopeType === 'department'" class="permission-picker-table department">
          <div class="permission-picker-table-head department">
            <span>部门</span>
            <span>包含子部门</span>
            <span>人数</span>
          </div>
          <div class="permission-picker-table-body">
            <div
              v-for="row in permissionPickerRows"
              :key="row.id"
              class="permission-department-row"
              :class="{ selected: row.selected, forced: row.forced }"
              @click="togglePermissionDepartmentExpanded(row)"
            >
              <div class="permission-department-name" :style="{ paddingLeft: `${Number(row.depth || 0) * 18}px` }">
                <input
                  type="checkbox"
                  :checked="row.selected"
                  :disabled="row.forced"
                  @click.stop
                  @change="togglePermissionDepartment(row)"
                />
                <ChevronDown
                  :size="16"
                  class="permission-tree-chevron"
                  :class="{ collapsed: row.hasChildren && !row.expanded, hidden: !row.hasChildren }"
                />
                <strong>{{ row.name }}</strong>
                <small>{{ row.id }}</small>
              </div>
              <label @click.stop>
                <input
                  type="checkbox"
                  :checked="row.includeSubDepartments"
                  :disabled="row.forced"
                  @change="setPermissionDepartmentIncludeChildren(row, $event.target.checked)"
                />
                <span>包含</span>
              </label>
              <span>{{ row.subtitle }}</span>
            </div>
            <div v-if="!permissionPickerRows.length" class="permission-picker-empty">无匹配部门</div>
          </div>
        </div>
        <div v-else class="permission-picker-table employee">
          <div class="permission-picker-table-head employee">
            <span>人员</span>
            <span>部门</span>
          </div>
          <div class="permission-picker-table-body">
            <div
              v-for="row in permissionPickerRows"
              :key="row.id"
              class="permission-employee-row"
              :class="{ selected: row.selected }"
              @click="togglePermissionEmployee(row)"
            >
              <div>
                <input type="checkbox" :checked="row.selected" @click.stop @change="togglePermissionEmployee(row)" />
                <strong>{{ row.name }}</strong>
                <small>{{ row.id }}</small>
              </div>
              <span :title="row.subtitle">{{ row.subtitle }}</span>
            </div>
            <div v-if="!permissionPickerRows.length" class="permission-picker-empty">无匹配人员</div>
          </div>
        </div>
      </section>
    </div>

      </section>
    </div>

  </main>
  <div
    v-if="parameterTooltip.visible"
    ref="parameterTooltipRef"
    class="parameter-tooltip"
    :style="{ left: `${parameterTooltip.x}px`, top: `${parameterTooltip.y}px` }"
  >
    <div class="parameter-tooltip-title">方案参数</div>
    <div class="parameter-tooltip-body">
      <div v-for="(line, index) in parameterTooltipLines(parameterTooltip.text)" :key="index" class="parameter-tooltip-line">
        {{ line }}
      </div>
    </div>
  </div>
  <div v-if="imagePreview.open" class="image-preview-mask" v-backdrop-dismiss="closeImagePreview">
    <section class="image-preview-dialog" @click.stop>
      <button class="image-preview-close" type="button" title="关闭" @click="closeImagePreview">
        <X :size="20" />
      </button>
      <div class="image-preview-title">{{ imagePreview.title }}</div>
      <img class="image-preview-img" :src="imagePreview.src" :alt="imagePreview.title" />
    </section>
  </div>
<PlatformUnsavedChangesDialog :open="suggestionsConfirmOpen" @cancel="cancelSuggestionsLeave" @confirm="confirmSuggestionsLeave" />
</template>

<style scoped src="./CableMallWorkspace_web.css"></style>
