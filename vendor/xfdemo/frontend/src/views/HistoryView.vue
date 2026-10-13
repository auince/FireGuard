<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ChevronDown, ClipboardCheck, FileText, History, Pencil, Workflow } from 'lucide-vue-next'
import {
  clearInspectionHistory,
  createInspectionRevision,
  deleteInspectionHistory,
  fetchInspectionHistory
} from '@/api'
import ReportViewer from '@/components/report/ReportViewer.vue'
import ReportRevisionDialog from '@/components/report/ReportRevisionDialog.vue'
import RevisionTimeline from '@/components/report/RevisionTimeline.vue'

const ui = {
  title: '\u68c0\u6d4b\u5386\u53f2',
  subtitle: '\u67e5\u770b\u5df2\u7ecf\u68c0\u6d4b\u8fc7\u7684\u6d88\u9632\u6813\u56fe\u7247\u3001\u7ed3\u8bba\u548c\u5b8c\u6574\u62a5\u544a\u3002',
  total: '\u5171',
  rows: '\u6761\u8bb0\u5f55',
  page: '\u9875',
  all: '\u5168\u90e8',
  verdict: '\u68c0\u6d4b\u7ed3\u8bba',
  keyword: '\u5173\u952e\u8bcd',
  keywordPlaceholder: '\u641c\u7d22 ID\u3001\u56fe\u7247\u540d\u3001\u6807\u7b7e\u6216\u62a5\u544a\u5185\u5bb9',
  reset: '\u91cd\u7f6e',
  clearAll: '\u6e05\u7a7a\u5386\u53f2',
  clearConfirm: '\u786e\u5b9a\u6e05\u7a7a\u6240\u6709\u68c0\u6d4b\u5386\u53f2\u5417\uff1f',
  clearing: '\u6e05\u7a7a\u4e2d...',
  yoloPreview: '\u7ec4\u4ef6\u6807\u8bb0',
  loading: '\u6b63\u5728\u8bfb\u53d6\u68c0\u6d4b\u5386\u53f2...',
  empty: '\u6682\u65e0\u68c0\u6d4b\u5386\u53f2\uff0c\u5b8c\u6210\u4e00\u6b21\u667a\u80fd\u68c0\u6d4b\u540e\u4f1a\u81ea\u52a8\u51fa\u73b0\u5728\u8fd9\u91cc\u3002',
  compliant: '\u5408\u683c',
  nonCompliant: '\u4e0d\u5408\u683c',
  unknown: '\u672a\u77e5',
  scope: '\u68c0\u67e5\u8303\u56f4',
  labels: '\u9690\u60a3\u6807\u7b7e',
  noLabels: '\u65e0\u9690\u60a3\u6807\u7b7e',
  report: '\u5b8c\u6574\u62a5\u544a',
  query: '\u68c0\u6d4b\u4efb\u52a1',
  image: '\u68c0\u6d4b\u56fe\u7247',
  createdAt: '\u68c0\u6d4b\u65f6\u95f4',
  firstPage: '\u9996\u9875',
  previous: '\u4e0a\u4e00\u9875',
  next: '\u4e0b\u4e00\u9875',
  lastPage: '\u672b\u9875',
  delete: '\u5220\u9664',
  deleteConfirm: '\u786e\u5b9a\u5220\u9664\u8fd9\u6761\u68c0\u6d4b\u5386\u53f2\u5417\uff1f',
  deleting: '\u5220\u9664\u4e2d...',
  traceTitle: '\u5904\u7406\u8bb0\u5f55',
  traceEmpty: '\u6682\u65e0\u5904\u7406\u8bb0\u5f55',
  reportHint: '\u7ed3\u8bba\u4e0e\u5b8c\u6574\u8bf4\u660e'
}
const filters = ref({ verdict: '', q: '' })
const page = ref(1)
const pageSize = ref(12)
const payload = ref({ records: [], total: 0, page: 1, pages: 1 })
const loading = ref(false)
const error = ref('')
const selectedImage = ref(null)
const deletingId = ref('')
const clearingAll = ref(false)
const failedImages = ref(new Set())
const revisionRecord = ref(null)
const revisionSaving = ref(false)
const revisionError = ref('')
const revisionMessage = ref('')

const visiblePages = computed(() => {
  const pages = payload.value.pages || 1
  const current = page.value
  const start = Math.max(1, current - 2)
  const end = Math.min(pages, current + 2)
  return Array.from({ length: end - start + 1 }, (_, index) => start + index)
})

const loadHistory = async () => {
  loading.value = true
  error.value = ''
  try {
    payload.value = await fetchInspectionHistory({
      ...filters.value,
      page: page.value,
      page_size: pageSize.value
    })
  } catch (err) {
    error.value = err.message || 'load history failed'
  } finally {
    loading.value = false
  }
}

const setPage = (target) => {
  const pages = payload.value.pages || 1
  page.value = Math.max(1, Math.min(pages, target))
}

const goPage = (direction) => setPage(page.value + direction)

