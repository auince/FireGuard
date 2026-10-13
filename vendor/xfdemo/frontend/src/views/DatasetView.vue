<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { fetchUltraStrictSamples } from '@/api'
import { ultraStrictDataset, formatPercent } from '@/data/hydrantUltraStrictDataset'

const ui = {
  generated: '\u751f\u6210',
  inspected: '\u6838\u67e5',
  overview: '\u6570\u636e\u96c6\u603b\u89c8',
  totalRows: '\u5168\u96c6\u6837\u672c',
  nonCompliant: '\u4e0d\u5408\u89c4',
  compliant: '\u5408\u89c4',
  quality: '\u8d28\u91cf\u68c0\u67e5',
  fileSplit: '\u6587\u4ef6\u62c6\u5206',
  file: '\u6587\u4ef6',
  usage: '\u7528\u9014',
  rows: '\u6837\u672c',
  verdict: '\u4e0d\u5408\u89c4 / \u5408\u89c4',
  scope: '\u68c0\u67e5\u8303\u56f4',
  image: '\u56fe\u7247',
  cleaning: '\u6e05\u6d17\u7ed3\u8bba',
  result: '\u5408\u89c4\u7ed3\u8bba',
  scopeSection: '\u68c0\u67e5\u8303\u56f4',
  defects: '\u9690\u60a3\u7c7b\u522b',
  defectsHint: '\u6309\u5de1\u68c0\u4e1a\u52a1\u8bed\u4e49\u5f52\u7c7b\uff0c\u5408\u89c4\u6837\u672c\u5355\u72ec\u5217\u51fa\u3002',
  defectTotalHint: '\u7c7b\u522b\u8ba1\u6570\u4f1a\u5305\u542b\u591a\u6807\u7b7e\u6837\u672c\uff0c\u56e0\u6b64\u5404\u7c7b\u522b\u76f8\u52a0\u4e0d\u7b49\u4e8e\u6837\u672c\u603b\u6570\u3002',
  sources: '\u6570\u636e\u6765\u6e90',
  prompts: '\u539f\u59cb Prompt \u7248\u672c',
  gradients: '\u6e05\u6d17\u68af\u5ea6',
  quarantine: '\u9694\u79bb\u6837\u672c',
  sample: '\u6837\u4f8b\u8bb0\u5f55',
  id: 'ID',
  path: '\u56fe\u7247\u8def\u5f84',
  assistant: 'Assistant \u8f93\u51fa\u6458\u8981',
  appearance: '\u5916\u89c2',
  internal: '\u5185\u90e8',
  badJson: 'bad json',
  train: 'train',
  val: 'val',
  gallery: '\u56fe\u7247\u4e0e\u6807\u7b7e\u6d4f\u89c8',
  galleryHint: '\u6309\u6587\u4ef6\u3001\u4eba\u5de5\u7ed3\u8bba\u3001\u68c0\u67e5\u8303\u56f4\u548c\u9690\u60a3\u6807\u7b7e\u7b5b\u9009\uff0c\u76f4\u63a5\u67e5\u770b\u539f\u56fe\u548c\u6570\u636e\u96c6\u6807\u6ce8\u7ed3\u679c\u3002',
  split: '\u6587\u4ef6',
  all: '\u5168\u90e8',
  defectLabel: '\u9690\u60a3\u6807\u7b7e',
  keyword: '\u5173\u952e\u8bcd',
  keywordPlaceholder: '\u641c\u7d22 ID\u3001\u8def\u5f84\u3001\u6807\u7b7e\u6216\u6458\u8981',
  reset: '\u91cd\u7f6e',
  previous: '\u4e0a\u4e00\u9875',
  next: '\u4e0b\u4e00\u9875',
  loading: '\u6b63\u5728\u8bfb\u53d6\u6837\u672c...',
  noSamples: '\u6ca1\u6709\u5339\u914d\u7684\u6837\u672c',
  page: '\u9875',
  pageSize: '\u6bcf\u9875',
  firstPage: '\u9996\u9875',
  lastPage: '\u672b\u9875',
  total: '\u5171',
  source: '\u6765\u6e90',
  prompt: '\u539f\u59cb Prompt',
  resolution: '\u539f\u59cb\u5206\u8fa8\u7387',
  unknown: '\u672a\u77e5',
  trueLabel: '\u4eba\u5de5 / \u6570\u636e\u96c6\u6807\u7b7e',
  humanVerdict: '\u4eba\u5de5\u7ed3\u8bba',
  finetuneQa: '\u5fae\u8c03\u95ee\u7b54\u6837\u672c',
  promptVersionExamples: '\u539f\u59cb Prompt \u7248\u672c\u6837\u4f8b',
  versionCount: '\u6837\u672c\u6570',
  finetuneQuestion: '\u63d0\u95ee',
  finetuneAnswer: '\u56de\u7b54',
  labelCount: '\u9879',
  excerpt: '\u67e5\u770b\u5b8c\u6574\u8f93\u51fa'
}

const activeGroup = ref(ultraStrictDataset.defectGroups[0]?.name || '')

const activeDefectGroup = computed(() => {
  return ultraStrictDataset.defectGroups.find((group) => group.name === activeGroup.value)
})

const maxDefectValue = computed(() => {
  return Math.max(1, ...ultraStrictDataset.defectGroups.flatMap((group) => group.items.map((item) => item.value)))
})

const maxSourceValue = computed(() => {
  return Math.max(1, ...ultraStrictDataset.sourceDistribution.map((item) => item.value))
})

const maxPromptValue = computed(() => {
  return Math.max(1, ...ultraStrictDataset.promptVersions.map((item) => item.value))
})

const fileRows = computed(() => ultraStrictDataset.files.filter((file) => file.name !== 'quarantine_all_flagged.jsonl'))

const valueOf = (items, label) => items.find((item) => item.label === label)?.value || 0


