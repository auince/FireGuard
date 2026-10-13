<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  Circle, Clock3, Gauge, PanelTop, RotateCcw, ScanSearch,
  Square, Trash2, Triangle, Upload, X
} from 'lucide-vue-next'
import {
  checkPipesHealth, clearPipeHistory, countPipes, deletePipeHistory,
  fetchPipeHistory, fileToBase64
} from '@/api'

const profileClasses = [
  { id: 0, key: 'round', name: '圆管', color: '#E53935', icon: Circle },
  { id: 1, key: 'square', name: '方管', color: '#2878D0', icon: Square },
  { id: 2, key: 'angle', name: '角钢', color: '#F28C28', icon: Triangle },
  { id: 3, key: 'channel', name: '槽钢', color: '#2F8F5B', icon: PanelTop }
]

const fileInput = ref(null)
const imageBase64 = ref('')
const imageSize = ref({ width: 4, height: 3 })
const result = ref(null)
const confidence = ref(0.25)
const selectedClasses = ref([0, 1, 2, 3])
const visibleClasses = ref([0, 1, 2, 3])
const isLoading = ref(false)
const error = ref('')
const serviceStatus = ref('checking')
const history = ref([])
const historyLoading = ref(false)

const canCount = computed(() => Boolean(imageBase64.value)
  && selectedClasses.value.length > 0 && !isLoading.value)
const visibleDetections = computed(() => (result.value?.detections || [])
  .filter((item) => visibleClasses.value.includes(item.classId)))
const imageAspect = computed(() => {
  const width = Number(result.value?.imageWidth || imageSize.value.width) || 4
  const height = Number(result.value?.imageHeight || imageSize.value.height) || 3
  return `${width} / ${height}`
})
const confidenceLabel = computed(() => `${Math.round(confidence.value * 100)}%`)
const statusText = computed(() => {
  if (serviceStatus.value === 'running') return '模型在线'
  if (serviceStatus.value === 'error') return '模型离线'
  return '正在连接'
})

const resultCount = (key) => Number(result.value?.counts?.[key] || 0)
const detectionStyle = (item) => {
  const [x1, y1, x2, y2] = item.bboxNorm || []
  return {
    left: `${Number(x1 || 0) * 100}%`,
    top: `${Number(y1 || 0) * 100}%`,
    width: `${Math.max(0, Number(x2 || 0) - Number(x1 || 0)) * 100}%`,
    height: `${Math.max(0, Number(y2 || 0) - Number(y1 || 0)) * 100}%`,
    borderColor: item.color || '#E53935'
  }
}

const toggleListValue = (listRef, value) => {
  listRef.value = listRef.value.includes(value)
    ? listRef.value.filter((item) => item !== value)
    : [...listRef.value, value].sort()
}

const loadImageDimensions = (src) => {
  const image = new Image()
  image.onload = () => {
    imageSize.value = { width: image.naturalWidth || 4, height: image.naturalHeight || 3 }
  }
  image.src = src
}

const processFile = async (file) => {
  if (!file?.type?.startsWith('image/')) {
    error.value = '请选择 JPG、PNG 或 WEBP 图片'
    return
  }
  if (file.size > 20 * 1024 * 1024) {
    error.value = '图片不能超过 20MB'
    return
  }
  try {
    const base64 = await fileToBase64(file)
    imageBase64.value = base64
    result.value = null
    error.value = ''
    loadImageDimensions(base64)
  } catch {
    error.value = '图片读取失败，请重新选择'
  }
}

const resetImage = () => {
  imageBase64.value = ''
  result.value = null
  error.value = ''
  imageSize.value = { width: 4, height: 3 }
  if (fileInput.value) fileInput.value.value = ''
}

const runCount = async () => {
  if (!canCount.value) return
  isLoading.value = true
  error.value = ''
  try {
    result.value = await countPipes({
      image: imageBase64.value,
      confidence: confidence.value,
      classes: selectedClasses.value
    })
    visibleClasses.value = [...selectedClasses.value]
    await loadHistory()
  } catch (err) {
    error.value = err.message || '计数失败，请重试'
  } finally {
    isLoading.value = false
  }
}

const loadHealth = async () => {
  serviceStatus.value = 'checking'
  try {
    const payload = await checkPipesHealth()
    serviceStatus.value = payload.status === 'running' ? 'running' : 'error'
  } catch {
    serviceStatus.value = 'error'
  }
}

const loadHistory = async () => {
  historyLoading.value = true
  try {
    const payload = await fetchPipeHistory(12)
    history.value = payload.records || []
  } catch {
    history.value = []
  } finally {
    historyLoading.value = false
  }
}

const removeHistory = async (id) => {
  try {
    await deletePipeHistory(id)
    history.value = history.value.filter((item) => item.id !== id)
  } catch (err) {
    error.value = err.message || '删除记录失败'
  }
}