const resetFilters = () => {
  filters.value = { verdict: '', q: '' }
  page.value = 1
}

const labelsOf = (record) => record.labels?.length ? record.labels : [ui.noLabels]
const traceStagesOf = (record) => record.trace?.stages || []
const traceIssuesOf = (record) => record.trace?.summary?.issues || []
const formatDuration = (value) => `${Number(value || 0)}ms`
const stageStatusText = (stage) => {
  if (stage?.superseded) return '\u672a\u91c7\u7eb3'
  if (stage?.status === 'warn') return '\u63d0\u9192'
  if (stage?.status === 'error') return '\u5f02\u5e38'
  if (stage?.status === 'skipped') return '\u8df3\u8fc7'
  return '\u6b63\u5e38'
}
const stageTitleOf = (stage) => {
  const name = String(stage?.name || '').toLowerCase()
  const signal = `${name} ${String(stage?.title || '').toLowerCase()}`
  if (name === 'qwen_first') return 'A \u00b7 \u57fa\u7840\u5206\u6790'
  if (signal.includes('missing') || signal.includes('\u7f3a\u5931')) return 'R1 \u00b7 \u5b8c\u6574\u6027\u6821\u9a8c'
  if (signal.includes('kink') || signal.includes('hose') || signal.includes('\u6298\u5f2f') || signal.includes('\u5f2f\u6298')) return 'R2 \u00b7 \u72b6\u6001\u6821\u9a8c'
  if (signal.includes('direction') || signal.includes('outlet') || signal.includes('\u65b9\u5411')) return 'R3 \u00b7 \u5b89\u88c5\u6821\u9a8c'
  if (name.startsWith('yolo_')) return 'B \u00b7 \u7279\u5f81\u6838\u9a8c'
  if (name.includes('review') || name.includes('judge')) return 'C \u00b7 \u4e00\u81f4\u6027\u6821\u9a8c'
  return 'C \u00b7 \u7ed3\u679c\u6821\u9a8c'
}
const issueTitleOf = (issue) => {
  const text = `${issue?.type || ''} ${issue?.title || ''}`.toLowerCase()
  if (text.includes('qwen') || text.includes('\u521d\u68c0')) return '\u521d\u6b65\u7ed3\u8bba\u5df2\u6821\u6b63'
  if (text.includes('yolo') || text.includes('\u68c0\u51fa')) return '\u5019\u9009\u8bc1\u636e\u672a\u91c7\u7eb3'
  if (text.includes('\u7f6e\u4fe1') || text.includes('confidence')) return '\u6821\u9a8c\u7f6e\u4fe1\u4e0d\u8db3'
  if (text.includes('\u7f3a\u5931') || text.includes('missing')) return '\u5b8c\u6574\u6027\u7ed3\u679c\u5df2\u590d\u67e5'
  return '\u9636\u6bb5\u7ed3\u679c\u5df2\u8c03\u6574'
}
const traceIssueTextOf = (record) => traceIssuesOf(record).map(issueTitleOf).join('、')
const stageMainText = (stage) => {
  if (stage.name === 'qwen_first') {
    const output = stage.output || {}
    return `${output.verdict || '\u672a\u89e3\u6790\u7ed3\u8bba'} / ${(output.labels || []).join('\uff1b') || '\u65e0\u6807\u7b7e'}`
  }
  if (String(stage.name || '').startsWith('yolo_')) {
    const summary = `\u8bc6\u522b\u5230 ${stage.detectionCount || 0} \u9879\u7ec4\u4ef6\u8bc1\u636e / ${(stage.labels || []).join('\uff1b') || '\u65e0\u6807\u7b7e'}`
    return stage.superseded ? `\u8be5\u9636\u6bb5\u7ed3\u679c\u672a\u91c7\u7eb3\uff1a${summary}` : summary
  }
  const output = stage.output || {}
  return `${output.verdict || '\u672a\u89e3\u6790\u7ed3\u8bba'} / ${(output.labels || []).join('\uff1b') || '\u65e0\u6807\u7b7e'}`
}
const previewUrlOf = (record) => record?.previewImageUrl || record?.imageUrl || ""

const yoloBoxesOf = (record) => {
  const width = Number(record?.yolo?.imageWidth || 0)
  const height = Number(record?.yolo?.imageHeight || 0)
  if (!width || !height) return []
  return (record?.yolo?.detections || []).map((item, index) => {
    let coords = Array.isArray(item?.bboxNorm) ? item.bboxNorm : []
    if (coords.length !== 4 && Array.isArray(item?.bbox) && item.bbox.length === 4) {
      coords = [
        Number(item.bbox[0]) / width,
        Number(item.bbox[1]) / height,
        Number(item.bbox[2]) / width,
        Number(item.bbox[3]) / height
      ]
    }
    if (coords.length !== 4) return null
    const [x1, y1, x2, y2] = coords.map((value) => Math.max(0, Math.min(1, Number(value) || 0)))
    if (x2 <= x1 || y2 <= y1) return null
    const confidence = Number(item?.confidence || 0)
    const label = item?.label || item?.className || ui.yoloPreview
    return {
      id: `${record?.id || 'record'}-${index}`,
      index: index + 1,
      label,
      confidence,
      legend: `${index + 1}. ${label}${confidence ? ` ${Math.round(confidence * 100)}%` : ''}`,
      left: `${x1 * 100}%`,
      top: `${y1 * 100}%`,
      width: `${(x2 - x1) * 100}%`,
      height: `${(y2 - y1) * 100}%`
    }
  }).filter(Boolean)
}

