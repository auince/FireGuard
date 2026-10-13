<script setup>
import { ref, computed, onBeforeUnmount } from 'vue'
import { Pencil } from 'lucide-vue-next'
import { createInspectionRevision, inspectFireStream } from '@/api'
import ImageUploader from '@/components/ImageUploader.vue'
import LoadingSpinner from '@/components/LoadingSpinner.vue'
import ReportEditor from '@/components/report/ReportEditor.vue'
import ReportViewer from '@/components/report/ReportViewer.vue'

// 固定的检测提示语
const FIXED_QUERY = '请帮我判断这张图片里面的消防栓存在的异常'

const imageBase64 = ref('')
const result = ref('')
const isLoading = ref(false)
const error = ref('')
const yoloResult = ref(null)
const traceResult = ref(null)
const progressEvents = ref([])
const abortController = ref(null)
const historyRecord = ref(null)
const editingReport = ref(false)
const revisionSaving = ref(false)
const revisionError = ref('')
const revisionMessage = ref('')
const STREAM_RENDER_INTERVAL = 120
let streamedResult = ''
let streamRenderTimer = null

const cancelStreamRender = () => {
  if (streamRenderTimer !== null) {
    window.clearTimeout(streamRenderTimer)
    streamRenderTimer = null
  }
}

const scheduleStreamRender = () => {
  if (streamRenderTimer !== null) return

  streamRenderTimer = window.setTimeout(() => {
    result.value = streamedResult
    streamRenderTimer = null
  }, STREAM_RENDER_INTERVAL)
}

// 只需要有图片即可提交
const canSubmit = computed(() => {
  return imageBase64.value && !isLoading.value
})

const yoloDetections = computed(() => yoloResult.value?.detections || [])
const yoloStatusText = computed(() => {
  if (!yoloResult.value) return ''
  if (!yoloResult.value.enabled) {
    return `YOLO辅助检测未启用：${yoloResult.value.reason || '无详细信息'}`
  }
  const count = yoloDetections.value.length
  return count
    ? `YOLO辅助检测检出 ${count} 个内部组件候选框，已交给二次复核综合判断。`
    : 'YOLO辅助检测未检出高于阈值的内部组件隐患框，但不代表没有隐患。'
})
const formatConfidence = (value) => `${Math.round((Number(value) || 0) * 100)}%`
const traceStages = computed(() => traceResult.value?.stages || [])
const traceIssues = computed(() => traceResult.value?.summary?.issues || [])
const progressStages = [
  { id: 'prepare', label: '准备任务', hint: '校验图片与检测参数' },
  { id: 'route', label: '识别巡检对象', hint: '确定设施类型与检测分支' },
  { id: 'analysis', label: '执行专项分析', hint: '理解现场状态与可见组件' },
  { id: 'review', label: '复核检测证据', hint: '校验结论和图像证据' },
  { id: 'specialist', label: '核验关键隐患', hint: '按需执行针对性校验', optional: true },
  { id: 'report', label: '生成检测报告', hint: '汇总标签、证据与建议' }
]
const latestProgress = computed(() => progressEvents.value.at(-1) || {
  stage: 'prepare',
  status: 'running',
  label: '正在建立检测任务',
  detail: '图片上传完成后将按步骤执行'
})
const progressByStage = computed(() => {
  const grouped = {}
  progressEvents.value.forEach((event) => {
    grouped[event.stage] = event
  })
  return grouped
})
const visibleProgressStages = computed(() => progressStages.filter((stage) => {
  if (!stage.optional) return true
  return progressEvents.value.some((event) => event.stage === stage.id)
}))
const progressStatus = (stage) => {
  const event = progressByStage.value[stage.id]
  if (event?.status === 'complete') return 'complete'
  if (latestProgress.value.stage === stage.id) return 'running'
  return 'pending'
}
const tokenSnapshot = computed(() => {
  const finalUsage = traceResult.value?.summary?.usage
  if (finalUsage) return finalUsage
  const event = [...progressEvents.value].reverse().find((item) => item.throughput)
  return event?.throughput || {}
})
const formatDuration = (value) => `${Number(value || 0)}ms`
const stageStatusText = (stage) => {
  if (stage?.superseded) return '\u5df2\u4f5c\u5e9f'
  if (stage?.status === 'warn') return '\u63d0\u9192'
  if (stage?.status === 'error') return '\u5f02\u5e38'
  if (stage?.status === 'skipped') return '\u8df3\u8fc7'
  return '\u6b63\u5e38'
}
const stageMainText = (stage) => {
  if (stage.name === 'qwen_first') {
    const output = stage.output || {}
    return `${output.verdict || '\u672a\u89e3\u6790\u7ed3\u8bba'} / ${(output.labels || []).join('\uff1b') || '\u65e0\u6807\u7b7e'}`
  }
  if (String(stage.name || '').startsWith('yolo_')) {
    const summary = `\u5019\u9009\u6846 ${stage.detectionCount || 0} \u4e2a / ${(stage.labels || []).join('\uff1b') || '\u65e0\u6807\u7b7e'}`
    return stage.superseded ? `\u65e7\u8303\u56f4\u7ed3\u679c\uff1a${summary}\uff1b\u4e0d\u53c2\u4e0e\u6700\u7ec8\u7ed3\u8bba` : summary
  }
  const output = stage.output || {}
  return `${output.verdict || '\u672a\u89e3\u6790\u7ed3\u8bba'} / ${(output.labels || []).join('\uff1b') || '\u65e0\u6807\u7b7e'}`
}