const sampleFilters = ref({
  split: 'train',
  verdict: '',
  scope: '',
  defect: '',
  q: ''
})
const samplePage = ref(1)
const samplePageSize = ref(9)
const samplePayload = ref({ records: [], total: 0, page: 1, pages: 1 })
const selectedImage = ref(null)
const failedImages = ref(new Set())

const visibleSamplePages = computed(() => {
  const pages = samplePayload.value.pages || 1
  const current = samplePage.value
  const start = Math.max(1, current - 2)
  const end = Math.min(pages, current + 2)
  return Array.from({ length: end - start + 1 }, (_, index) => start + index)
})
const samplesLoading = ref(false)
const samplesError = ref('')

const defectOptions = computed(() => {
  const seen = new Set()
  return ultraStrictDataset.defectGroups.flatMap((group) => group.items)
    .filter((item) => {
      if (seen.has(item.label)) return false
      seen.add(item.label)
      return true
    })
})


const imageAspectRatio = (record) => {
  const width = Number(record.imageWidth) || 4
  const height = Number(record.imageHeight) || 3
  return `${width} / ${height}`
}

const boxStyle = (box) => ({
  left: `${box.left}%`,
  top: `${box.top}%`,
  width: `${box.width}%`,
  height: `${box.height}%`
})

const imageResolution = (record) => {
  const width = Number(record.imageWidth) || 0
  const height = Number(record.imageHeight) || 0
  return width > 0 && height > 0 ? `${width} x ${height}` : ui.unknown
}

const loadSamples = async () => {
  samplesLoading.value = true
  samplesError.value = ''
  try {
    samplePayload.value = await fetchUltraStrictSamples({
      ...sampleFilters.value,
      page: samplePage.value,
      page_size: samplePageSize.value
    })
  } catch (error) {
    samplesError.value = error.message || 'load samples failed'
  } finally {
    samplesLoading.value = false
  }
}

const resetSampleFilters = () => {
  sampleFilters.value = { split: 'train', verdict: '', scope: '', defect: '', q: '' }
  samplePage.value = 1
}

const setSamplePage = (page) => {
  const pages = samplePayload.value.pages || 1
  samplePage.value = Math.max(1, Math.min(pages, page))
}

const goSamplePage = (direction) => {
  setSamplePage(samplePage.value + direction)
}

const openImagePreview = (record) => {
  selectedImage.value = record
}

const closeImagePreview = () => {
  selectedImage.value = null
}

const markImageFailed = (url) => {
  failedImages.value = new Set([...failedImages.value, url])
}

const canShowImage = (record) => Boolean(record.imageUrl && !failedImages.value.has(record.imageUrl))

watch(sampleFilters, () => {
  samplePage.value = 1
  loadSamples()
}, { deep: true })

watch(samplePage, () => {
  loadSamples()
})

watch(samplePageSize, () => {
  samplePage.value = 1
  loadSamples()
})

onMounted(() => {
  loadSamples()
})
</script>