const hasYoloBoxes = (record) => yoloBoxesOf(record).length > 0
const yoloLegendOf = (record) => yoloBoxesOf(record).map((box) => box.legend)

const imageStyleOf = (record) => {
  const width = Number(record?.yolo?.imageWidth || 0)
  const height = Number(record?.yolo?.imageHeight || 0)
  if (width > 0 && height > 0) {
    return { aspectRatio: `${width} / ${height}` }
  }
  return {}
}

const boxStyleOf = (box) => ({
  left: box.left,
  top: box.top,
  width: box.width,
  height: box.height
})

const openImage = (record) => {
  if (previewUrlOf(record)) selectedImage.value = record
}
const closeImage = () => {
  selectedImage.value = null
}
const markImageFailed = (url) => {
  failedImages.value = new Set([...failedImages.value, url])
}
const canShowImage = (record) => {
  const url = previewUrlOf(record)
  return Boolean(url && !failedImages.value.has(url))
}

const reportRevisionCount = (record) => Number(record?.reportRevisionSummary?.count || 0)
const hasReportCorrection = (record) => Boolean(record?.reportRevisionSummary?.hasCorrection)
const latestReportRevision = (record) => record?.reportRevisionSummary?.latest || null
const reportRevisionsOf = (record) => record?.reportRevisions || []
const reviewNoteOf = (record) => record?.reviewNote || ''

const openRevisionDialog = (record) => {
  if (!record?.id || !record?.effectiveReportDocument) return
  revisionRecord.value = record
  revisionError.value = ''
  revisionMessage.value = ''
}

const closeRevisionDialog = () => {
  if (revisionSaving.value) return
  revisionRecord.value = null
  revisionError.value = ''
}

const saveReportRevision = async (revisionPayload) => {
  if (!revisionRecord.value?.id) return
  revisionSaving.value = true
  revisionError.value = ''
  try {
    const recordId = revisionRecord.value.id
    const saved = await createInspectionRevision(recordId, revisionPayload)
    const index = payload.value.records.findIndex((record) => record.id === recordId)
    if (index >= 0) {
      const current = payload.value.records[index]
      const verdictLabels = {
        qualified: ui.compliant,
        unqualified: ui.nonCompliant,
        unknown: ui.unknown
      }
      payload.value.records[index] = {
        ...current,
        ...saved,
        verdict: verdictLabels[saved.effectiveReportDocument?.verdict] || ui.unknown,
        labels: saved.reportRevisionSummary?.hasCorrection ? [] : current.labels
      }
    }
    revisionMessage.value = `记录 ${recordId} 的人工修订已保存`
    revisionRecord.value = null
  } catch (err) {
    revisionError.value = err.message || '保存人工修订失败'
  } finally {
    revisionSaving.value = false
  }
}

const deleteRecord = async (record) => {
  if (!record?.id || !window.confirm(ui.deleteConfirm)) return
  deletingId.value = record.id
  error.value = ''
  try {
    await deleteInspectionHistory(record.id)
    if (payload.value.records.length === 1 && page.value > 1) {
      page.value -= 1
    } else {
      await loadHistory()
    }
  } catch (err) {
    error.value = err.message || 'delete history failed'
  } finally {
    deletingId.value = ''
  }
}


const clearAllHistory = async () => {
  if (!payload.value.records.length || !window.confirm(ui.clearConfirm)) return
  clearingAll.value = true
  error.value = ''
  try {
    await clearInspectionHistory()
    selectedImage.value = null
    page.value = 1
    payload.value = { records: [], total: 0, page: 1, pages: 1 }
    failedImages.value = new Set()
    await loadHistory()
  } catch (err) {
    error.value = err.message || 'clear history failed'
  } finally {
    clearingAll.value = false
  }
}


watch(filters, () => {
  page.value = 1
  loadHistory()
}, { deep: true })

watch(page, loadHistory)
onMounted(loadHistory)
</script>