const handleImageUpload = (base64) => {
  abortActiveRequest()
  imageBase64.value = base64
  // 清除之前的结果
  result.value = ''
  error.value = ''
  yoloResult.value = null
  traceResult.value = null
  progressEvents.value = []
  historyRecord.value = null
  editingReport.value = false
  revisionError.value = ''
  revisionMessage.value = ''
}

const handleImageRemove = () => {
  abortActiveRequest()
  imageBase64.value = ''
  result.value = ''
  error.value = ''
  yoloResult.value = null
  traceResult.value = null
  progressEvents.value = []
  historyRecord.value = null
  editingReport.value = false
  revisionError.value = ''
  revisionMessage.value = ''
}

const abortActiveRequest = () => {
  abortController.value?.abort()
  abortController.value = null
  cancelStreamRender()
  streamedResult = ''
}

const handleSubmit = async () => {
  if (!canSubmit.value) return

  abortActiveRequest()
  isLoading.value = true
  error.value = ''
  result.value = ''
  yoloResult.value = null
  traceResult.value = null
  progressEvents.value = []
  historyRecord.value = null
  editingReport.value = false
  revisionError.value = ''
  revisionMessage.value = ''
  streamedResult = ''
  const controller = new AbortController()
  abortController.value = controller

  try {
    const res = await inspectFireStream({
      query: FIXED_QUERY,
      image: imageBase64.value,
      signal: controller.signal,
      onChunk: (delta) => {
        streamedResult += delta
        scheduleStreamRender()
      },
      onProgress: (payload) => {
        progressEvents.value.push(payload)
      }
    })

    cancelStreamRender()
    result.value = res.response
    yoloResult.value = res.yolo || null
    traceResult.value = res.trace || null
    historyRecord.value = res.history || null
    if (historyRecord.value?.effectiveResponse) {
      result.value = historyRecord.value.effectiveResponse
    }
  } catch (err) {
    if (err.name === 'AbortError') {
      return
    }

    cancelStreamRender()
    error.value = err.message || '检测失败，请重试'
  } finally {
    if (abortController.value === controller) {
      abortController.value = null
    }
    isLoading.value = false
  }
}

const handleReset = () => {
  abortActiveRequest()
  imageBase64.value = ''
  result.value = ''
  error.value = ''
  yoloResult.value = null
  traceResult.value = null
  progressEvents.value = []
  historyRecord.value = null
  editingReport.value = false
  revisionError.value = ''
  revisionMessage.value = ''
}

const currentReportDocument = computed(() => (
  historyRecord.value?.effectiveReportDocument || null
))
const modelReportDocument = computed(() => (
  historyRecord.value?.modelReportDocument || currentReportDocument.value
))
const latestRevisionId = computed(() => (
  historyRecord.value?.reportRevisionSummary?.latest?.id || ''
))
const hasReportCorrection = computed(() => (
  Boolean(historyRecord.value?.reportRevisionSummary?.hasCorrection)
))