<template>
  <div class="dataset-page">
    <div class="dataset-page__container container">
      <header class="dataset-hero">
        <div>
          <p class="dataset-hero__eyebrow">{{ ultraStrictDataset.status }}</p>
          <h1 class="dataset-hero__title">{{ ultraStrictDataset.title }}</h1>
          <p class="dataset-hero__path">{{ ultraStrictDataset.path }}</p>
        </div>
        <div class="dataset-hero__meta">
          <span>{{ ui.generated }}: {{ ultraStrictDataset.generatedAt }}</span>
          <span>{{ ui.inspected }}: {{ ultraStrictDataset.inspectedAt }}</span>
        </div>
      </header>

      <section class="summary-grid" :aria-label="ui.overview">
        <article class="summary-card">
          <span class="summary-card__label">{{ ui.totalRows }}</span>
          <strong>{{ ultraStrictDataset.overview.totalRows }}</strong>
          <span>{{ ui.train }} {{ ultraStrictDataset.overview.trainRows }} / {{ ui.val }} {{ ultraStrictDataset.overview.valRows }}</span>
        </article>
        <article class="summary-card">
          <span class="summary-card__label">{{ ui.nonCompliant }}</span>
          <strong>{{ ultraStrictDataset.overview.nonCompliantRows }}</strong>
          <span>{{ formatPercent(ultraStrictDataset.overview.nonCompliantRows, ultraStrictDataset.overview.totalRows) }}</span>
        </article>
        <article class="summary-card">
          <span class="summary-card__label">{{ ui.compliant }}</span>
          <strong>{{ ultraStrictDataset.overview.compliantRows }}</strong>
          <span>{{ formatPercent(ultraStrictDataset.overview.compliantRows, ultraStrictDataset.overview.totalRows) }}</span>
        </article>
        <article class="summary-card">
          <span class="summary-card__label">{{ ui.quality }}</span>
          <strong>{{ ultraStrictDataset.overview.badJson }}</strong>
          <span>{{ ui.badJson }} / {{ ui.image }} {{ ultraStrictDataset.overview.imageCheck }}</span>
        </article>
      </section>

      <section class="dataset-section dataset-section--split">
        <div class="dataset-panel dataset-panel--wide">
          <div class="section-heading">
            <h2>{{ ui.fileSplit }}</h2>
            <p>{{ ultraStrictDataset.recommendation }}</p>
          </div>
          <div class="file-table" role="table">
            <div class="file-table__row file-table__row--head" role="row">
              <span>{{ ui.file }}</span>
              <span>{{ ui.usage }}</span>
              <span>{{ ui.rows }}</span>
              <span>{{ ui.verdict }}</span>
              <span>{{ ui.scope }}</span>
              <span>{{ ui.image }}</span>
            </div>
            <div v-for="file in fileRows" :key="file.name" class="file-table__row" role="row">
              <span class="file-table__name">{{ file.name }}</span>
              <span>{{ file.usage }}</span>
              <span>{{ file.rows }}</span>
              <span>{{ valueOf(file.verdict, ui.nonCompliant) }} / {{ valueOf(file.verdict, ui.compliant) }}</span>
              <span>{{ file.scope.map((item) => `${item.label} ${item.value}`).join(' / ') }}</span>
              <span>{{ file.imageCheck }}</span>
            </div>
          </div>
        </div>

        <aside class="dataset-panel">
          <div class="section-heading">
            <h2>{{ ui.cleaning }}</h2>
          </div>
          <ul class="note-list">
            <li v-for="note in ultraStrictDataset.notes" :key="note">{{ note }}</li>
          </ul>
        </aside>
      </section>

      <section class="dataset-section dataset-section--charts">
        <div class="dataset-panel">
          <div class="section-heading">
            <h2>{{ ui.result }}</h2>
          </div>
          <div class="bar-list">
            <div v-for="item in ultraStrictDataset.verdictDistribution" :key="item.label" class="bar-row">
              <div class="bar-row__top">
                <span>{{ item.label }}</span>
                <strong>{{ item.value }} / {{ formatPercent(item.value, ultraStrictDataset.overview.totalRows) }}</strong>
              </div>
              <div class="bar-row__track">
                <span class="bar-row__fill" :class="`bar-row__fill--${item.tone}`" :style="{ width: formatPercent(item.value, ultraStrictDataset.overview.totalRows) }"></span>
              </div>
            </div>
          </div>
        </div>

        <div class="dataset-panel">
          <div class="section-heading">
            <h2>{{ ui.scopeSection }}</h2>
          </div>
          <div class="scope-grid">
            <article v-for="item in ultraStrictDataset.scopeDistribution" :key="item.label" class="scope-item">
              <strong>{{ item.label }}</strong>
              <span>{{ item.value }} / {{ formatPercent(item.value, ultraStrictDataset.overview.totalRows) }}</span>
            </article>
          </div>
        </div>
      </section>

      <section class="dataset-section">
        <div class="dataset-panel dataset-panel--wide">
          <div class="section-heading section-heading--row">
            <div>
              <h2>{{ ui.defects }}</h2>
              <p>{{ ui.defectsHint }}</p>
            </div>
            <div class="segmented-control" :aria-label="ui.defects">
              <button
                v-for="group in ultraStrictDataset.defectGroups"
                :key="group.name"
                type="button"
                :class="{ 'segmented-control__button--active': activeGroup === group.name }"
                class="segmented-control__button"
                @click="activeGroup = group.name"
              >
                {{ group.name }}
              </button>
            </div>
          </div>

          <div v-if="activeDefectGroup" class="defect-layout">
            <div class="defect-total">
              <span>{{ activeDefectGroup.name }}</span>
              <strong>{{ activeDefectGroup.total }}</strong>
              <p>{{ ui.defectTotalHint }}</p>
            </div>
            <div class="defect-list">
              <div v-for="item in activeDefectGroup.items" :key="item.label" class="defect-row">
                <div class="defect-row__top">
                  <span>{{ item.label }}</span>
                  <strong>{{ item.value }}</strong>
                </div>
                <div class="bar-row__track">
                  <span class="bar-row__fill" :style="{ width: formatPercent(item.value, maxDefectValue) }"></span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>


      <section class="dataset-section">
        <div class="dataset-panel dataset-panel--wide">
          <div class="section-heading">
            <h2>{{ ui.gallery }}</h2>
            <p>{{ ui.galleryHint }}</p>
          </div>

          <div class="gallery-pager gallery-pager--top">
            <span class="gallery-pager__summary">{{ ui.total }} {{ samplePayload.pages || 1 }} {{ ui.page }}</span>
            <button class="gallery-pager__button" type="button" :disabled="samplePage <= 1 || samplesLoading" @click="setSamplePage(1)">{{ ui.firstPage }}</button>
            <button class="gallery-pager__button" type="button" :disabled="samplePage <= 1 || samplesLoading" @click="goSamplePage(-1)">{{ ui.previous }}</button>
            <button
              v-for="pageNumber in visibleSamplePages"
              :key="pageNumber"
              type="button"
              class="gallery-pager__button gallery-pager__number"
              :class="{ 'gallery-pager__number--active': pageNumber === samplePage }"
              @click="setSamplePage(pageNumber)"
            >
              {{ pageNumber }}
            </button>
            <button class="gallery-pager__button" type="button" :disabled="samplePage >= samplePayload.pages || samplesLoading" @click="goSamplePage(1)">{{ ui.next }}</button>
            <button class="gallery-pager__button" type="button" :disabled="samplePage >= samplePayload.pages || samplesLoading" @click="setSamplePage(samplePayload.pages || 1)">{{ ui.lastPage }}</button>
          </div>

          <div class="sample-toolbar">
            <label>
              <span>{{ ui.split }}</span>
              <select v-model="sampleFilters.split">
                <option value="train">train.jsonl</option>
                <option value="val">val.jsonl</option>
                <option value="all">all.jsonl</option>
                <option value="quarantine">quarantine</option>
              </select>
            </label>
            <label>
              <span>{{ ui.result }}</span>
              <select v-model="sampleFilters.verdict">
                <option value="">{{ ui.all }}</option>
                <option :value="ui.nonCompliant">{{ ui.nonCompliant }}</option>
                <option :value="ui.compliant">{{ ui.compliant }}</option>
              </select>
            </label>
            <label>
              <span>{{ ui.scope }}</span>
              <select v-model="sampleFilters.scope">
                <option value="">{{ ui.all }}</option>
                <option v-for="item in ultraStrictDataset.scopeDistribution" :key="item.label" :value="item.label">{{ item.label }}</option>
              </select>
            </label>
            <label>
              <span>{{ ui.defectLabel }}</span>
              <select v-model="sampleFilters.defect">
                <option value="">{{ ui.all }}</option>
                <option v-for="item in defectOptions" :key="item.label" :value="item.label">{{ item.label }}</option>
              </select>
            </label>
            <label class="sample-toolbar__search">
              <span>{{ ui.keyword }}</span>
              <input v-model.trim="sampleFilters.q" type="search" :placeholder="ui.keywordPlaceholder" />
            </label>
            <label>
              <span>{{ ui.pageSize }}</span>
              <select v-model.number="samplePageSize">
                <option :value="9">9</option>
                <option :value="18">18</option>
                <option :value="45">45</option>
              </select>
            </label>
            <button class="gallery-pager__button" type="button" @click="resetSampleFilters">{{ ui.reset }}</button>
          </div>

          <div class="sample-browser-status">
            <span v-if="samplesLoading">{{ ui.loading }}</span>
            <span v-else-if="samplesError">{{ samplesError }}</span>
            <span v-else>{{ ui.total }} {{ samplePayload.total }} {{ ui.rows }} / {{ ui.page }} {{ samplePayload.page }} / {{ samplePayload.pages || 1 }}</span>
          </div>

          <div v-if="!samplesLoading && samplePayload.records.length === 0" class="sample-empty">{{ ui.noSamples }}</div>
          <div class="sample-card-grid">
            <article v-for="record in samplePayload.records" :key="`${record.split}-${record.id}-${record.imagePath}`" class="sample-card">
              <div class="sample-card__image-wrap">
                <button class="sample-card__image-button" type="button" @click="openImagePreview(record)">
                  <div class="sample-card__image-canvas" :style="{ aspectRatio: imageAspectRatio(record) }">
                    <img
                      v-if="canShowImage(record)"
                      :src="record.imageUrl"
                      :alt="record.id"
                      class="sample-card__image"
                      loading="lazy"
                      @error="markImageFailed(record.imageUrl)"
                    />
                    <div v-else class="sample-image-fallback">图片加载失败</div>
                  <template v-if="record.annotationBoxes?.length">
                    <div
                      v-for="(box, index) in record.annotationBoxes"
                      :key="`${record.id}-box-${index}`"
                      class="sample-annotation-box"
                      :style="boxStyle(box)"
                    >
                      <span>{{ box.label }}</span>
                    </div>
                  </template>
                    <div v-else class="sample-image-labels">
                      <span v-for="label in record.trueLabels" :key="`image-label-${label}`">{{ label }}</span>
                    </div>
                  </div>
                </button>
              </div>
              <div class="sample-card__body">
                <div class="sample-card__topline">
                  <strong>{{ record.id }}</strong>
                  <span :class="['sample-badge', record.verdict === ui.compliant ? 'sample-badge--ok' : 'sample-badge--bad']">{{ ui.humanVerdict }}: {{ record.verdict }}</span>
                </div>
                <div class="sample-card__meta">
                  <span>{{ record.split }}</span>
                  <span>{{ ui.source }}: {{ record.trueLabelSource }}</span>
                </div>
                <div class="sample-card__label-compare">
                  <section class="sample-label-panel sample-label-panel--truth">
                    <div class="sample-label-panel__head">
                      <strong>{{ ui.trueLabel }} {{ record.trueLabels?.length || 0 }} {{ ui.labelCount }}</strong>
                      <small>{{ record.verdict }} / {{ record.scope }}</small>
                    </div>
                    <div class="sample-card__labels sample-card__labels--truth">
                      <span v-for="label in record.trueLabels" :key="`truth-${label}`">{{ label }}</span>
                    </div>
                  </section>
                </div>
                <dl class="sample-card__details">
                  <div>
                    <dt>{{ ui.source }}</dt>
                    <dd>{{ record.sourceDataset }}</dd>
                  </div>
                  <div>
                    <dt>{{ ui.prompt }}</dt>
                    <dd>{{ record.promptVersion }}</dd>
                  </div>
                  <div>
                    <dt>{{ ui.resolution }}</dt>
                    <dd>{{ imageResolution(record) }}</dd>
                  </div>
                  <div>
                    <dt>{{ ui.path }}</dt>
                    <dd>{{ record.imagePath }}</dd>
                  </div>
                </dl>
              </div>
            </article>
          </div>
          <div v-if="samplePayload.records.length" class="gallery-pager gallery-pager--bottom">
            <span class="gallery-pager__summary">{{ ui.total }} {{ samplePayload.pages || 1 }} {{ ui.page }}</span>
            <button class="gallery-pager__button" type="button" :disabled="samplePage <= 1 || samplesLoading" @click="setSamplePage(1)">{{ ui.firstPage }}</button>
            <button class="gallery-pager__button" type="button" :disabled="samplePage <= 1 || samplesLoading" @click="goSamplePage(-1)">{{ ui.previous }}</button>
            <button
              v-for="pageNumber in visibleSamplePages"
              :key="`bottom-${pageNumber}`"
              type="button"
              class="gallery-pager__button gallery-pager__number"
              :class="{ 'gallery-pager__number--active': pageNumber === samplePage }"
              @click="setSamplePage(pageNumber)"
            >
              {{ pageNumber }}
            </button>
            <button class="gallery-pager__button" type="button" :disabled="samplePage >= samplePayload.pages || samplesLoading" @click="goSamplePage(1)">{{ ui.next }}</button>
            <button class="gallery-pager__button" type="button" :disabled="samplePage >= samplePayload.pages || samplesLoading" @click="setSamplePage(samplePayload.pages || 1)">{{ ui.lastPage }}</button>
          </div>
        </div>
      </section>

      <section class="dataset-section dataset-section--split">
        <div class="dataset-panel">
          <div class="section-heading">
            <h2>{{ ui.sources }}</h2>
          </div>
          <div class="bar-list">
            <div v-for="item in ultraStrictDataset.sourceDistribution" :key="item.label" class="source-row">
              <div class="bar-row__top">
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
              </div>
              <div class="bar-row__track">
                <span class="bar-row__fill bar-row__fill--info" :style="{ width: formatPercent(item.value, maxSourceValue) }"></span>
              </div>
            </div>
          </div>
        </div>

        <div class="dataset-panel">
          <div class="section-heading">
            <h2>{{ ui.prompts }}</h2>
          </div>
          <div class="bar-list">
            <div v-for="item in ultraStrictDataset.promptVersions" :key="item.label" class="prompt-row">
              <div class="bar-row__top">
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
              </div>
              <div class="bar-row__track">
                <span class="bar-row__fill bar-row__fill--warning" :style="{ width: formatPercent(item.value, maxPromptValue) }"></span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section class="dataset-section dataset-section--split">
        <div class="dataset-panel">
          <div class="section-heading">
            <h2>{{ ui.gradients }}</h2>
          </div>
          <div class="version-list">
            <article v-for="item in ultraStrictDataset.relatedVersions" :key="item.name" class="version-item">
              <div>
                <strong>{{ item.name }}</strong>
                <span>{{ item.trainVal }} / {{ item.noise }}</span>
              </div>
              <div>
                <strong>{{ item.rows }}</strong>
                <span>{{ item.position }}</span>
              </div>
            </article>
          </div>
        </div>

        <div class="dataset-panel">
          <div class="section-heading">
            <h2>{{ ui.quarantine }}</h2>
            <p>{{ ultraStrictDataset.quarantine.reason }}</p>
          </div>
          <div class="quarantine-total">
            <strong>{{ ultraStrictDataset.quarantine.rows }}</strong>
            <span>quarantine_all_flagged.jsonl</span>
          </div>
          <div class="compact-list">
            <div v-for="item in ultraStrictDataset.quarantine.topDefects" :key="item.label" class="compact-list__item">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
            </div>
          </div>
        </div>
      </section>

      <section class="dataset-section">
        <div class="dataset-panel dataset-panel--wide sample-panel">
          <div class="section-heading">
            <h2>{{ ui.sample }}</h2>
          </div>
          <div class="sample-grid">
            <div class="sample-field">
              <span>{{ ui.id }}</span>
              <strong>{{ ultraStrictDataset.sample.id }}</strong>
            </div>
            <div class="sample-field">
              <span>{{ ui.result }}</span>
              <strong>{{ ultraStrictDataset.sample.verdict }}</strong>
            </div>
            <div class="sample-field">
              <span>{{ ui.scope }}</span>
              <strong>{{ ultraStrictDataset.sample.scope }}</strong>
            </div>
            <div class="sample-field sample-field--wide">
              <span>{{ ui.defects }}</span>
              <strong>{{ ultraStrictDataset.sample.defect }}</strong>
            </div>
            <div class="sample-field sample-field--wide">
              <span>{{ ui.path }}</span>
              <code>{{ ultraStrictDataset.sample.image }}</code>
            </div>
            <div class="sample-field sample-field--wide">
              <span>{{ ui.assistant }}</span>
              <p>{{ ultraStrictDataset.sample.assistant }}</p>
            </div>
          </div>
          <div class="prompt-version-samples">
            <h3>{{ ui.promptVersionExamples }}</h3>
            <details v-for="item in ultraStrictDataset.promptVersionSamples" :key="item.version" class="finetune-qa finetune-qa--version">
              <summary>
                <span>{{ item.version }}</span>
                <strong>{{ ui.versionCount }} {{ item.count }}</strong>
              </summary>
              <div class="prompt-version-sample__meta">
                <span>ID: {{ item.id }}</span>
                <span>{{ ui.humanVerdict }}: {{ item.verdict }}</span>
                <span>{{ ui.scope }}: {{ item.scope || ui.unknown }}</span>
              </div>
              <div class="prompt-version-sample__field">
                <span>{{ ui.defects }}</span>
                <p>{{ item.defect }}</p>
              </div>
              <div class="prompt-version-sample__field">
                <span>{{ ui.path }}</span>
                <code>{{ item.image }}</code>
              </div>
              <div class="finetune-qa__block">
                <strong>{{ ui.finetuneQuestion }}</strong>
                <p>{{ item.finetuneUser }}</p>
              </div>
              <div class="finetune-qa__block">
                <strong>{{ ui.finetuneAnswer }}</strong>
                <p>{{ item.finetuneAssistant }}</p>
              </div>
            </details>
          </div>
        </div>
      </section>
    </div>

    <div v-if="selectedImage" class="image-preview" @click.self="closeImagePreview">
      <div class="image-preview__dialog">
        <button class="image-preview__close" type="button" @click="closeImagePreview">x</button>
        <div class="image-preview__canvas" :style="{ aspectRatio: imageAspectRatio(selectedImage) }">
          <img
            v-if="canShowImage(selectedImage)"
            :src="selectedImage.imageUrl"
            :alt="selectedImage.id"
            class="image-preview__image"
            @error="markImageFailed(selectedImage.imageUrl)"
          />
          <div v-else class="sample-image-fallback">图片加载失败</div>
          <template v-if="selectedImage.annotationBoxes?.length">
            <div
              v-for="(box, index) in selectedImage.annotationBoxes"
              :key="`preview-box-${index}`"
              class="sample-annotation-box image-preview__box"
              :style="boxStyle(box)"
            >
              <span>{{ box.label }}</span>
            </div>
          </template>
        </div>
        <div class="image-preview__meta">
          <div>
            <strong>{{ selectedImage.id }}</strong>
            <span>{{ ui.humanVerdict }}: {{ selectedImage.verdict }}</span>
          </div>
          <div>
            <span>{{ ui.resolution }}: {{ imageResolution(selectedImage) }}</span>
            <span>{{ ui.scope }}: {{ selectedImage.scope }}</span>
          </div>
          <div class="image-preview__labels">
            <span v-for="label in selectedImage.trueLabels" :key="`preview-label-${label}`">{{ label }}</span>
          </div>
          <code>{{ selectedImage.imagePath }}</code>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dataset-page {
  min-height: 100vh;
  padding: 96px 0 40px;
  background: var(--bg-secondary);
}