<template>
  <div class="history-page">
    <div class="history-page__container container">
      <header class="history-hero">
        <div>
          <span class="history-hero__eyebrow">History</span>
          <h1>{{ ui.title }}</h1>
          <p>{{ ui.subtitle }}</p>
        </div>
        <div class="history-hero__stat">
          <strong>{{ payload.total }}</strong>
          <span>{{ ui.rows }}</span>
        </div>
      </header>

      <section class="history-panel">
        <div class="history-toolbar">
          <label>
            <span>{{ ui.verdict }}</span>
            <select v-model="filters.verdict">
              <option value="">{{ ui.all }}</option>
              <option :value="ui.nonCompliant">{{ ui.nonCompliant }}</option>
              <option :value="ui.compliant">{{ ui.compliant }}</option>
            </select>
          </label>
          <label class="history-toolbar__search">
            <span>{{ ui.keyword }}</span>
            <input v-model.trim="filters.q" type="search" :placeholder="ui.keywordPlaceholder" />
          </label>
          <button class="history-button" type="button" @click="resetFilters">{{ ui.reset }}</button>
          <button class="history-button history-button--danger" type="button" :disabled="!payload.total || clearingAll" @click="clearAllHistory">{{ clearingAll ? ui.clearing : ui.clearAll }}</button>
        </div>

        <div class="history-status">
          <span v-if="loading">{{ ui.loading }}</span>
          <span v-else-if="error">{{ error }}</span>
          <span v-else-if="revisionMessage" class="history-status__success">{{ revisionMessage }}</span>
          <span v-else>{{ ui.total }} {{ payload.total }} {{ ui.rows }} / {{ payload.page }} / {{ payload.pages || 1 }} {{ ui.page }}</span>
        </div>

        <div v-if="!loading && payload.records.length === 0" class="history-empty">{{ ui.empty }}</div>

        <div class="history-grid">
          <article v-for="record in payload.records" :key="record.id" class="history-card">
            <button class="history-card__image" type="button" :style="imageStyleOf(record)" :disabled="!previewUrlOf(record)" @click="openImage(record)">
              <img
                v-if="canShowImage(record)"
                :src="previewUrlOf(record)"
                :alt="record.id"
                loading="lazy"
                @error="markImageFailed(previewUrlOf(record))"
              />
              <span v-else>{{ ui.image }}</span>
              <div v-if="hasYoloBoxes(record)" class="history-yolo-overlay">
                <div v-for="box in yoloBoxesOf(record)" :key="box.id" class="history-yolo-box" :style="boxStyleOf(box)">
                  <span>{{ box.index }}</span>
                </div>
              </div>
            </button>
            <div class="history-card__body">
              <div class="history-card__topline">
                <strong>{{ record.id }}</strong>
                <div class="history-card__actions">
                  <span :class="['history-badge', record.verdict === ui.compliant ? 'history-badge--ok' : 'history-badge--bad']">
                    {{ record.verdict || ui.unknown }}
                  </span>
                  <button class="history-edit" type="button" title="修订检测报告" @click="openRevisionDialog(record)">
                    <Pencil :size="14" :stroke-width="2" />
                    修订
                  </button>
                  <button class="history-delete" type="button" :disabled="deletingId === record.id" @click="deleteRecord(record)">
                    {{ deletingId === record.id ? ui.deleting : ui.delete }}
                  </button>
                </div>
              </div>
              <dl class="history-card__meta">
                <div>
                  <dt>{{ ui.createdAt }}</dt>
                  <dd>{{ record.createdText }}</dd>
                </div>
                <div>
                  <dt>{{ ui.scope }}</dt>
                  <dd>{{ record.scope || ui.unknown }}</dd>
                </div>
                <div>
                  <dt>{{ ui.query }}</dt>
                  <dd>{{ record.query }}</dd>
                </div>
              </dl>
              <div v-if="hasYoloBoxes(record)" class="history-card__hint">{{ ui.yoloPreview }}</div>
              <div v-if="hasYoloBoxes(record)" class="history-yolo-legend history-yolo-legend--card">
                <span v-for="item in yoloLegendOf(record).slice(0, 4)" :key="`${record.id}-${item}`">{{ item }}</span>
              </div>
              <div v-if="!hasReportCorrection(record)" class="history-labels">
                <span v-for="label in labelsOf(record)" :key="`${record.id}-${label}`">{{ label }}</span>
              </div>
              <p v-else class="history-card__manual-note">当前结论已人工修订，以完整报告为准。</p>
              <section :class="['history-review-note', { 'history-review-note--empty': !reviewNoteOf(record) }]">
                <div class="history-review-note__heading">
                  <span class="history-review-note__icon">
                    <ClipboardCheck :size="16" :stroke-width="2" />
                  </span>
                  <strong>复核说明</strong>
                  <span v-if="latestReportRevision(record)" class="history-review-note__meta">
                    {{ latestReportRevision(record).createdText }} ·
                    {{ latestReportRevision(record).editor?.name || '当前用户' }}
                  </span>
                </div>
                <p>{{ reviewNoteOf(record) || '当前记录尚未进行人工复核。' }}</p>
              </section>
              <details v-if="reportRevisionCount(record)" class="history-revisions">
                <summary class="history-action">
                  <span class="history-action__icon"><History :size="16" :stroke-width="2" /></span>
                  <strong class="history-action__label">修改记录</strong>
                  <span class="history-action__meta">{{ reportRevisionCount(record) }} 个人工版本</span>
                  <ChevronDown class="history-action__chevron" :size="16" :stroke-width="2" />
                </summary>
                <div class="history-revisions__body">
                  <RevisionTimeline :revisions="reportRevisionsOf(record)" />
                </div>
              </details>
              <details class="history-trace">
                <summary class="history-action">
                  <span class="history-action__icon"><Workflow :size="16" :stroke-width="2" /></span>
                  <strong class="history-action__label">{{ ui.traceTitle }}</strong>
                  <span class="history-action__meta">
                    {{ traceStagesOf(record).length }} 个阶段 ·
                    {{ formatDuration(record.trace?.summary?.totalDurationMs) }}
                  </span>
                  <ChevronDown class="history-action__chevron" :size="16" :stroke-width="2" />
                </summary>
                <div v-if="traceStagesOf(record).length" class="history-trace__body">
                  <div class="history-trace__summary">
                    <span>共 {{ traceStagesOf(record).length }} 个阶段</span>
                    <span>总耗时 {{ formatDuration(record.trace?.summary?.totalDurationMs) }}</span>
                    <span v-if="traceIssuesOf(record).length">{{ traceIssuesOf(record).length }} 项复核关注</span>
                  </div>
                  <ol class="history-trace__timeline">
                    <li
                      v-for="stage in traceStagesOf(record)"
                      :key="`${record.id}-${stage.name}`"
                      :class="['history-trace__stage', `history-trace__stage--${stage.status || 'ok'}`]"
                    >
                      <span class="history-trace__marker" aria-hidden="true"></span>
                      <div class="history-trace__stage-content">
                        <div class="history-trace__stage-heading">
                          <strong>{{ stageTitleOf(stage) }}</strong>
                          <span>{{ stageStatusText(stage) }} · {{ formatDuration(stage.durationMs) }}</span>
                        </div>
                        <p>{{ stageMainText(stage) }}</p>
                      </div>
                    </li>
                  </ol>
                  <p v-if="traceIssuesOf(record).length" class="history-trace__issues">
                    <strong>复核关注：</strong>
                    {{ traceIssueTextOf(record) }}
                  </p>
                </div>
                <p v-else class="history-trace__empty">{{ ui.traceEmpty }}</p>
              </details>
              <details class="history-report">
                <summary class="history-action">
                  <span class="history-action__icon"><FileText :size="16" :stroke-width="2" /></span>
                  <strong class="history-action__label">{{ ui.report }}</strong>
                  <span class="history-action__meta">{{ ui.reportHint }}</span>
                  <ChevronDown class="history-action__chevron" :size="16" :stroke-width="2" />
                </summary>
                <div class="history-report__content">
                  <ReportViewer
                    :document="record.effectiveReportDocument"
                    :text="record.effectiveResponse || record.response"
                    :revised="hasReportCorrection(record)"
                  />
                  <details v-if="hasReportCorrection(record)" class="history-report__original">
                    <summary>查看模型原始报告</summary>
                    <ReportViewer
                      :document="record.modelReportDocument"
                      :text="record.modelResponse || record.response"
                    />
                  </details>
                </div>
              </details>
            </div>
          </article>
        </div>

        <div v-if="payload.records.length" class="history-pager">
          <span>{{ ui.total }} {{ payload.pages || 1 }} {{ ui.page }}</span>
          <button class="history-button" type="button" :disabled="page <= 1 || loading" @click="setPage(1)">{{ ui.firstPage }}</button>
          <button class="history-button" type="button" :disabled="page <= 1 || loading" @click="goPage(-1)">{{ ui.previous }}</button>
          <button
            v-for="item in visiblePages"
            :key="item"
            class="history-button history-button--number"
            :class="{ 'history-button--active': item === page }"
            type="button"
            @click="setPage(item)"
          >
            {{ item }}
          </button>
          <button class="history-button" type="button" :disabled="page >= payload.pages || loading" @click="goPage(1)">{{ ui.next }}</button>
          <button class="history-button" type="button" :disabled="page >= payload.pages || loading" @click="setPage(payload.pages || 1)">{{ ui.lastPage }}</button>
        </div>
      </section>
    </div>

    <div v-if="selectedImage" class="history-preview" @click.self="closeImage">
      <div class="history-preview__dialog">
        <button class="history-preview__close" type="button" @click="closeImage">x</button>
        <div class="history-preview__image" :style="imageStyleOf(selectedImage)">
          <img
            v-if="canShowImage(selectedImage)"
            :src="previewUrlOf(selectedImage)"
            :alt="selectedImage.id"
            @error="markImageFailed(previewUrlOf(selectedImage))"
          />
          <span v-else>{{ ui.image }}</span>
          <div v-if="hasYoloBoxes(selectedImage)" class="history-yolo-overlay history-yolo-overlay--preview">
            <div v-for="box in yoloBoxesOf(selectedImage)" :key="box.id" class="history-yolo-box" :style="boxStyleOf(box)">
              <span>{{ box.index }}</span>
            </div>
          </div>
        </div>
        <div v-if="hasYoloBoxes(selectedImage)" class="history-yolo-legend history-yolo-legend--preview">
          <span v-for="item in yoloLegendOf(selectedImage)" :key="`${selectedImage.id}-${item}`">{{ item }}</span>
        </div>
        <div class="history-preview__meta">
          <strong>{{ selectedImage.id }}</strong>
          <span>{{ selectedImage.createdText }}</span>
          <span>{{ selectedImage.verdict || ui.unknown }} / {{ selectedImage.scope || ui.unknown }}</span>
        </div>
      </div>
    </div>

    <ReportRevisionDialog
      v-if="revisionRecord"
      :record="revisionRecord"
      :saving="revisionSaving"
      :error="revisionError"
      @save="saveReportRevision"
      @cancel="closeRevisionDialog"
    />
  </div>