const openReportEditor = () => {
  if (!historyRecord.value?.id || !currentReportDocument.value) return
  revisionError.value = ''
  revisionMessage.value = ''
  editingReport.value = true
}

const closeReportEditor = () => {
  if (revisionSaving.value) return
  revisionError.value = ''
  editingReport.value = false
}

const saveReportRevision = async (payload) => {
  if (!historyRecord.value?.id) return
  revisionSaving.value = true
  revisionError.value = ''
  revisionMessage.value = ''
  try {
    const saved = await createInspectionRevision(historyRecord.value.id, payload)
    historyRecord.value = {
      ...historyRecord.value,
      ...saved
    }
    result.value = saved.effectiveResponse || result.value
    editingReport.value = false
    revisionMessage.value = `人工修订 v${saved.revision?.version || ''} 已保存`
  } catch (err) {
    revisionError.value = err.message || '保存人工修订失败'
  } finally {
    revisionSaving.value = false
  }
}

onBeforeUnmount(() => {
  abortActiveRequest()
})
</script>

<template>
  <div class="inspect">
    <div class="inspect__container container">
      <!-- Header -->
      <header class="inspect__header">
        <h1 class="inspect__title">智能检测</h1>
        <p class="inspect__subtitle">
          上传消防栓图片，AI将自动分析并生成检测报告
        </p>
      </header>

      <!-- Main Content -->
      <div class="inspect__content">
        <!-- Input Section -->
        <div class="inspect__input-section">
          <div class="inspect__card card">
            <h2 class="inspect__card-title">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                <path d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14"
                      stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M14 8h.01" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                <rect x="3" y="4" width="18" height="16" rx="2" stroke="currentColor" stroke-width="1.5"/>
              </svg>
              上传消防栓图片
            </h2>
            <ImageUploader
              @upload="handleImageUpload"
              @remove="handleImageRemove"
            />

            <div class="inspect__hint">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <path d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                      stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
              <span>上传图片后，系统将自动检测消防栓存在的异常</span>
            </div>
          </div>

          <div class="inspect__actions">
            <button
              class="btn btn-primary btn-lg inspect__submit"
              :disabled="!canSubmit"
              @click="handleSubmit"
            >
              <template v-if="isLoading">
                <LoadingSpinner size="sm" />
                <span>分析中...</span>
              </template>
              <template v-else>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                  <path d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
                        stroke="currentColor" stroke-width="2"
                        stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <span>开始检测</span>
              </template>
            </button>

            <button
              v-if="result || error"
              class="btn btn-secondary btn-lg"
              @click="handleReset"
            >
              重新检测
            </button>
          </div>
        </div>

        <!-- Result Section -->
        <div class="inspect__result-section">
          <div class="inspect__card card inspect__result-card">
            <div class="inspect__report-heading">
              <h2 class="inspect__card-title">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                  <path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                        stroke="currentColor" stroke-width="1.5"
                        stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                检测报告
              </h2>
              <button
                v-if="result && historyRecord?.id && !isLoading && !editingReport"
                class="inspect__edit-report"
                type="button"
                @click="openReportEditor"
              >
                <Pencil :size="17" />
                人工修订
              </button>
            </div>

            <!-- Error State -->
            <div v-if="error" class="inspect__error">
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none">
                <path d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                      stroke="currentColor" stroke-width="1.5"
                      stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
              <p>{{ error }}</p>
            </div>

            <!-- Result State -->
            <div v-else-if="result || isLoading" class="inspect__result">
              <div v-if="isLoading && result" class="inspect__streaming-status">
                <LoadingSpinner size="sm" />
                <span>AI 正在流式生成检测报告...</span>
              </div>
              <p v-if="revisionMessage && !editingReport" class="inspect__revision-message">{{ revisionMessage }}</p>
              <ReportEditor
                v-if="editingReport && currentReportDocument && modelReportDocument"
                :model-value="currentReportDocument"
                :model-document="modelReportDocument"
                :base-revision-id="latestRevisionId"
                :saving="revisionSaving"
                :error="revisionError"
                @save="saveReportRevision"
                @cancel="closeReportEditor"
              />
              <ReportViewer
                v-else-if="result"
                class="inspect__result-content"
                :document="currentReportDocument"
                :text="result"
                :revised="hasReportCorrection"
              />
              <div v-if="false && yoloResult" class="inspect__yolo-card">
                <div class="inspect__yolo-head">
                  <strong>YOLO 辅助检测</strong>
                  <span>{{ yoloStatusText }}</span>
                </div>
                <div v-if="yoloDetections.length" class="inspect__yolo-list">
                  <span
                    v-for="item in yoloDetections"
                    :key="`${item.className}-${item.confidence}-${item.bbox?.join('-')}`"
                  >
                    {{ item.label || item.className }} {{ formatConfidence(item.confidence) }}
                  </span>
                </div>
              </div>
              <div v-if="false && traceResult" class="inspect__trace-card">
                <div class="inspect__trace-head">
                  <strong>&#x672c;&#x6b21;&#x94fe;&#x8def;&#x8ffd;&#x8e2a;</strong>
                  <span>&#x603b;&#x8017;&#x65f6; {{ formatDuration(traceResult.summary?.totalDurationMs) }}</span>
                </div>
                <div class="inspect__trace-stages">
                  <div
                    v-for="stage in traceStages"
                    :key="stage.name"
                    :class="['inspect__trace-stage', `inspect__trace-stage--${stage.status || 'ok'}`]"
                  >
                    <div>
                      <strong>{{ stage.title }}</strong>
                      <span>{{ stageStatusText(stage) }} &middot; {{ formatDuration(stage.durationMs) }}</span>
                    </div>
                    <p>{{ stageMainText(stage) }}</p>
                  </div>
                </div>
                <div v-if="traceIssues.length" class="inspect__trace-issues">
                  <strong>&#x9700;&#x8981;&#x5173;&#x6ce8;</strong>
                  <span v-for="issue in traceIssues" :key="issue.type">{{ issue.title }}</span>
                </div>
              </div>
              <div v-if="isLoading && !result" class="inspect__loading">
                <div class="inspect-progress">
                  <div class="inspect-progress__head">
                    <div class="inspect-progress__pulse" aria-hidden="true">
                      <span></span>
                    </div>
                    <div>
                      <span>检测进行中</span>
                      <strong>{{ latestProgress.label }}</strong>
                      <p>{{ latestProgress.detail }}</p>
                    </div>
                  </div>

                  <ol class="inspect-progress__steps">
                    <li
                      v-for="(stage, index) in visibleProgressStages"
                      :key="stage.id"
                      :class="`is-${progressStatus(stage)}`"
                    >
                      <span class="inspect-progress__index">
                        <svg v-if="progressStatus(stage) === 'complete'" width="14" height="14" viewBox="0 0 24 24" fill="none">
                          <path d="M5 12.5l4 4L19 7" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                        <template v-else>{{ String(index + 1).padStart(2, '0') }}</template>
                      </span>
                      <span>
                        <strong>{{ stage.label }}</strong>
                        <small>{{ stage.hint }}</small>
                      </span>
                    </li>
                  </ol>

                  <div v-if="tokenSnapshot.totalTokens" class="inspect-progress__metrics">
                    <span>
                      <small>输入 Token</small>
                      <strong>{{ tokenSnapshot.inputTokens || 0 }}</strong>
                    </span>
                    <span>
                      <small>输出 Token</small>
                      <strong>{{ tokenSnapshot.outputTokens || 0 }}</strong>
                    </span>
                    <span>
                      <small>输出速率</small>
                      <strong>{{ tokenSnapshot.outputTokensPerSecond || 0 }} t/s</strong>
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <!-- Empty State -->
            <div v-else class="inspect__empty">
              <svg width="64" height="64" viewBox="0 0 24 24" fill="none">
                <path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"
                      stroke="currentColor" stroke-width="1.5"
                      stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
              <p>上传消防栓图片后<br />检测报告将显示在这里</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.inspect {
  padding: 104px 0 40px;
  min-height: 100vh;
  background: var(--bg-secondary);
}