.dataset-page__container {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.dataset-hero {
  display: flex;
  justify-content: space-between;
  gap: var(--spacing-xl);
  align-items: flex-end;
  padding-bottom: var(--spacing-md);
  border-bottom: 1px solid var(--color-gray-200);
}

.dataset-hero__eyebrow {
  display: inline-flex;
  margin-bottom: var(--spacing-sm);
  color: var(--color-primary);
  font-size: var(--font-size-sm);
  font-weight: 600;
}

.dataset-hero__title {
  font-size: var(--font-size-3xl);
  line-height: 1.2;
  color: var(--text-primary);
  margin-bottom: var(--spacing-sm);
}

.dataset-hero__path {
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
  word-break: break-all;
}

.dataset-hero__meta {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
  align-items: flex-end;
  color: var(--text-tertiary);
  font-size: var(--font-size-sm);
  white-space: nowrap;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--spacing-md);
}

.summary-card,
.dataset-panel {
  background: var(--bg-primary);
  border: 1px solid var(--color-gray-200);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-sm);
}

.summary-card {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
}

.summary-card__label,
.sample-field span,
.version-item span,
.quarantine-total span {
  color: var(--text-tertiary);
  font-size: var(--font-size-sm);
}

.summary-card strong {
  font-size: var(--font-size-3xl);
  line-height: 1;
  color: var(--text-primary);
}