</template>

<style scoped>
.history-page {
  min-height: 100vh;
  padding: 96px 0 40px;
  background: var(--bg-secondary);
}

.history-page__container {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.history-hero,
.history-panel,
.history-card {
  background: var(--bg-primary);
  border: 1px solid var(--color-gray-200);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-sm);
}

.history-hero {
  display: flex;
  justify-content: space-between;
  gap: var(--spacing-xl);
  padding: 24px 28px;
  align-items: flex-end;
}

.history-hero__eyebrow {
  color: var(--color-primary);
  font-size: var(--font-size-sm);
  font-weight: 600;
}

.history-hero h1 {
  margin: var(--spacing-xs) 0;
  font-size: var(--font-size-3xl);
  line-height: 1.2;
}

.history-hero p,
.history-status,
.history-card__meta,
.history-report__content {
  color: var(--text-secondary);
}

.history-hero__stat {
  text-align: right;
}

.history-hero__stat strong {
  display: block;
  font-size: var(--font-size-3xl);
  line-height: 1;
}

.history-panel {
  padding: 22px;
}

.history-toolbar {
  display: grid;
  grid-template-columns: minmax(160px, 220px) minmax(240px, 1fr) max-content max-content;
  gap: var(--spacing-md);
  align-items: end;
  margin-bottom: var(--spacing-md);
}

