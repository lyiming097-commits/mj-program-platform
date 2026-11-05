<script setup>
import AppSelect from "@/shared/AppSelect.vue";
import { computed, onMounted, shallowRef } from "vue";
import { Camera, Check, ChevronLeft, ChevronRight, FileUp, MapPin, PackageSearch, Search, Trash2 } from "lucide-vue-next";

import { useCollectionForm } from "@/composables/useCollectionForm";
import { productImageUrl } from "@/features/competitiveApi";
import { matchesSearch } from "@/features/search";
import AppModal from "@/shared/AppModal.vue";
import ParameterTextEditor from "@/shared/ParameterTextEditor.vue";
import SearchableSelect from "@/shared/SearchableSelect.vue";
import UnsavedChangesDialog from "@/shared/UnsavedChangesDialog.vue";
import DesktopAttachmentThumbnail from "./DesktopAttachmentThumbnail.vue";
import DesktopLocationPicker from "./DesktopLocationPicker.vue";
import DesktopLocationPreview from "./DesktopLocationPreview.vue";

const props = defineProps({ open: Boolean });
const emit = defineEmits(["close", "submitted", "notify"]);
const locationOpen = shallowRef(false);
const discardOpen = shallowRef(false);
const step = shallowRef(0);
const error = shallowRef("");
const productQuery = shallowRef("");
const productDomain = shallowRef("");
const productLevelTwo = shallowRef("");
const productCategory = shallowRef("");
const formState = useCollectionForm();
const { form, files, categories, products, options, submitting, savingDraft, draftId, draftAttachments } = formState;
const steps = computed(() => [
  "基础信息",
  formState.collectionField("product_id", "关联我司产品", true).label,
  "竞争分析",
  formState.collectionField("material_category", "资料归属", true).label,
  "地点与提交",
]);
const productDomains = computed(() => [...new Set(products.value.map((item) => item.productDomain || item.line).filter(Boolean))].sort());
const productLevelTwos = computed(() => [...new Set(products.value.filter((item) => !productDomain.value || item.productDomain === productDomain.value).map((item) => item.levelTwo).filter(Boolean))].sort());
const productCategories = computed(() => [...new Set(products.value.filter((item) => (!productDomain.value || item.productDomain === productDomain.value) && (!productLevelTwo.value || item.levelTwo === productLevelTwo.value)).map((item) => item.category).filter(Boolean))].sort());
const visibleProducts = computed(() => products.value.filter((item) =>
  (!productDomain.value || item.productDomain === productDomain.value)
  && (!productLevelTwo.value || item.levelTwo === productLevelTwo.value)
  && (!productCategory.value || item.category === productCategory.value)
  && matchesSearch(productQuery.value, [
    item.name,
    item.fullName,
    item.kingdeeCode,
    item.model,
    item.brand,
    item.shortName,
  ]),
));