.summary-card span:last-child {
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
}

.dataset-section {
  display: grid;
  gap: var(--spacing-lg);
}

.dataset-section--split,
.dataset-section--charts {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.dataset-section--charts {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.dataset-panel {
  padding: 24px;
  min-width: 0;
}

.section-heading {
  margin-bottom: var(--spacing-lg);
}

.section-heading--row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--spacing-lg);
}

.section-heading h2 {
  font-size: var(--font-size-xl);
  line-height: 1.25;
  margin-bottom: var(--spacing-xs);
}

.section-heading p {
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
}

.file-table {
  width: 100%;
  overflow-x: auto;
}

.file-table__row {
  display: grid;
  grid-template-columns: minmax(210px, 1.4fr) minmax(130px, 0.8fr) 90px minmax(130px, 1fr) minmax(170px, 1.1fr) 90px;
  gap: var(--spacing-md);
  align-items: center;
  padding: var(--spacing-md) 0;
  border-bottom: 1px solid var(--color-gray-100);
  min-width: 900px;
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
}

.file-table__row--head {
  color: var(--text-tertiary);
  font-weight: 600;
  padding-top: 0;
}

.file-table__name {
  color: var(--text-primary);
  font-weight: 600;
}

.note-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
  color: var(--text-secondary);
  padding-left: var(--spacing-lg);
}