.history-toolbar label {
  display: grid;
  gap: var(--spacing-xs);
  color: var(--text-tertiary);
  font-size: var(--font-size-sm);
}

.history-toolbar select,
.history-toolbar input {
  min-height: 44px;
  border: 1px solid var(--color-gray-200);
  border-radius: var(--radius-lg);
  padding: 0 var(--spacing-md);
  background: var(--bg-primary);
  color: var(--text-primary);
}

.history-status {
  min-height: 24px;
  margin-bottom: var(--spacing-md);
  font-size: var(--font-size-sm);
}

.history-status__success {
  color: var(--color-success);
  font-weight: 650;
}

.history-empty {
  padding: var(--spacing-2xl);
  text-align: center;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  border-radius: var(--radius-lg);
}

.history-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.history-card {
  overflow: hidden;
  min-width: 0;
}

.history-card__image {
  position: relative;
  width: 100%;
  aspect-ratio: 4 / 3;
  display: grid;
  place-items: center;
  padding: 0;
  border: 0;
  background: var(--bg-tertiary);
  cursor: zoom-in;
}

.history-card__image:disabled {
  cursor: default;
}

.history-card__image img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  background: #111;
}

.history-card__image > span {
  display: grid;
  width: 100%;
  height: 100%;
  place-items: center;
  color: var(--text-secondary);
  background: var(--bg-secondary);
}

.history-card__body {
  padding: 16px 17px 18px;
  display: flex;
  flex-direction: column;
  gap: var(--spacing-sm);
}

.history-card__topline {
  display: flex;
  justify-content: space-between;
  gap: var(--spacing-sm);
  align-items: center;
}

.history-card__actions {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-xs);
}

.history-card__topline strong {
  min-width: 0;
  overflow-wrap: anywhere;
}

.history-badge {
  flex: 0 0 auto;
  padding: 2px var(--spacing-sm);
  border-radius: var(--radius-full);
  color: var(--text-inverse);
  background: var(--color-primary);
  font-size: var(--font-size-xs);
}

.history-badge--ok {
  background: var(--color-success);
}

.history-badge--bad {
  background: var(--color-primary);
}

.history-edit,
.history-delete {
  display: inline-flex;
  min-height: 28px;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 0 var(--spacing-sm);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-gray-200);
  background: var(--bg-secondary);
  font-size: var(--font-size-xs);
  white-space: nowrap;
}

.history-edit {
  color: var(--text-secondary);
}

.history-edit:hover {
  border-color: rgba(239, 59, 57, 0.28);
  background: var(--color-primary-subtle);
  color: var(--color-primary-dark);
}

.history-delete {
  min-height: 28px;
  color: var(--color-primary);
}

.history-delete:disabled {
  color: var(--text-tertiary);
  cursor: not-allowed;
}

.history-card__meta {
  display: grid;
  gap: var(--spacing-xs);
  font-size: var(--font-size-sm);
}