function field(code, label, required = false) { return formState.collectionField(code, label, required); }
function fileKey(file) { return `${file.name}-${file.lastModified}-${file.size}`; }
function validateStep(index) {
  let missing = "";
  if (index === 0) missing = formState.missingRequiredField([
    { code: "brand", fallbackLabel: "竞品品牌", fallbackRequired: true, filled: Boolean(form.brand.trim()) },
    { code: "name", fallbackLabel: "产品名称", fallbackRequired: true, filled: Boolean(form.name.trim()) },
    { code: "model", fallbackLabel: "产品型号", filled: Boolean(form.model.trim()) },
    { code: "price", fallbackLabel: "单价", filled: Boolean(form.price.trim()) },
    { code: "attachments", fallbackLabel: "现场资料", filled: Boolean(files.value.length || draftAttachments.value.length) },
  ]);
  if (index === 1) missing = formState.missingRequiredField([{ code: "product_id", fallbackLabel: "关联我司产品", fallbackRequired: true, filled: Boolean(form.productId) }]);
  if (index === 2) missing = formState.missingRequiredField([
    { code: "dealer", fallbackLabel: "现有经销商", filled: Boolean(form.dealer.trim()) },
    { code: "customer", fallbackLabel: "现有客户", filled: Boolean(form.customer.trim()) },
    { code: "note", fallbackLabel: "一线备注", filled: Boolean(form.note.trim()) },
    { code: "competitor_parameters", fallbackLabel: "竞品参数", filled: Boolean(form.competitorParameterText.trim()) },
    { code: "advantage", fallbackLabel: "竞品优势", filled: Boolean(form.advantage.trim()) },
    { code: "weakness", fallbackLabel: "竞品劣势", filled: Boolean(form.weakness.trim()) },
    { code: "tactic", fallbackLabel: "销售应对策略", filled: Boolean(form.tactic.trim()) },
  ]);
  if (index === 3 && files.value.length && field("material_category", "资料归属", true).required) {
    if (files.value.some((file) => !categories[fileKey(file)])) missing = field("material_category", "资料归属", true).label;
  }
  if (index === 4) missing = formState.missingRequiredField([
    { code: "region", fallbackLabel: "采集地区", fallbackRequired: true, filled: Boolean(form.region) },
    { code: "location", fallbackLabel: "具体地点", fallbackRequired: true, filled: Boolean(form.location.trim()) },
    { code: "validity", fallbackLabel: "资料有效期", filled: Boolean(form.validity) },
    { code: "reminder_owner", fallbackLabel: "到期提醒责任人", filled: Boolean(form.reminderOwner) },
  ]);
  error.value = missing ? `请填写${missing}` : "";
  return !missing;
}
function next() { if (validateStep(step.value)) step.value = Math.min(steps.value.length - 1, step.value + 1); }
function previous() { error.value = ""; step.value = Math.max(0, step.value - 1); }
async function handleSubmit() { if (!validateStep(4)) return; try { const result = await formState.submit(); emit("submitted", result); formState.reset(); step.value = 0; emit("close"); } catch (reason) { emit("notify", reason.message || "提交失败"); } }
async function handleSaveDraft() { try { await formState.saveDraft(); emit("notify", "草稿已保存"); } catch (reason) { emit("notify", reason.message || "草稿保存失败"); } }
async function handleDiscardDraft() { try { await formState.discardDraft(); step.value = 0; emit("notify", "草稿已放弃"); } catch (reason) { emit("notify", reason.message || "草稿删除失败"); } }
function requestClose() {
  if (submitting.value || savingDraft.value) return;
  if (formState.dirty.value) discardOpen.value = true;
  else emit("close");
}
function discardAndClose() {
  formState.discardChanges();
  discardOpen.value = false;
  locationOpen.value = false;
  step.value = 0;
  error.value = "";
  emit("close");
}
function selectLocation(value) { Object.assign(form, { location: value.address, located: true, latitude: value.latitude, longitude: value.longitude, locationAccuracy: value.locationAccuracy, locatedAt: value.locatedAt, locationSource: "device" }); locationOpen.value = false; }
onMounted(() => formState.loadOptions().catch((reason) => emit("notify", reason.message || "选项加载失败")));
</script>