.bar-list,
.defect-list,
.compact-list,
.version-list {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
}

.bar-row__top,
.defect-row__top,
.compact-list__item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) max-content;
  gap: var(--spacing-md);
  align-items: start;
  margin-bottom: var(--spacing-xs);
}

.bar-row__top span,
.defect-row__top span,
.compact-list__item span {
  min-width: 0;
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
  line-height: 1.45;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.bar-row__top strong,
.defect-row__top strong,
.compact-list__item strong {
  color: var(--text-primary);
  white-space: nowrap;
  justify-self: end;
}

.bar-row__track {
  width: 100%;
  height: 8px;
  background: var(--color-gray-100);
  border-radius: var(--radius-full);
  overflow: hidden;
}

.bar-row__fill {
  display: block;
  height: 100%;
  border-radius: var(--radius-full);
  background: var(--color-primary);
}

.bar-row__fill--danger {
  background: var(--color-primary);
}

.bar-row__fill--success {
  background: var(--color-success);
}

.bar-row__fill--info {
  background: var(--color-info);
}

.bar-row__fill--warning {
  background: var(--color-warning);
}

.scope-grid {
  display: grid;
  gap: var(--spacing-md);
}

.scope-item {
  padding: var(--spacing-md);
  border: 1px solid var(--color-gray-100);
  border-radius: var(--radius-lg);
  background: var(--bg-secondary);
}

.scope-item strong,
.scope-item span {
  display: block;
}

.scope-item span {
  color: var(--color-primary);
  font-size: var(--font-size-sm);
  margin-top: var(--spacing-xs);
}

.segmented-control {
  display: inline-flex;
  gap: var(--spacing-xs);
  padding: var(--spacing-xs);
  background: var(--bg-secondary);
  border-radius: var(--radius-full);
  border: 1px solid var(--color-gray-100);
}

.segmented-control__button {
  padding: var(--spacing-sm) var(--spacing-md);
  border-radius: var(--radius-full);
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
  white-space: nowrap;
}

.segmented-control__button--active {
  background: var(--color-primary);
  color: var(--text-inverse);
}

.defect-layout {
  display: grid;
  grid-template-columns: minmax(180px, 0.4fr) minmax(0, 1fr);
  gap: var(--spacing-xl);
  align-items: start;
}

.defect-total {
  padding: var(--spacing-lg);
  border-radius: var(--radius-lg);
  background: var(--color-primary-subtle);
}

.defect-total span,
.defect-total p {
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
}

.defect-total strong {
  display: block;
  font-size: var(--font-size-4xl);
  line-height: 1;
  margin: var(--spacing-sm) 0;
}

.version-item {
  display: flex;
  justify-content: space-between;
  gap: var(--spacing-lg);
  padding: var(--spacing-md);
  border: 1px solid var(--color-gray-100);
  border-radius: var(--radius-lg);
}

.version-item div {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
}

.version-item strong,
.version-item span {
  overflow-wrap: anywhere;
  word-break: break-word;
}

.version-item div:last-child {
  align-items: flex-end;
  text-align: right;
}

.quarantine-total {
  display: flex;
  align-items: baseline;
  gap: var(--spacing-md);
  margin-bottom: var(--spacing-lg);
}

.prompt-version-samples {
  margin-top: var(--spacing-lg);
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
}

.prompt-version-samples h3 {
  font-size: var(--font-size-lg);
  line-height: 1.35;
}

.finetune-qa--version summary {
  display: flex;
  justify-content: space-between;
  gap: var(--spacing-md);
  align-items: center;
}

.finetune-qa--version summary span {
  min-width: 0;
  overflow-wrap: anywhere;
}

.finetune-qa--version summary strong {
  flex: 0 0 auto;
  color: var(--text-primary);
  font-size: var(--font-size-sm);
}

.prompt-version-sample__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-sm);
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
}