.history-card__meta div {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: var(--spacing-sm);
}

.history-card__meta dt {
  color: var(--text-tertiary);
}

.history-card__meta dd {
  min-width: 0;
  overflow-wrap: anywhere;
}

.history-labels {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-xs);
}

.history-labels span {
  padding: 3px var(--spacing-sm);
  border-radius: var(--radius-full);
  background: var(--color-primary-subtle);
  color: var(--color-primary-dark);
  font-size: var(--font-size-xs);
  line-height: 1.35;
}

.history-card__manual-note {
  margin: 0;
  padding: 8px 10px;
  border-left: 3px solid #d79b2e;
  background: #fff8eb;
  color: #815b18;
  font-size: var(--font-size-xs);
  line-height: 1.55;
}




.history-revisions,
.history-trace,
.history-report {
  border-top: 1px solid var(--color-gray-100);
  padding-top: var(--spacing-sm);
}

.history-action {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr) auto 16px;
  align-items: center;
  gap: 10px;
  min-height: 48px;
  cursor: pointer;
  list-style: none;
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  padding: 8px 10px;
  background: #fafafa;
  color: var(--text-primary);
  transition: border-color 0.18s ease, background 0.18s ease, box-shadow 0.18s ease;
}

.history-action:hover,
details[open] > .history-action {
  border-color: rgba(239, 68, 68, 0.14);
  background: #fff;
  box-shadow: 0 5px 16px rgba(15, 23, 42, 0.05);
}

.history-action::-webkit-details-marker {
  display: none;
}

.history-action__icon {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border: 1px solid rgba(239, 68, 68, 0.12);
  border-radius: 8px;
  background: #fff;
  color: var(--color-primary);
}

.history-action__label {
  min-width: 0;
  overflow: hidden;
  color: var(--text-primary);
  font-size: var(--font-size-sm);
  font-weight: 700;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-action__meta {
  max-width: 150px;
  overflow: hidden;
  color: var(--text-tertiary);
  font-size: 11px;
  font-weight: 500;
  line-height: 1.25;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-action__chevron {
  color: var(--text-tertiary);
  transition: transform 0.18s ease, color 0.18s ease;
}

details[open] > .history-action .history-action__chevron {
  color: var(--color-primary);
  transform: rotate(180deg);
}

.history-review-note {
  display: grid;
  gap: 9px;
  margin-top: 2px;
  padding: 13px 14px;
  border: 1px solid #e4e5e8;
  border-radius: var(--radius-md);
  background: #fff;
}

.history-review-note__heading {
  display: flex;
  align-items: center;
  gap: 12px;
}

.history-review-note__icon {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  flex: 0 0 auto;
  border-radius: 6px;
  background: var(--color-primary-subtle);
  color: var(--color-primary);
}

.history-review-note strong {
  color: var(--text-primary);
  font-size: var(--font-size-sm);
}

.history-review-note__meta {
  margin-left: auto;
  color: var(--text-secondary);
  font-size: var(--font-size-xs);
  text-align: right;
}

.history-review-note p {
  margin: 0;
  padding-left: 40px;
  color: var(--text-primary);
  font-size: var(--font-size-sm);
  line-height: 1.65;
  white-space: pre-wrap;
}

.history-review-note--empty {
  background: #fafafa;
}

.history-review-note--empty p {
  color: var(--text-tertiary);
}

.history-revisions__body {
  margin-top: var(--spacing-sm);
  padding: 4px 10px;
}

.history-trace__body {
  display: grid;
  gap: 14px;
  margin-top: 12px;
  padding: 0 10px 4px;
}

.history-trace__summary {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 18px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--color-gray-100);
  color: var(--text-tertiary);
  font-size: var(--font-size-xs);
}

.history-trace__timeline {
  margin: 0;
  padding: 0;
  list-style: none;
}

.history-trace__stage {
  position: relative;
  display: grid;
  grid-template-columns: 14px minmax(0, 1fr);
  gap: 10px;
  padding: 0 0 17px;
}

.history-trace__stage:last-child {
  padding-bottom: 0;
}

.history-trace__stage:not(:last-child)::before {
  position: absolute;
  top: 13px;
  bottom: 0;
  left: 6px;
  width: 1px;
  background: #dedfe3;
  content: '';
}

.history-trace__marker {
  position: relative;
  z-index: 1;
  width: 9px;
  height: 9px;
  margin: 5px 0 0 2px;
  border: 2px solid #fff;
  border-radius: 50%;
  background: var(--color-success);
  box-shadow: 0 0 0 1px rgba(35, 122, 69, 0.28);
}

.history-trace__stage--warn .history-trace__marker {
  background: #d99316;
  box-shadow: 0 0 0 1px rgba(217, 147, 22, 0.3);
}

.history-trace__stage--error .history-trace__marker {
  background: var(--color-primary);
  box-shadow: 0 0 0 1px rgba(239, 59, 57, 0.3);
}

.history-trace__stage--skipped .history-trace__marker {
  background: var(--color-gray-400);
  box-shadow: 0 0 0 1px rgba(148, 151, 158, 0.3);
}

.history-trace__stage-content {
  min-width: 0;
}

.history-trace__stage-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--spacing-sm);
}