const clearHistory = async () => {
  if (!history.value.length) return
  try {
    await clearPipeHistory()
    history.value = []
  } catch (err) {
    error.value = err.message || '清空记录失败'
  }
}

const openHistory = async (record) => {
  try {
    const response = await fetch(record.imageUrl)
    if (!response.ok) throw new Error('图片读取失败')
    const image = await fileToBase64(await response.blob())
    imageBase64.value = image
    result.value = { ...record }
    visibleClasses.value = [0, 1, 2, 3]
    error.value = ''
    loadImageDimensions(image)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  } catch (err) {
    error.value = err.message || '历史图片读取失败'
  }
}

onMounted(() => {
  loadHealth()
  loadHistory()
})
</script>

<template>
  <main class="pipes-page">
    <section class="pipes-heading">
      <div class="container pipes-heading__inner">
        <div>
          <p class="eyebrow">工业视觉</p>
          <h1>型材计数</h1>
        </div>
        <div class="service-status" :class="`service-status--${serviceStatus}`">
          <span></span>{{ statusText }}
        </div>
      </div>
    </section>

    <section class="pipes-workspace">
      <div class="container workspace-grid">
        <div class="image-workbench">
          <input ref="fileInput" class="visually-hidden" type="file"
                 accept="image/jpeg,image/png,image/webp"
                 @change="processFile($event.target.files?.[0])" />
          <button v-if="!imageBase64" class="upload-surface" type="button"
                  @click="fileInput?.click()" @dragover.prevent
                  @drop.prevent="processFile($event.dataTransfer.files?.[0])">
            <Upload :size="34" />
            <span class="upload-title">选择型材图片</span>
            <span class="upload-meta">JPG · PNG · WEBP · 最大 20MB</span>
          </button>

          <div v-else class="image-stage" :style="{ aspectRatio: imageAspect }">
            <img :src="imageBase64" alt="待计数型材" />
            <div class="detection-layer" aria-hidden="true">
              <span v-for="(item, index) in visibleDetections"
                    :key="`${item.classId}-${index}`" class="detection-box"
                    :style="detectionStyle(item)"></span>
            </div>
            <button class="remove-image" type="button" title="移除图片" @click="resetImage">
              <X :size="18" />
            </button>
          </div>

          <div v-if="result" class="result-legend">
            <button v-for="item in profileClasses" :key="item.id" class="legend-item"
                    :class="{ muted: !visibleClasses.includes(item.id) }" type="button"
                    @click="toggleListValue(visibleClasses, item.id)">
              <span :style="{ background: item.color }"></span>
              {{ item.name }} {{ resultCount(item.key) }}
            </button>
          </div>
        </div>

        <aside class="count-console">
          <div class="console-topline">
            <span>计数结果</span>
            <span v-if="result" class="elapsed"><Clock3 :size="14" /> {{ result.elapsedMs }}ms</span>
          </div>
          <div class="total-count"><strong>{{ result?.total ?? '—' }}</strong><span>合计</span></div>

          <div class="profile-counts">
            <div v-for="item in profileClasses" :key="item.id" class="profile-count">
              <component :is="item.icon" :size="18" :style="{ color: item.color }" />
              <span>{{ item.name }}</span><strong>{{ result ? resultCount(item.key) : '—' }}</strong>
            </div>
          </div>

          <div class="divider"></div>
          <div class="control-block">
            <div class="control-label"><span>识别类别</span><span>{{ selectedClasses.length }}/4</span></div>
            <div class="class-switches">
              <label v-for="item in profileClasses" :key="item.id" class="class-switch">
                <input type="checkbox" :checked="selectedClasses.includes(item.id)"
                       @change="toggleListValue(selectedClasses, item.id)" />
                <span :style="{ '--class-color': item.color }"></span>{{ item.name }}
              </label>
            </div>
          </div>

          <div class="control-block">
            <div class="control-label">
              <span><Gauge :size="15" />置信度</span><strong>{{ confidenceLabel }}</strong>
            </div>
            <input v-model.number="confidence" class="confidence-slider" type="range"
                   min="0.1" max="0.8" step="0.05" />
          </div>

          <p v-if="error" class="console-error">{{ error }}</p>
          <div class="console-actions">
            <button class="count-button" type="button" :disabled="!canCount" @click="runCount">
              <ScanSearch :size="19" />{{ isLoading ? '正在计数' : '开始计数' }}
            </button>
            <button class="reset-button" type="button" title="重置"
                    :disabled="!imageBase64" @click="resetImage"><RotateCcw :size="19" /></button>
          </div>
        </aside>
      </div>
    </section>

    <section class="history-section">
      <div class="container">
        <div class="section-heading">
          <div><p class="eyebrow">RECENT</p><h2>最近计数</h2></div>
          <button v-if="history.length" class="clear-history" type="button" @click="clearHistory">
            <Trash2 :size="16" />清空
          </button>
        </div>
        <div v-if="historyLoading" class="history-empty">正在读取记录...</div>
        <div v-else-if="!history.length" class="history-empty">暂无计数记录</div>
        <div v-else class="history-grid">
          <article v-for="record in history" :key="record.id" class="history-item">
            <button class="history-image" type="button" title="查看计数结果" @click="openHistory(record)">
              <img :src="record.imageUrl" alt="型材计数历史图片" /><strong>{{ record.total }}</strong>
            </button>
            <div class="history-body">
              <time>{{ record.createdAt }}</time>
              <div class="history-counts">
                <span>圆 {{ record.counts?.round || 0 }}</span><span>方 {{ record.counts?.square || 0 }}</span>
                <span>角 {{ record.counts?.angle || 0 }}</span><span>槽 {{ record.counts?.channel || 0 }}</span>
              </div>
              <button type="button" title="删除记录" @click="removeHistory(record.id)"><Trash2 :size="15" /></button>
            </div>
          </article>
        </div>
      </div>
    </section>
  </main>