.inspect__header {
  text-align: left;
  margin-bottom: 26px;
}

.inspect__title {
  font-size: var(--font-size-3xl);
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 6px;
}

.inspect__subtitle {
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
}

.inspect__content {
  display: grid;
  grid-template-columns: 1fr;
  gap: 20px;
}

@media (min-width: 1024px) {
  .inspect__content {
    grid-template-columns: 1fr 1fr;
    align-items: start;
  }
}

.inspect__input-section {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.inspect__card {
  padding: 24px;
}

.inspect__card-title {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  font-size: var(--font-size-lg);
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: var(--spacing-lg);
}

.inspect__card-title svg {
  color: var(--color-primary);
}

.inspect__hint {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  margin-top: var(--spacing-lg);
  padding: var(--spacing-md);
  background: var(--color-primary-subtle);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  color: var(--color-primary-dark);
}

.inspect__hint svg {
  flex-shrink: 0;
}

.inspect__actions {
  display: flex;
  gap: var(--spacing-md);
}

.inspect__submit {
  flex: 1;
}

.inspect__submit:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.inspect__result-section {
  position: sticky;
  top: 88px;
}

.inspect__result-card {
  min-height: 460px;
  display: flex;
  flex-direction: column;
}

.inspect__loading,
.inspect__error,
.inspect__empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: var(--spacing-2xl);
}