.history-trace__stage-heading strong {
  color: var(--text-primary);
  font-size: var(--font-size-sm);
}

.history-trace__stage-heading span,
.history-trace__stage p,
.history-trace__empty,
.history-trace__issues {
  color: var(--text-secondary);
  font-size: var(--font-size-xs);
}

.history-trace__stage p {
  margin: 4px 0 0;
  line-height: 1.55;
  overflow-wrap: anywhere;
}

.history-trace__issues {
  margin: 0;
  padding-top: 11px;
  border-top: 1px solid var(--color-gray-100);
  line-height: 1.6;
}

.history-report__content {
  margin-top: var(--spacing-sm);
  max-height: 520px;
  overflow: auto;
  line-height: 1.75;
  font-size: var(--font-size-sm);
}

.history-report__original {
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--color-gray-100);
}

.history-report__original > summary {
  color: var(--text-secondary);
  font-size: var(--font-size-xs);
  font-weight: 650;
  cursor: pointer;
}

.history-report__original[open] > summary {
  margin-bottom: 16px;
  color: var(--color-primary-dark);
}

.history-pager {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: var(--spacing-sm);
  margin-top: var(--spacing-lg);
  overflow-x: auto;
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
}

.history-pager span,
.history-yolo-overlay {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.history-yolo-box {
  position: absolute;
  border: 2px solid #dc2626;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.18) inset;
}

.history-yolo-box span {
  position: absolute;
  left: 4px;
  top: 4px;
  display: grid;
  width: 24px;
  height: 24px;
  place-items: center;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.82);
  background: #dc2626;
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  box-shadow: 0 6px 16px rgba(220, 38, 38, 0.22);
}

.history-yolo-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.history-yolo-legend span {
  max-width: 100%;
  padding: 3px 8px;
  border-radius: var(--radius-full);
  background: rgba(220, 38, 38, 0.08);
  color: #991b1b;
  font-size: var(--font-size-xs);
  line-height: 1.35;
}

.history-yolo-legend--card span {
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-yolo-legend--preview {
  margin-top: var(--spacing-sm);
}

.history-card__hint {
  display: inline-flex;
  align-self: flex-start;
  padding: 3px var(--spacing-sm);
  border-radius: var(--radius-full);
  background: rgba(220, 38, 38, 0.08);
  color: #b91c1c;
  font-size: var(--font-size-xs);
  line-height: 1.35;
}

.history-button {
  flex: 0 0 auto;
  white-space: nowrap;
}

.history-button {
  min-height: 38px;
  min-width: 58px;
  padding: 0 var(--spacing-md);
  border-radius: var(--radius-full);
  border: 1px solid var(--color-gray-200);
  background: var(--bg-secondary);
  color: var(--text-primary);
}

.history-button:disabled {
  color: var(--text-tertiary);
  cursor: not-allowed;
}

.history-button--number {
  min-width: 38px;
  padding: 0 var(--spacing-sm);
}

.history-button--danger {
  color: var(--text-inverse);
  background: var(--color-primary);
  border-color: var(--color-primary);
}

.history-button--active {
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: var(--text-inverse);
}

.history-preview {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: grid;
  place-items: center;
  padding: var(--spacing-xl);
  background: rgba(17, 24, 39, 0.78);
}

.history-preview__dialog {
  position: relative;
  width: min(980px, 96vw);
  max-height: 92vh;
  padding: var(--spacing-lg);
  border-radius: var(--radius-xl);
  background: var(--bg-primary);
  overflow: auto;
  box-shadow: var(--shadow-lg);
}

.history-preview__close {
  position: absolute;
  top: var(--spacing-sm);
  right: var(--spacing-sm);
  width: 36px;
  height: 36px;
  border-radius: var(--radius-full);
  border: 1px solid var(--color-gray-200);
  background: var(--bg-primary);
}

.history-preview__image {
  position: relative;
  width: 100%;
  max-height: 72vh;
}

.history-preview img {
  width: 100%;
  max-height: 72vh;
  object-fit: contain;
  background: #111;
}

.history-yolo-overlay--preview .history-yolo-box {
  border-width: 3px;
}

.history-preview__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-md);
  margin-top: var(--spacing-md);
  color: var(--text-secondary);
}

.history-preview__meta strong {
  color: var(--text-primary);
}

@media (max-width: 1024px) {
  .history-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .history-hero,
  .history-toolbar {
    grid-template-columns: 1fr;
  }

  .history-hero {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
  }

  .history-hero__stat {
    text-align: left;
  }

  .history-grid {
    grid-template-columns: 1fr;
  }

  .history-review-note__heading,
  .history-trace__stage-heading {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .history-review-note__meta {
    width: 100%;
    margin-left: 40px;
    text-align: left;
  }

  .history-review-note p {
    padding-left: 0;
  }
}
</style>