.prompt-version-sample__field {
  display: grid;
  gap: var(--spacing-xs);
  margin-bottom: var(--spacing-sm);
}

.prompt-version-sample__field span {
  color: var(--text-tertiary);
  font-size: var(--font-size-sm);
}

.prompt-version-sample__field p,
.prompt-version-sample__field code {
  color: var(--text-secondary);
  white-space: normal;
  overflow-wrap: anywhere;
}

.quarantine-total strong {
  font-size: var(--font-size-4xl);
  line-height: 1;
  color: var(--color-primary);
}

.sample-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--spacing-md);
}

.sample-field {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
  padding: var(--spacing-md);
  border-radius: var(--radius-lg);
  background: var(--bg-secondary);
  min-width: 0;
}

.sample-field--wide {
  grid-column: 1 / -1;
}

.sample-field code,
.sample-field p {
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
  word-break: break-all;
}


.sample-toolbar {
  display: grid;
  grid-template-columns: repeat(4, minmax(140px, 1fr)) minmax(220px, 1.2fr) minmax(90px, 0.5fr) auto;
  gap: var(--spacing-md);
  align-items: end;
  margin-bottom: var(--spacing-md);
}

.sample-toolbar > * {
  min-width: 0;
}

.sample-toolbar label {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-xs);
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
}

.sample-toolbar select,
.sample-toolbar input {
  width: 100%;
  min-width: 0;
  min-height: 42px;
  border: 1px solid var(--color-gray-200);
  border-radius: var(--radius-lg);
  padding: 0 var(--spacing-md);
  background: var(--bg-primary);
  color: var(--text-primary);
  outline: none;
}

.sample-toolbar select:focus,
.sample-toolbar input:focus {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-subtle);
}

.gallery-pager {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
  max-width: 100%;
  overflow-x: auto;
  overflow-y: hidden;
  padding-bottom: 2px;
  scrollbar-width: thin;
}

.gallery-pager__summary {
  flex: 0 0 auto;
  min-height: 38px;
  display: inline-flex;
  align-items: center;
  padding: 0 var(--spacing-sm);
  color: var(--text-secondary);
  white-space: nowrap;
}

.gallery-pager__button {
  flex: 0 0 auto;
  min-height: 38px;
  min-width: 58px;
  padding: 0 var(--spacing-md);
  white-space: nowrap;
  word-break: keep-all;
  border-radius: var(--radius-md);
  background: var(--bg-secondary);
  color: var(--text-primary);
  border: 1px solid var(--color-gray-200);
}

.gallery-pager__button:disabled {
  color: var(--text-tertiary);
  cursor: not-allowed;
}

.gallery-pager__number {
  min-width: 38px;
  padding: 0 var(--spacing-sm);
}

.gallery-pager__number--active {
  background: var(--color-primary);
  color: var(--text-inverse);
  border-color: var(--color-primary);
}

.gallery-pager--top {
  justify-content: flex-end;
  margin: calc(-1 * var(--spacing-sm)) 0 var(--spacing-md);
}

.gallery-pager--bottom {
  justify-content: center;
  margin-top: var(--spacing-lg);
}

.sample-browser-status {
  min-height: 24px;
  margin-bottom: var(--spacing-md);
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
}

.sample-empty {
  padding: var(--spacing-xl);
  text-align: center;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  border-radius: var(--radius-lg);
}

.sample-card-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--spacing-lg);
}

.sample-card {
  border: 1px solid var(--color-gray-100);
  border-radius: var(--radius-xl);
  overflow: hidden;
  background: var(--bg-primary);
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.sample-card__image-wrap {
  aspect-ratio: 4 / 3;
  display: grid;
  place-items: center;
  padding: var(--spacing-sm);
  background: var(--bg-tertiary);
  border-bottom: 1px solid var(--color-gray-100);
}

.sample-card__image-button {
  width: 100%;
  height: 100%;
  display: grid;
  place-items: center;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: zoom-in;
}

.sample-card__image-button:focus-visible {
  outline: 3px solid var(--color-primary-subtle);
  outline-offset: 2px;
}

.sample-card__image-canvas {
  position: relative;
  max-width: 100%;
  max-height: 100%;
  width: 100%;
  background: #111;
  overflow: hidden;
}

.sample-card__image {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: fill;
}

.sample-image-fallback {
  min-height: 140px;
  display: grid;
  place-items: center;
  padding: 16px;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  text-align: center;
}

.sample-annotation-box {
  position: absolute;
  min-width: 18px;
  min-height: 18px;
  border: 2px solid #E53935;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.5), inset 0 0 0 1px rgba(0, 0, 0, 0.25);
  pointer-events: none;
}

.sample-annotation-box span {
  position: absolute;
  left: -2px;
  bottom: 100%;
  max-width: min(260px, 70vw);
  padding: 3px var(--spacing-xs);
  border-radius: var(--radius-sm) var(--radius-sm) var(--radius-sm) 0;
  background: rgba(183, 28, 28, 0.92);
  color: #fff;
  font-size: 11px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.sample-image-labels {
  position: absolute;
  left: var(--spacing-xs);
  top: var(--spacing-xs);
  right: var(--spacing-xs);
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-xs);
  align-items: flex-start;
}

.sample-image-labels span {
  max-width: 100%;
  padding: 3px var(--spacing-xs);
  border-radius: var(--radius-sm);
  background: rgba(13, 71, 161, 0.88);
  color: #fff;
  font-size: 11px;
  line-height: 1.35;
  overflow-wrap: anywhere;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.28);
}

.sample-card__body {
  padding: var(--spacing-md);
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
}

.sample-card__topline,
.sample-card__meta {
  display: flex;
  justify-content: space-between;
  gap: var(--spacing-sm);
  align-items: center;
}

.sample-card__topline strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sample-card__meta {
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
}