<template>
  <AppModal :open="props.open" title="新增竞品采集" width="896px" @close="requestClose">
    <div class="stepper"><button v-for="(label,index) in steps" :key="label" type="button" :disabled="index > step" :class="{ active:index===step,done:index<step }" @click="step=index; error='' "><span><Check v-if="index < step" :size="12" /><template v-else>{{ index+1 }}</template></span><b>{{ label }}</b></button></div>
    <form id="desktop-collection-form" class="collection-form" @submit.prevent="handleSubmit">
      <section v-if="step === 0" class="step-one"><div v-if="field('attachments','现场资料').enabled" class="upload-column"><h3>{{ field('attachments','现场资料').label }}<em v-if="field('attachments','现场资料').required">*</em></h3><div class="upload-grid"><label><Camera :size="20" /><b>拍照</b><input type="file" accept="image/*" capture="environment" hidden @change="formState.addFiles($event.target.files); $event.target.value=''" /></label><label><Camera :size="20" /><b>从相册选择</b><input type="file" accept="image/*" multiple hidden @change="formState.addFiles($event.target.files); $event.target.value=''" /></label><label class="wide"><FileUp :size="20" /><b>多文件上传</b><small>{{ files.length ? `已选择 ${files.length} 个附件` : '图片、视频、PDF 与 Office 文件' }}</small><input type="file" multiple hidden @change="formState.addFiles($event.target.files); $event.target.value=''" /></label></div><div v-for="(file,index) in files" :key="fileKey(file)" class="selected-file"><DesktopAttachmentThumbnail :file="file" :name="file.name" /><span>{{ file.name }}</span><button type="button" aria-label="移除附件" @click="formState.removeFile(index)"><Trash2 :size="14" /></button></div><div v-for="file in draftAttachments" :key="file.id" class="selected-file saved"><DesktopAttachmentThumbnail :name="file.name" :type="file.type" /><span>{{ file.name }}</span><small>草稿附件</small></div></div><div class="basic-grid"><label v-if="field('brand','竞品品牌',true).enabled"><span>{{ field('brand','竞品品牌',true).label }}<em v-if="field('brand','竞品品牌',true).required">*</em></span><input v-model="form.brand" class="control" placeholder="请输入品牌名称" /></label><label v-if="field('name','产品名称',true).enabled"><span>{{ field('name','产品名称',true).label }}<em v-if="field('name','产品名称',true).required">*</em></span><input v-model="form.name" class="control" placeholder="请输入竞品名称" /></label><label v-if="field('model','产品型号').enabled"><span>{{ field('model','产品型号').label }}<em v-if="field('model','产品型号').required">*</em></span><input v-model="form.model" class="control" placeholder="铭牌或项目型号" /></label><label v-if="field('price','单价').enabled"><span>{{ field('price','单价').label }}<em v-if="field('price','单价').required">*</em></span><input v-model="form.price" class="control" placeholder="如：¥18,600" /></label></div></section>

      <section v-else-if="step === 1"><h3>{{ field('product_id','关联我司产品',true).label }}<em v-if="field('product_id','关联我司产品',true).required">*</em></h3><p class="step-note">选择竞品所对应的我司产品，审核通过后将沉淀到该产品下。</p><div class="product-filters"><label><Search :size="14" /><input v-model="productQuery" class="control" placeholder="搜索产品简称、名称、编码、型号或品牌" /></label><AppSelect v-model="productDomain" class="control" @change="productLevelTwo='';productCategory='' "><option value="">全部一级分类</option><option v-for="value in productDomains" :key="value">{{ value }}</option></AppSelect><AppSelect v-model="productLevelTwo" class="control" @change="productCategory='' "><option value="">全部二级分类</option><option v-for="value in productLevelTwos" :key="value">{{ value }}</option></AppSelect><AppSelect v-model="productCategory" class="control"><option value="">全部三级分类</option><option v-for="value in productCategories" :key="value">{{ value }}</option></AppSelect></div><p class="result-count">找到 {{ visibleProducts.length }} 个产品</p><div class="product-grid"><button v-for="product in visibleProducts" :key="product.id" type="button" :class="{ active:form.productId===product.id }" @click="form.productId=product.id"><span><PackageSearch :size="17" /><img v-if="product.hasImage" :src="productImageUrl(product.id)" alt="" @error="$event.currentTarget.style.display='none'" /></span><div><b>{{ product.name }}</b><small>{{ product.fullName || product.model || '-' }} · {{ product.category || '-' }}</small></div><Check v-if="form.productId===product.id" :size="16" /></button></div></section>

      <section v-else-if="step === 2" class="analysis-layout"><div class="form-card"><h3>渠道与现场</h3><label v-if="field('dealer','现有经销商').enabled"><span>{{ field('dealer','现有经销商').label }}<em v-if="field('dealer','现有经销商').required">*</em></span><input v-model="form.dealer" class="control" /></label><label v-if="field('customer','现有客户').enabled"><span>{{ field('customer','现有客户').label }}<em v-if="field('customer','现有客户').required">*</em></span><input v-model="form.customer" class="control" /></label><label v-if="field('note','一线备注').enabled"><span>{{ field('note','一线备注').label }}<em v-if="field('note','一线备注').required">*</em></span><textarea v-model="form.note" class="control" /></label></div><div class="form-card"><h3>竞争判断</h3><label v-if="field('advantage','竞品优势').enabled"><span>{{ field('advantage','竞品优势').label }}<em v-if="field('advantage','竞品优势').required">*</em></span><textarea v-model="form.advantage" class="control" /></label><label v-if="field('weakness','竞品劣势').enabled"><span>{{ field('weakness','竞品劣势').label }}<em v-if="field('weakness','竞品劣势').required">*</em></span><textarea v-model="form.weakness" class="control" /></label><label v-if="field('tactic','销售应对策略').enabled"><span>{{ field('tactic','销售应对策略').label }}<em v-if="field('tactic','销售应对策略').required">*</em></span><textarea v-model="form.tactic" class="control" /></label></div><div v-if="field('competitor_parameters','竞品参数').enabled" class="form-card wide"><div class="card-head"><h3>{{ field('competitor_parameters','竞品参数').label }}<em v-if="field('competitor_parameters','竞品参数').required">*</em></h3></div><ParameterTextEditor v-model="form.competitorParameterText" :rows="8" /></div></section>

      <section v-else-if="step === 3"><h3>{{ field('material_category','资料归属',true).label }}<em v-if="field('material_category','资料归属',true).required">*</em></h3><p class="step-note">为每份资料选择归属，便于审核采纳、版本追溯和资料包沉淀。</p><div v-if="!files.length" class="no-files"><FileUp :size="22" /><b>尚未上传现场资料</b><span>本次没有附件，可直接继续提交。</span></div><div v-for="file in files" :key="fileKey(file)" class="category-row"><div><DesktopAttachmentThumbnail :file="file" :name="file.name" /><b>{{ file.name }}</b></div><div><button v-for="item in options.material_category || []" :key="item.id" type="button" :class="{ active:categories[fileKey(file)]===item.label }" @click="categories[fileKey(file)]=item.label">{{ item.label }}</button></div></div></section>

      <section v-else class="final-grid"><div class="form-card"><h3>地点、有效期与提醒</h3><div v-if="field('region','采集地区',true).enabled" class="searchable-field"><span class="field-label">{{ field('region','采集地区',true).label }}<em v-if="field('region','采集地区',true).required">*</em></span><SearchableSelect v-model="form.region" :options="options.region || []" placeholder="请选择采集地区" search-placeholder="搜索采集地区" aria-label="采集地区" /></div><label v-if="field('location','具体地点',true).enabled"><span>{{ field('location','具体地点',true).label }}<em v-if="field('location','具体地点',true).required">*</em></span><button type="button" class="location-button" @click="locationOpen=true"><MapPin :size="16" /><span>{{ form.location || '打开地图选择地点' }}</span></button></label><label v-if="field('validity','资料有效期').enabled"><span>{{ field('validity','资料有效期').label }}<em v-if="field('validity','资料有效期').required">*</em></span><AppSelect v-model="form.validity" class="control"><option v-for="item in options.validity || []" :key="item.id" :value="item.label">{{ item.label }}</option></AppSelect></label><label v-if="field('reminder_owner','到期提醒责任人').enabled"><span>{{ field('reminder_owner','到期提醒责任人').label }}<em v-if="field('reminder_owner','到期提醒责任人').required">*</em></span><AppSelect v-model="form.reminderOwner" class="control"><option v-for="item in options.reminder_owner || []" :key="item.id" :value="item.label">{{ item.label }}</option></AppSelect></label></div><div class="submit-summary"><DesktopLocationPreview v-if="form.latitude != null && form.longitude != null" :latitude="form.latitude" :longitude="form.longitude" /><div class="submit-summary-copy"><MapPin v-if="form.latitude == null || form.longitude == null" :size="24" /><h3>{{ form.location || '尚未选择地点' }}</h3><p>{{ form.region || '未选择地区' }} · {{ form.validity || '未设置有效期' }}</p><span>填写完成后提交审核，审核人员可退回补充、新建竞品或归并到已有竞品。</span></div></div></section>
      <p v-if="error" class="form-error">{{ error }}</p>
    </form>
    <template #footer><button v-if="draftId" type="button" class="btn btn-danger" @click="handleDiscardDraft">放弃草稿</button><button type="button" class="btn" :disabled="savingDraft" @click="handleSaveDraft">{{ savingDraft ? '保存中...' : '保存草稿' }}</button><button v-if="step>0" type="button" class="btn" @click="previous"><ChevronLeft :size="14" />上一步</button><button v-if="step<steps.length-1" type="button" class="btn btn-primary" @click="next">下一步<ChevronRight :size="14" /></button><button v-else type="submit" form="desktop-collection-form" class="btn btn-primary" :disabled="submitting">{{ submitting ? '提交中...' : '提交审核' }}</button></template>
  </AppModal>
  <DesktopLocationPicker v-if="locationOpen" :open="locationOpen" :initial="form" @close="locationOpen=false" @select="selectLocation" />
  <UnsavedChangesDialog :open="discardOpen" @cancel="discardOpen = false" @confirm="discardAndClose" />