.inspect__loading {
  align-items: stretch;
  justify-content: flex-start;
  padding: 6px 2px 2px;
  text-align: left;
}

.inspect-progress {
  width: 100%;
  padding: 20px;
  border: 1px solid #eadfdd;
  border-radius: var(--radius-lg);
  background: #fcfbfa;
}

.inspect-progress__head {
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr);
  gap: 14px;
  align-items: start;
  padding-bottom: 18px;
  border-bottom: 1px solid #ebe4e2;
}

.inspect-progress__pulse {
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
  border-radius: 50%;
  background: #f8e8e6;
}

.inspect-progress__pulse span {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--color-primary);
  box-shadow: 0 0 0 0 rgba(204, 70, 61, .28);
  animation: progress-pulse 1.8s ease-out infinite;
}

.inspect-progress__head > div:last-child > span {
  color: var(--color-primary);
  font-size: 11px;
  font-weight: 700;
}

.inspect-progress__head strong {
  display: block;
  margin-top: 3px;
  color: var(--text-primary);
  font-size: 17px;
}

.inspect-progress__head p {
  margin-top: 5px;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.6;
}

.inspect-progress__steps {
  display: grid;
  gap: 0;
  margin: 18px 0 0;
  padding: 0;
  list-style: none;
}

.inspect-progress__steps li {
  position: relative;
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  gap: 12px;
  min-height: 56px;
  color: var(--text-tertiary);
}

.inspect-progress__steps li:not(:last-child)::after {
  content: '';
  position: absolute;
  top: 27px;
  bottom: 2px;
  left: 13px;
  width: 1px;
  background: #e5dddb;
}

.inspect-progress__index {
  z-index: 1;
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border: 1px solid #ded7d5;
  border-radius: 50%;
  background: #fff;
  color: #a39b99;
  font-size: 10px;
  font-weight: 700;
}

.inspect-progress__steps strong,
.inspect-progress__steps small {
  display: block;
}

.inspect-progress__steps strong {
  padding-top: 2px;
  color: inherit;
  font-size: 14px;
}

.inspect-progress__steps small {
  margin-top: 3px;
  color: var(--text-tertiary);
  font-size: 11px;
}

.inspect-progress__steps .is-running {
  color: var(--text-primary);
}

.inspect-progress__steps .is-running .inspect-progress__index {
  border-color: var(--color-primary);
  background: var(--color-primary);
  color: #fff;
  box-shadow: 0 0 0 4px #f8e8e6;
}

.inspect-progress__steps .is-complete {
  color: #4e665d;
}

.inspect-progress__steps .is-complete .inspect-progress__index {
  border-color: #cfe1d8;
  background: #e7f2ec;
  color: #36765b;
}

.inspect-progress__metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1px;
  overflow: hidden;
  margin-top: 2px;
  border: 1px solid #e8e0de;
  border-radius: var(--radius-md);
  background: #e8e0de;
}

.inspect-progress__metrics span {
  padding: 10px 12px;
  background: #fff;
}