</template>

<style scoped>
.pipes-page { min-height: 100vh; padding-top: 88px; background: var(--bg-secondary); }
.pipes-heading { background: #fff; border-bottom: 1px solid var(--color-gray-200); }
.pipes-heading__inner { min-height: 118px; display: flex; align-items: center; justify-content: space-between; gap: 24px; }
.eyebrow { margin-bottom: 4px; color: var(--color-primary); font-size: 12px; font-weight: 700; letter-spacing: 0; }
.pipes-heading h1 { font-size: var(--font-size-3xl); line-height: 1.2; }
.service-status { display: inline-flex; align-items: center; gap: 8px; color: var(--text-secondary); font-size: 14px; }
.service-status > span { width: 9px; height: 9px; border-radius: 50%; background: var(--color-gray-400); box-shadow: 0 0 0 4px var(--color-gray-100); }
.service-status--running > span { background: var(--color-success); box-shadow: 0 0 0 4px #e8f5e9; }
.service-status--error > span { background: var(--color-error); box-shadow: 0 0 0 4px var(--color-primary-subtle); }
.pipes-workspace { padding: 34px 0 42px; }
.workspace-grid { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(310px, .7fr); align-items: start; gap: 24px; }
.image-workbench, .count-console { min-width: 0; background: #fff; border: 1px solid var(--color-gray-200); border-radius: var(--radius-lg); box-shadow: var(--shadow-sm); }
.image-workbench { padding: 18px; }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
.upload-surface { width: 100%; min-height: 490px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; border: 1px dashed var(--color-gray-300); border-radius: var(--radius-md); color: var(--color-gray-500); background: var(--bg-secondary); transition: .18s ease; }
.upload-surface:hover { border-color: var(--color-primary); color: var(--color-primary); background: var(--color-primary-subtle); }
.upload-title { color: var(--text-primary); font-size: 18px; font-weight: 600; }
.upload-meta { color: var(--text-tertiary); font-size: 14px; }
.image-stage { position: relative; width: 100%; overflow: hidden; border-radius: var(--radius-md); background: #111; }
.image-stage > img { width: 100%; height: 100%; object-fit: contain; }
.detection-layer { position: absolute; inset: 0; pointer-events: none; }
.detection-box { position: absolute; border: 2px solid; box-shadow: 0 0 0 1px rgba(255,255,255,.42) inset; }
.remove-image { position: absolute; top: 12px; right: 12px; width: 36px; height: 36px; display: grid; place-items: center; border-radius: 50%; color: #fff; background: rgba(20,20,20,.76); backdrop-filter: blur(8px); }
.result-legend { display: flex; flex-wrap: wrap; gap: 8px; padding-top: 14px; }
.legend-item { display: inline-flex; align-items: center; gap: 7px; padding: 7px 10px; border: 1px solid var(--color-gray-200); border-radius: var(--radius-sm); color: var(--text-secondary); font-size: 14px; background: #fff; }
.legend-item.muted { opacity: .42; }
.legend-item > span { width: 9px; height: 9px; border-radius: 2px; }
.count-console { position: sticky; top: 106px; padding: 22px; }
.console-topline, .control-label, .section-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.console-topline { color: var(--text-secondary); font-size: 14px; font-weight: 600; }
.elapsed { display: inline-flex; align-items: center; gap: 5px; color: var(--text-tertiary); font-weight: 400; }
.total-count { display: flex; align-items: baseline; gap: 10px; margin: 12px 0 18px; }
.total-count strong { font-size: 3.5rem; line-height: 1; font-variant-numeric: tabular-nums; }
.total-count span { color: var(--text-tertiary); }
.profile-counts { display: grid; grid-template-columns: 1fr 1fr; border-top: 1px solid var(--color-gray-200); border-left: 1px solid var(--color-gray-200); }
.profile-count { min-width: 0; display: grid; grid-template-columns: 20px 1fr auto; align-items: center; gap: 7px; padding: 12px 10px; border-right: 1px solid var(--color-gray-200); border-bottom: 1px solid var(--color-gray-200); font-size: 14px; }
.profile-count span { overflow: hidden; color: var(--text-secondary); text-overflow: ellipsis; white-space: nowrap; }
.profile-count strong { font-size: 18px; font-variant-numeric: tabular-nums; }
.divider { height: 1px; margin: 22px 0; background: var(--color-gray-200); }
.control-block + .control-block { margin-top: 20px; }
.control-label { margin-bottom: 10px; color: var(--text-secondary); font-size: 14px; }
.control-label span:first-child { display: inline-flex; align-items: center; gap: 6px; }
.class-switches { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.class-switch { min-height: 38px; display: flex; align-items: center; gap: 8px; padding: 8px 10px; border: 1px solid var(--color-gray-200); border-radius: var(--radius-sm); color: var(--text-secondary); font-size: 14px; cursor: pointer; }
.class-switch input { position: absolute; opacity: 0; }
.class-switch > span { width: 14px; height: 14px; border: 1px solid var(--color-gray-300); border-radius: 3px; }
.class-switch input:checked + span { border-color: var(--class-color); background: var(--class-color); box-shadow: 0 0 0 2px #fff inset; }
.confidence-slider { width: 100%; accent-color: var(--color-primary); }
.console-error { margin-top: 16px; padding: 10px 12px; border-left: 3px solid var(--color-error); color: var(--color-error); font-size: 14px; background: var(--color-primary-subtle); }
.console-actions { display: grid; grid-template-columns: 1fr 46px; gap: 10px; margin-top: 22px; }
.count-button, .reset-button { min-height: 46px; display: inline-flex; align-items: center; justify-content: center; gap: 8px; border-radius: var(--radius-md); transition: .18s ease; }
.count-button { color: #fff; font-weight: 600; background: var(--color-primary); }
.reset-button { border: 1px solid var(--color-gray-200); color: var(--text-secondary); background: #fff; }
.count-button:not(:disabled):hover, .reset-button:not(:disabled):hover { transform: translateY(-1px); }
.count-button:disabled, .reset-button:disabled { cursor: not-allowed; opacity: .42; }
.history-section { padding: 38px 0 64px; border-top: 1px solid var(--color-gray-200); background: #fff; }
.section-heading { margin-bottom: 20px; }
.section-heading h2 { font-size: var(--font-size-2xl); }
.clear-history { display: inline-flex; align-items: center; gap: 6px; color: var(--text-secondary); font-size: 14px; }
.history-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
.history-item { min-width: 0; overflow: hidden; border: 1px solid var(--color-gray-200); border-radius: var(--radius-md); background: #fff; }
.history-image { position: relative; width: 100%; aspect-ratio: 4/3; overflow: hidden; background: var(--bg-tertiary); }
.history-image img { width: 100%; height: 100%; object-fit: cover; }
.history-image strong { position: absolute; right: 8px; bottom: 8px; min-width: 38px; padding: 4px 8px; border-radius: var(--radius-sm); color: #fff; text-align: center; font-size: 18px; background: rgba(18,18,18,.78); }
.history-body { position: relative; padding: 12px; }
.history-body time { display: block; margin-bottom: 8px; color: var(--text-tertiary); font-size: 12px; }
.history-counts { display: flex; flex-wrap: wrap; gap: 5px 9px; padding-right: 24px; color: var(--text-secondary); font-size: 12px; }
.history-body > button { position: absolute; right: 10px; bottom: 10px; color: var(--color-gray-400); }
.history-empty { min-height: 130px; display: grid; place-items: center; border: 1px dashed var(--color-gray-300); color: var(--text-tertiary); font-size: 14px; }
@media (max-width: 900px) { .workspace-grid { grid-template-columns: 1fr; } .count-console { position: static; } .upload-surface { min-height: 360px; } .history-grid { grid-template-columns: repeat(2, minmax(0,1fr)); } }
@media (max-width: 560px) { .pipes-page { padding-top: 72px; } .pipes-heading__inner { min-height: 96px; } .pipes-heading h1 { font-size: var(--font-size-2xl); } .pipes-workspace { padding-top: 18px; } .image-workbench { padding: 10px; } .upload-surface { min-height: 280px; } .history-grid { grid-template-columns: 1fr; } }
</style>