</template>

<style scoped>
.stepper{display:flex;align-items:flex-start;margin:-20px -20px 18px;border-bottom:1px solid #dfe6ee;background:#f8fafc;padding:12px 18px}.stepper button{position:relative;display:flex;min-width:0;flex:1;align-items:center;gap:7px;border:0;background:transparent;padding:0;color:#94a3b8;text-align:left}.stepper button:not(:last-child)::after{content:"";height:1px;flex:1;background:#dfe6ee;margin-right:8px}.stepper button.done:not(:last-child)::after{background:#2563eb}.stepper button>span{display:grid;width:26px;height:26px;flex:0 0 auto;place-items:center;border-radius:50%;background:#e2e8f0;color:#64748b;font-size:10px;font-weight:800}.stepper button.active>span,.stepper button.done>span{background:#2563eb;color:#fff}.stepper b{overflow:hidden;max-width:100px;color:inherit;font-size:9px;text-overflow:ellipsis;white-space:nowrap}.stepper button.active b{color:#1d4ed8}.collection-form{min-height:430px}.collection-form h3{margin:0;font-size:13px}.collection-form em{margin-left:3px;color:#dc2626;font-style:normal}.step-one{display:grid;grid-template-columns:260px 1fr;gap:20px}.upload-column>h3{margin-bottom:8px}.upload-grid{display:grid;grid-template-columns:1fr 1fr;gap:7px}.upload-grid label{display:flex;min-height:88px;cursor:pointer;flex-direction:column;align-items:center;justify-content:center;gap:5px;border:1px dashed #93c5fd;border-radius:6px;background:#eff6ff55;color:#2563eb}.upload-grid label b{color:#334155;font-size:10px}.upload-grid label small{color:#94a3b8;font-size:8px}.upload-grid .wide{grid-column:1/-1}.selected-file{display:flex;align-items:center;justify-content:space-between;gap:7px;border-bottom:1px solid #edf1f5;padding:7px 2px;font-size:9px}.selected-file span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.selected-file button{border:0;background:transparent;color:#64748b}.selected-file.saved small{color:#2563eb}.basic-grid{display:grid;grid-template-columns:1fr 1fr;align-content:start;gap:13px}.collection-form label>span{display:block;margin-bottom:5px;color:#475569;font-size:10px;font-weight:700}.product-filters{display:grid;grid-template-columns:1fr 170px 170px;gap:7px;margin-top:12px}.product-filters label{position:relative}.product-filters label svg{position:absolute;z-index:1;top:11px;left:10px;color:#94a3b8}.product-filters label input{padding-left:31px}.step-note,.result-count{margin:5px 0 0;color:#64748b;font-size:9px}.result-count{margin:8px 0}.product-grid{display:grid;max-height:380px;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;overflow-y:auto}.product-grid>button{display:grid;min-width:0;grid-template-columns:44px minmax(0,1fr) auto;align-items:center;gap:8px;border:1px solid #dfe6ee;border-radius:6px;background:#fff;padding:9px;text-align:left}.product-grid>button.active{border-color:#2563eb;background:#eff6ff;box-shadow:0 0 0 2px #dbeafe}.product-grid>button>span{display:grid;width:44px;height:40px;place-items:center;border:1px solid #edf1f5;border-radius:5px;background:#fff;color:#cbd5e1}.product-grid b,.product-grid small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.product-grid b{font-size:10px}.product-grid small{margin-top:4px;color:#64748b;font-size:8px}.analysis-layout{display:grid;grid-template-columns:1fr 1fr;gap:10px}.form-card{border:1px solid #dfe6ee;border-radius:7px;background:#fff;padding:12px}.form-card.wide{grid-column:1/-1}.form-card>h3,.card-head{margin-bottom:10px}.form-card label{display:block;margin-top:9px}.form-card textarea{min-height:70px}.card-head{display:flex;align-items:center;justify-content:space-between}.parameter-row{display:grid;grid-template-columns:1fr 1.4fr 34px;gap:7px;margin-top:7px}.no-files{display:flex;min-height:230px;flex-direction:column;align-items:center;justify-content:center;gap:7px;border:1px dashed #cbd5e1;border-radius:7px;background:#f8fafc;color:#94a3b8}.no-files b{color:#475569;font-size:11px}.no-files span{font-size:9px}.category-row{display:grid;grid-template-columns:220px 1fr;gap:12px;align-items:center;border:1px solid #dfe6ee;border-radius:6px;margin-top:8px;padding:10px}.category-row>div:first-child{display:flex;min-width:0;align-items:center;gap:7px}.category-row b{overflow:hidden;font-size:10px;text-overflow:ellipsis;white-space:nowrap}.category-row>div:last-child{display:flex;flex-wrap:wrap;gap:5px}.category-row button{height:25px;border:1px solid #dfe6ee;border-radius:13px;background:#fff;padding:0 8px;color:#64748b;font-size:8px}.category-row button.active{border-color:#2563eb;background:#2563eb;color:#fff}.final-grid{display:grid;grid-template-columns:1fr 320px;gap:16px}.location-button{display:flex;width:100%;min-height:36px;align-items:center;gap:7px;border:1px solid #d9e1ea;border-radius:6px;background:#f8fafc;padding:0 10px;color:#475569;text-align:left}.location-button span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.submit-summary{display:flex;min-height:260px;flex-direction:column;align-items:center;justify-content:center;border:1px solid #dfe6ee;border-radius:7px;background:#f8fbff;padding:20px;text-align:center;color:#2563eb}.submit-summary h3{margin:11px 0 4px;color:#334155}.submit-summary p{margin:0;color:#64748b;font-size:9px}.submit-summary span{margin-top:14px;color:#94a3b8;font-size:9px;line-height:1.55}.form-error{margin:12px 0 0;border-radius:5px;background:#fff1f2;padding:8px 10px;color:#be123c;font-size:10px}
.submit-summary{display:block;overflow:hidden;padding:0}.submit-summary-copy{display:flex;min-height:90px;flex-direction:column;align-items:center;justify-content:center;padding:14px 20px}.submit-summary-copy h3{margin-top:7px}.submit-summary-copy span{margin-top:9px}
.stepper button>span{width:28px;height:28px;font-size:11px}.stepper b{max-width:112px;font-size:11px}.collection-form{min-height:450px}.upload-grid label{min-height:96px;gap:7px}.upload-grid label b{font-size:11px}.upload-grid label small{font-size:10px}.selected-file{display:grid;grid-template-columns:52px minmax(0,1fr) auto;min-height:58px;gap:9px;padding:7px 2px;font-size:10.5px}.selected-file :deep(.attachment-thumbnail){width:52px;height:44px}.selected-file>span{min-width:0}.selected-file button{display:grid;width:30px;height:30px;place-items:center;border-radius:5px}.selected-file button:hover{background:#f1f5f9}.selected-file.saved small{font-size:10px}.basic-grid{gap:16px}.collection-form label>span{margin-bottom:7px;font-size:11px}.step-note,.result-count{font-size:10.5px}.result-count{margin:10px 0}.product-grid{max-height:430px;gap:8px}.product-grid>button{grid-template-columns:56px minmax(0,1fr) auto;gap:12px;padding:12px}.product-grid>button>span{position:relative;width:56px;height:48px;overflow:hidden}.product-grid>button>span>img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:#fff}.product-grid b{font-size:12px}.product-grid small{font-size:10px}.analysis-layout{gap:16px}.form-card{padding:16px}.form-card>h3,.card-head{margin-bottom:14px}.form-card label{margin-top:12px}.form-card textarea{min-height:82px}.parameter-row{gap:9px;margin-top:9px}.no-files b{font-size:12px}.no-files span{font-size:10.5px}.category-row{grid-template-columns:260px 1fr;gap:16px;margin-top:10px;padding:12px}.category-row>div:first-child{gap:10px}.category-row :deep(.attachment-thumbnail){width:54px;height:46px}.category-row b{font-size:11px}.category-row button{height:30px;padding:0 10px;font-size:10px}.submit-summary p,.submit-summary span{font-size:10.5px}.form-error{font-size:11px}
.product-filters{grid-template-columns:minmax(240px,1fr) 145px 145px 145px}
.collection-form .searchable-field>.field-label{display:block;margin-bottom:7px;color:#475569;font-size:11px;font-weight:700}.searchable-field{margin-top:12px}
</style>