.sample-badge {
  flex: 0 0 auto;
  padding: 2px var(--spacing-sm);
  border-radius: var(--radius-full);
  font-size: var(--font-size-xs);
  color: var(--text-inverse);
  background: var(--color-primary);
}

.sample-badge--ok {
  background: var(--color-success);
}

.sample-badge--bad {
  background: var(--color-primary);
}

.sample-badge--match {
  background: var(--color-success);
}

.sample-badge--review {
  background: var(--color-warning);
}

.image-preview {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: grid;
  place-items: center;
  padding: var(--spacing-xl);
  background: rgba(17, 24, 39, 0.78);
}

.image-preview__dialog {
  position: relative;
  width: min(1120px, 96vw);
  max-height: 92vh;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: var(--spacing-lg);
  padding: var(--spacing-lg);
  border-radius: var(--radius-xl);
  background: var(--bg-primary);
  box-shadow: var(--shadow-lg);
  overflow: auto;
}

.image-preview__close {
  position: absolute;
  top: var(--spacing-sm);
  right: var(--spacing-sm);
  z-index: 2;
  width: 36px;
  height: 36px;
  border-radius: var(--radius-full);
  border: 1px solid var(--color-gray-200);
  background: var(--bg-primary);
  color: var(--text-primary);
  font-size: var(--font-size-lg);
  line-height: 1;
}

.image-preview__canvas {
  position: relative;
  width: 100%;
  max-height: 78vh;
  align-self: start;
  background: #111;
  overflow: hidden;
}

.image-preview__image {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: fill;
}

.image-preview__box {
  border-width: 3px;
}

.image-preview__meta {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--spacing-md);
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
  padding-right: var(--spacing-lg);
}

.image-preview__meta strong {
  display: block;
  color: var(--text-primary);
  font-size: var(--font-size-lg);
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.image-preview__meta code {
  padding: var(--spacing-sm);
  border-radius: var(--radius-md);
  background: var(--bg-secondary);
  color: var(--text-secondary);
  white-space: normal;
  overflow-wrap: anywhere;
}

.image-preview__labels {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-xs);
}

.image-preview__labels span {
  padding: 4px var(--spacing-sm);
  border-radius: var(--radius-full);
  background: var(--color-primary-subtle);
  color: var(--color-primary-dark);
  line-height: 1.35;
}


.sample-card__label-compare {
  display: grid;
  gap: var(--spacing-sm);
}

.sample-label-panel {
  min-width: 0;
  padding: var(--spacing-sm);
  border: 1px solid var(--color-gray-100);
  border-radius: var(--radius-lg);
  background: var(--bg-secondary);
}

.sample-label-panel--truth {
  border-color: rgba(30, 136, 229, 0.28);
  background: #F4F9FF;
}

.sample-label-panel__head {
  display: flex;
  justify-content: space-between;
  gap: var(--spacing-sm);
  align-items: flex-start;
  margin-bottom: var(--spacing-xs);
}

.sample-label-panel__head strong {
  color: var(--text-primary);
  font-size: var(--font-size-sm);
}

.sample-label-panel__head small {
  min-width: 0;
  color: var(--text-tertiary);
  font-size: var(--font-size-xs);
  line-height: 1.4;
  text-align: right;
  overflow-wrap: anywhere;
}

.sample-card__labels {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-xs);
}

.sample-card__labels span {
  max-width: 100%;
  padding: 2px var(--spacing-sm);
  border-radius: var(--radius-full);
  background: var(--color-primary-subtle);
  color: var(--color-primary-dark);
  font-size: var(--font-size-xs);
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.sample-card__labels--truth span {
  background: #E3F2FD;
  color: #0D47A1;
}

.finetune-qa {
  border-top: 1px solid var(--color-gray-100);
  padding-top: var(--spacing-sm);
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
}

.finetune-qa--sample {
  margin-top: var(--spacing-md);
}

.finetune-qa summary {
  color: var(--color-primary);
  cursor: pointer;
  font-weight: 700;
}

.finetune-qa__block {
  margin-top: var(--spacing-sm);
  padding: var(--spacing-sm);
  border-radius: var(--radius-md);
  background: var(--bg-secondary);
}

.finetune-qa__block strong {
  display: block;
  color: var(--text-primary);
  margin-bottom: var(--spacing-xs);
}

.finetune-qa__block p {
  margin: 0;
  line-height: 1.7;
  white-space: normal;
  overflow-wrap: anywhere;
}

.sample-card__details {
  display: grid;
  gap: var(--spacing-xs);
  padding-top: var(--spacing-sm);
  border-top: 1px solid var(--color-gray-100);
}

.sample-card__details div {
  min-width: 0;
}

.sample-card__details dt {
  color: var(--text-tertiary);
  font-size: var(--font-size-xs);
}

.sample-card__details dd {
  color: var(--text-secondary);
  font-size: var(--font-size-xs);
  word-break: break-all;
}

@media (max-width: 1024px) {
  .summary-grid,
  .dataset-section--charts,
  .dataset-section--split {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .dataset-section--split .dataset-panel--wide {
    grid-column: 1 / -1;
  }
}

@media (max-width: 768px) {
  .dataset-hero,
  .section-heading--row,
  .defect-layout {
    display: flex;
    flex-direction: column;
  }

  .dataset-hero {
    align-items: flex-start;
  }

  .dataset-hero__meta {
    align-items: flex-start;
  }

  .summary-grid,
  .dataset-section--charts,
  .dataset-section--split,
  .sample-grid {
    grid-template-columns: 1fr;
  }

  .segmented-control {
    width: 100%;
    overflow-x: auto;
    border-radius: var(--radius-lg);
  }

  .sample-toolbar,
  .sample-card-grid {
    grid-template-columns: 1fr;
  }

  .dataset-panel {
    overflow: hidden;
  }

  .gallery-pager {
    justify-content: flex-start;
  }

  .image-preview {
    padding: var(--spacing-md);
  }

  .image-preview__dialog {
    grid-template-columns: 1fr;
  }
}
</style>