.inspect-progress__metrics small,
.inspect-progress__metrics strong {
  display: block;
}

.inspect-progress__metrics small {
  color: var(--text-tertiary);
  font-size: 10px;
}

.inspect-progress__metrics strong {
  margin-top: 2px;
  color: var(--text-primary);
  font-size: 13px;
}

@keyframes progress-pulse {
  70% { box-shadow: 0 0 0 9px rgba(204, 70, 61, 0); }
  100% { box-shadow: 0 0 0 0 rgba(204, 70, 61, 0); }
}

.inspect__empty svg,
.inspect__error svg {
  color: var(--color-gray-300);
  margin-bottom: var(--spacing-md);
}

.inspect__empty p {
  color: var(--text-tertiary);
  line-height: 1.8;
}

.inspect__error svg {
  color: var(--color-error);
}

.inspect__error p {
  color: var(--color-error);
  font-weight: 500;
}

.inspect__result {
  flex: 1;
  overflow-y: auto;
  max-height: 680px;
}

.inspect__streaming-status {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-md);
  padding: var(--spacing-sm) var(--spacing-md);
  background: var(--color-primary-subtle);
  border-radius: var(--radius-md);
  color: var(--color-primary-dark);
  font-size: var(--font-size-sm);
  position: sticky;
  top: 0;
}

.inspect__report-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-md);
}

.inspect__report-heading .inspect__card-title {
  margin-bottom: 0;
}

.inspect__edit-report {
  display: inline-flex;
  min-height: 38px;
  align-items: center;
  gap: 7px;
  padding: 0 13px;
  border: 1px solid var(--color-gray-200);
  border-radius: 6px;
  background: #fff;
  color: var(--text-secondary);
  font: inherit;
  font-size: 14px;
  font-weight: 650;
  cursor: pointer;
  transition: border-color 150ms ease, color 150ms ease, background 150ms ease;
}

.inspect__edit-report:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-subtle);
  color: var(--color-primary-dark);
}

.inspect__result-content {
  margin-top: var(--spacing-lg);
}

.inspect__revision-message {
  margin: var(--spacing-lg) 0 0;
  padding: 10px 12px;
  border-left: 3px solid #d79b2e;
  background: #fff8eb;
  color: #815b18;
  font-size: 14px;
}


.inspect__trace-card {
  margin-top: var(--spacing-md);
  padding: var(--spacing-md);
  border: 1px solid var(--color-gray-200);
  border-radius: var(--radius-lg);
  background: var(--bg-secondary);
}

.inspect__trace-head,
.inspect__trace-stage > div {
  display: flex;
  justify-content: space-between;
  gap: var(--spacing-md);
  align-items: center;
}

.inspect__trace-head span,
.inspect__trace-stage span,
.inspect__trace-stage p {
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
}

.inspect__trace-stages {
  display: grid;
  gap: var(--spacing-sm);
  margin-top: var(--spacing-md);
}

.inspect__trace-stage {
  padding: var(--spacing-sm) var(--spacing-md);
  border-left: 4px solid var(--color-success);
  background: var(--bg-primary);
  border-radius: var(--radius-md);
}

.inspect__trace-stage--warn {
  border-left-color: #f59e0b;
}

.inspect__trace-stage--error {
  border-left-color: var(--color-primary);
}

.inspect__trace-stage--skipped {
  border-left-color: var(--color-gray-400);
  background: var(--bg-tertiary);
}

.inspect__trace-stage p {
  margin: var(--spacing-xs) 0 0;
  overflow-wrap: anywhere;
}

.inspect__trace-issues {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-xs);
  margin-top: var(--spacing-md);
  align-items: center;
}

.inspect__trace-issues span {
  padding: 3px var(--spacing-sm);
  border-radius: var(--radius-full);
  background: #fff1f2;
  color: var(--color-primary-dark);
  font-size: var(--font-size-xs);
}

@media (max-width: 1024px) {
  .inspect__result-section {
    position: static;
  }
}

@media (max-width: 640px) {
  .inspect__report-heading {
    align-items: flex-start;
  }

  .inspect__edit-report {
    flex: 0 0 auto;
    padding: 0 10px;
  }
}
</style>
