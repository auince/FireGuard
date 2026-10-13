<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import {
  BadgeCheck,
  Camera,
  Database,
  FileSearch,
  Image as ImageIcon,
  Layers,
  Search,
  Sparkles
} from 'lucide-vue-next'
import ImageUploader from '@/components/ImageUploader.vue'

const imageBase64 = ref('')
const query = ref('红色软管明显锐角折弯，检索相似隐患图片和法规依据')
const activeMode = ref('text-image')
const activeScope = ref('all')
const activeIndex = ref('all')
const selectedResultId = ref('img-001')
const isSearching = ref(false)
const hasSearched = ref(true)
const progress = ref(100)
const resultSeed = ref(0)
let progressTimer = null
let finishTimer = null

const modes = [
  { id: 'image-image', title: '以图搜图', desc: '上传巡检图，召回相似隐患图片', icon: ImageIcon },
  { id: 'text-image', title: '以文搜图', desc: '输入隐患描述，定位样例图片', icon: Search },
  { id: 'image-text', title: '以图搜文', desc: '上传图片，召回法规和历史报告', icon: FileSearch }
]

const scopes = [
  { id: 'all', label: '全部范围' },
  { id: 'appearance', label: '箱体外观' },
  { id: 'internal', label: '内部组件' }
]

const indexes = [
  { id: 'all', label: '全域索引' },
  { id: 'dataset', label: '训练数据' },
  { id: 'history', label: '检测历史' },
  { id: 'law', label: '法规条文' }
]

const modelPaths = [
  '/opt/models/multimodal/xf_clip_hydrant_demo_v1',
  '/opt/models/multimodal/bge_m3_fire_regulation_demo',
  '/opt/xfagent/artifacts/yolo/fire_hydrant_v3_20260707',
  '/opt/models/multimodal/cross_rerank_hydrant_demo'
]

const demoResults = [
  {
    id: 'img-001',
    mode: ['image-image', 'text-image'],
    type: '相似图片',
    scope: 'internal',
    index: 'dataset',
    title: '软管卷盘供水软管锐角折弯',
    score: 0.972,
    image: '/demo-multimodal/internal-bend.jpg',
    summary: '红色供水软管在卷盘出口附近形成锐角弯折，局部受压，与当前查询高度相似。',
    tags: ['折弯严重', '内部组件', '高置信召回'],
    source: '/opt/datasets/fire-inspection/training_data/v5_YOLO/internal/images/val/val_xf_hydrant_auto_v3_000176.jpg',
    boxes: [
      { label: '软管', x: 47, y: 6, w: 44, h: 28 },
      { label: '接口', x: 30, y: 50, w: 26, h: 28 },
      { label: '水带', x: 58, y: 60, w: 34, h: 24 }
    ],
    reason: ['红色软管曲率突变', '卷盘与接口区域匹配', '隐患标签语义一致']
  },
  {
    id: 'img-002',
    mode: ['image-image', 'text-image'],
    type: '历史图片',
    scope: 'internal',
    index: 'history',
    title: '内部组件缺失复核案例',
    score: 0.918,
    image: '/demo-multimodal/internal-missing.jpg',
    summary: '历史记录中保留了缺失类标签的复核过程，可用于纠正“组件相似但标签误判”的问题。',
    tags: ['缺失复核', '历史记录', '误判修正'],
    source: '/opt/datasets/fire-inspection/training_data/v5_YOLO/internal/images/train/train_xf_hydrant_auto_v3_000467.jpg',
    boxes: [
      { label: '栓体', x: 42, y: 46, w: 28, h: 40 },
      { label: '手轮', x: 49, y: 38, w: 18, h: 12 },
      { label: '接口', x: 56, y: 50, w: 20, h: 18 }
    ],
    reason: ['箱内布局相似', '组件框包含栓体和接口', '适合触发二次复核']
  },
  {
    id: 'img-003',
    mode: ['image-image', 'text-image'],
    type: '外观图片',
    scope: 'appearance',
    index: 'dataset',
    title: '箱门标识清晰但铭牌不可辨',
    score: 0.864,
    image: '/demo-multimodal/external-label.jpg',
    summary: '外观 YOLO 检出中文标识和箱门区域，铭牌区域模糊，适合作为外观证据参考。',
    tags: ['箱体外观', '标识', '铭牌模糊'],
    source: '/opt/datasets/fire-inspection/training_data/v5_YOLO/external/images/val/val_xf_hydrant_auto_v3_001040.jpg',
    boxes: [
      { label: '箱门', x: 24, y: 12, w: 55, h: 70 },
      { label: '中文标识', x: 30, y: 18, w: 43, h: 16 },
      { label: '铭牌', x: 35, y: 58, w: 34, h: 18 }
    ],
    reason: ['外观组件框重叠度高', 'OCR 区域相似', '标识类标签可复用']
  },
  {
    id: 'img-004',
    mode: ['image-image', 'text-image'],
    type: '训练图片',
    scope: 'internal',
    index: 'dataset',
    title: '水带遮挡下的接口识别样例',
    score: 0.835,
    image: '/demo-multimodal/internal-review.jpg',
    summary: '水带和接口存在遮挡关系，适合展示“召回样例 + 局部证据框”的检索效果。',
    tags: ['遮挡场景', '接口定位', '训练样例'],
    source: '/opt/datasets/fire-inspection/training_data/v5_YOLO/internal/images/val/val_xf_hydrant_auto_v3_000114.jpg',
    boxes: [
      { label: '水带', x: 15, y: 10, w: 62, h: 68 },
      { label: '接口', x: 38, y: 58, w: 24, h: 22 }
    ],
    reason: ['图像结构接近', '可解释检测框明确', '用于遮挡样例召回']
  },
  {
    id: 'txt-001',
    mode: ['image-text'],
    type: '法规条文',
    scope: 'internal',
    index: 'law',
    title: '中华人民共和国消防法 第十六条',
    score: 0.941,
    image: '/demo-multimodal/external-door.jpg',
    summary: '单位应按标准配置消防设施、器材，设置消防安全标志，并定期组织检验、维修，确保完好有效。',
    tags: ['上位法', '设施器材', '完好有效'],
    source: 'regulations_extracted/中华人民共和国消防法.txt',
    boxes: [
      { label: '标识', x: 28, y: 16, w: 44, h: 12 },
      { label: '箱门', x: 20, y: 8, w: 60, h: 78 }
    ],
    reason: ['图片涉及设施器材状态', '对应维护和完好有效义务', '可作为报告依据']
  },
  {
    id: 'txt-002',
    mode: ['image-text'],
    type: '历史报告',
    scope: 'appearance',
    index: 'history',
    title: '外观标识与遮挡检查报告片段',
    score: 0.902,
    image: '/demo-multimodal/external-label.jpg',
    summary: '召回历史报告中的外观标识、箱门状态和铭牌可辨识度描述，用于辅助生成整改说明。',
    tags: ['历史报告', '外观证据', '标识检查'],
    source: '/opt/xfagent/vendor/xfdemo/backend/runtime/history/inspection/records.jsonl',
    boxes: [
      { label: '中文标识', x: 30, y: 18, w: 43, h: 16 },
      { label: '箱门', x: 24, y: 12, w: 55, h: 70 }
    ],
    reason: ['历史描述与当前场景接近', '外观证据字段完整', '可作为报告生成参考']
  }
]

const activeModeMeta = computed(() => modes.find((mode) => mode.id === activeMode.value) || modes[0])
const canSearch = computed(() => {
  if (activeMode.value === 'text-image') return query.value.trim().length > 0
  return imageBase64.value || query.value.trim().length > 0
})

const filteredResults = computed(() => {
  const items = demoResults.filter((item) => {
    const modeMatch = item.mode.includes(activeMode.value)
    const scopeMatch = activeScope.value === 'all' || item.scope === activeScope.value
    const indexMatch = activeIndex.value === 'all' || item.index === activeIndex.value
    return modeMatch && scopeMatch && indexMatch
  })
  if (!items.length) return items
  const shift = resultSeed.value % items.length
  return [...items.slice(shift), ...items.slice(0, shift)]
})

const selectedResult = computed(() => filteredResults.value.find((item) => item.id === selectedResultId.value) || filteredResults.value[0] || demoResults[0])
const resultCountText = computed(() => `召回 ${filteredResults.value.length} 条`)

const handleImageUpload = (base64) => {
  imageBase64.value = base64
  hasSearched.value = false
}
const handleImageRemove = () => {
  imageBase64.value = ''
  hasSearched.value = false
}
const switchMode = (id) => {
  activeMode.value = id
  hasSearched.value = true
  progress.value = 100
  selectedResultId.value = demoResults.find((item) => item.mode.includes(id))?.id || demoResults[0].id
}
const clearTimers = () => {
  if (progressTimer) clearInterval(progressTimer)
  if (finishTimer) clearTimeout(finishTimer)
  progressTimer = null
  finishTimer = null
}
const runSearch = () => {
  if (!canSearch.value || isSearching.value) return
  clearTimers()
  resultSeed.value += 1
  isSearching.value = true
  hasSearched.value = false
  progress.value = 12
  const first = filteredResults.value[0] || demoResults.find((item) => item.mode.includes(activeMode.value)) || demoResults[0]
  selectedResultId.value = first.id
  progressTimer = setInterval(() => {
    progress.value = Math.min(progress.value + 14, 92)
  }, 180)
  finishTimer = setTimeout(() => {
    clearTimers()
    progress.value = 100
    isSearching.value = false
    hasSearched.value = true
  }, 1100)
}
const resetSearch = () => {
  clearTimers()
  imageBase64.value = ''
  query.value = ''
  activeScope.value = 'all'
  activeIndex.value = 'all'
  hasSearched.value = false
  isSearching.value = false
  progress.value = 0
}

onBeforeUnmount(clearTimers)
</script>

<template>
  <div class="retrieval-page">
    <div class="retrieval-shell">
      <header class="retrieval-hero">
        <div>
          <p>Multimodal Retrieval</p>
          <h1>多模态检索</h1>
          <span>以图搜图、以文搜图、以图搜文的演示链路。当前页面模拟向量召回、重排、证据框定位和来源追踪。</span>
        </div>
        <button class="hero-action" :disabled="!canSearch || isSearching" @click="runSearch">
          <Sparkles :size="18" />
          {{ isSearching ? '检索中' : '开始演示' }}
        </button>
      </header>

      <section class="mode-strip">
        <button v-for="mode in modes" :key="mode.id" :class="{ active: activeMode === mode.id }" @click="switchMode(mode.id)">
          <component :is="mode.icon" :size="18" />
          <strong>{{ mode.title }}</strong>
          <span>{{ mode.desc }}</span>
        </button>
      </section>

      <section class="retrieval-layout">
        <aside class="query-card">
          <div class="panel-heading"><Search :size="18" />检索输入</div>

          <ImageUploader
            v-if="activeMode !== 'text-image'"
            @upload="handleImageUpload"
            @remove="handleImageRemove"
          />

          <label class="field-label">{{ activeMode === 'text-image' ? '文本描述' : '补充说明' }}</label>
          <textarea v-model="query" rows="4" placeholder="例如：红色软管明显锐角折弯；水枪缺失；箱门标识模糊"></textarea>

          <div class="filter-grid">
            <label>
              <span>索引</span>
              <select v-model="activeIndex">
                <option v-for="item in indexes" :key="item.id" :value="item.id">{{ item.label }}</option>
              </select>
            </label>
            <label>
              <span>范围</span>
              <select v-model="activeScope">
                <option v-for="item in scopes" :key="item.id" :value="item.id">{{ item.label }}</option>
              </select>
            </label>
          </div>

          <div class="query-actions">
            <button class="primary-action" :disabled="!canSearch || isSearching" @click="runSearch">
              <FileSearch :size="17" />
              {{ isSearching ? '检索中...' : '开始检索' }}
            </button>
            <button class="secondary-action" @click="resetSearch">重置</button>
          </div>
        </aside>

        <main class="result-card">
          <div class="result-head">
            <div class="panel-heading"><Layers :size="18" />{{ activeModeMeta.title }}</div>
            <span>{{ resultCountText }}</span>
          </div>

          <div class="search-status">
            <div>
              <strong>{{ isSearching ? '正在生成向量并重排结果' : hasSearched ? '检索完成' : '等待启动' }}</strong>
              <span>图像编码 / 文本编码 / 向量召回 / 证据重排</span>
            </div>
            <small>{{ progress }}%</small>
          </div>
          <div class="progress-track"><div :style="{ width: `${progress}%` }"></div></div>

          <div v-if="!hasSearched && !isSearching" class="empty-state">
            <Camera :size="42" />
            <strong>选择模式并开始检索</strong>
            <p>将展示真实样例图、相似度、检测框、召回依据和模型路径。</p>
          </div>

          <div v-else class="results">
            <button
              v-for="item in filteredResults"
              :key="item.id"
              :class="{ active: selectedResult?.id === item.id }"
              @click="selectedResultId = item.id"
            >
              <div class="result-preview">
                <img :src="item.image" :alt="item.title" />
                <span
                  v-for="box in item.boxes"
                  :key="`${item.id}-${box.label}`"
                  class="detect-box"
                  :style="{ left: `${box.x}%`, top: `${box.y}%`, width: `${box.w}%`, height: `${box.h}%` }"
                >
                  {{ box.label }}
                </span>
              </div>
              <div class="result-body">
                <div class="result-meta">
                  <span>{{ item.type }}</span>
                  <strong>{{ Math.round(item.score * 1000) / 10 }}%</strong>
                </div>
                <h3>{{ item.title }}</h3>
                <p>{{ item.summary }}</p>
                <div class="tag-row"><span v-for="tag in item.tags" :key="tag">{{ tag }}</span></div>
              </div>
            </button>
          </div>

          <section v-if="hasSearched || isSearching" class="selected-detail">
            <div class="detail-title">
              <Database :size="18" />
              <strong>证据详情</strong>
              <span>{{ Math.round(selectedResult.score * 1000) / 10 }}%</span>
            </div>
            <div class="detail-grid">
              <div>
                <h4><BadgeCheck :size="15" />召回原因</h4>
                <ul>
                  <li v-for="reason in selectedResult.reason" :key="reason">{{ reason }}</li>
                </ul>
              </div>
              <div>
                <h4>来源路径</h4>
                <code>{{ selectedResult.source }}</code>
                <h4>模型链路</h4>
                <code v-for="path in modelPaths" :key="path">{{ path }}</code>
              </div>
            </div>
          </section>
        </main>
      </section>
    </div>
  </div>
</template>

<style scoped>
.retrieval-page {
  min-height: 100vh;
  padding: 96px 0 40px;
  background: var(--bg-secondary);
  color: var(--text-primary);
}

.retrieval-shell {
  width: min(1240px, calc(100% - 2rem));
  margin: 0 auto;
}

.retrieval-hero,
.query-card,
.result-card,
.mode-strip button {
  border: 1px solid var(--color-gray-200);
  border-radius: var(--radius-xl);
  background: var(--bg-primary);
  box-shadow: var(--shadow-sm);
}

.retrieval-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-xl);
  padding: 26px 28px;
  margin-bottom: var(--spacing-md);
}

.retrieval-hero p {
  margin: 0;
  color: var(--color-primary);
  font-size: var(--font-size-sm);
  font-weight: 800;
  letter-spacing: .08em;
}

.retrieval-hero h1 {
  margin: var(--spacing-xs) 0;
  font-size: clamp(2rem, 3vw, 2.55rem);
  line-height: 1.12;
}

.retrieval-hero span {
  display: block;
  max-width: 760px;
  color: var(--text-secondary);
  line-height: 1.7;
}

.hero-action,
.primary-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--spacing-sm);
  border: 0;
  border-radius: var(--radius-lg);
  background: var(--color-primary);
  color: var(--text-inverse);
  font-weight: 800;
}

.hero-action {
  min-width: 148px;
  min-height: 46px;
  padding: 0 var(--spacing-lg);
}

.hero-action:disabled,
.primary-action:disabled {
  opacity: .48;
  cursor: not-allowed;
}

.mode-strip {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-md);
}

.mode-strip button {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 2px var(--spacing-sm);
  align-items: center;
  padding: 14px 16px;
  text-align: left;
}

.mode-strip button svg {
  grid-row: span 2;
  color: var(--color-primary);
}

.mode-strip button strong {
  font-size: var(--font-size-base);
}

.mode-strip button span {
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
}

.mode-strip button.active {
  border-color: var(--color-primary);
  background: var(--color-primary-subtle);
}

.retrieval-layout {
  display: grid;
  grid-template-columns: 330px minmax(0, 1fr);
  gap: var(--spacing-md);
  align-items: start;
}

.query-card,
.result-card {
  padding: 22px;
}

.query-card {
  position: sticky;
  top: 96px;
}

.panel-heading {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-md);
  font-weight: 800;
}

.field-label,
.filter-grid span {
  display: block;
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
  font-weight: 700;
}

.field-label {
  margin: var(--spacing-lg) 0 var(--spacing-sm);
}

textarea,
select {
  width: 100%;
  border: 1px solid var(--color-gray-200);
  border-radius: var(--radius-md);
  padding: var(--spacing-md);
  outline: 0;
  background: var(--bg-primary);
  line-height: 1.7;
}

textarea:focus,
select:focus {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-subtle);
}

.filter-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--spacing-sm);
  margin-top: var(--spacing-md);
}

.filter-grid span {
  margin-bottom: var(--spacing-xs);
}

.query-actions {
  display: flex;
  gap: var(--spacing-sm);
  margin-top: var(--spacing-lg);
}

.primary-action,
.secondary-action {
  flex: 1;
  min-height: 42px;
  padding: 0 var(--spacing-md);
}

.secondary-action {
  border-radius: var(--radius-lg);
  background: var(--bg-tertiary);
  color: var(--text-primary);
  font-weight: 800;
}

.result-head,
.search-status,
.result-meta,
.detail-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--spacing-md);
}

.result-head {
  color: var(--text-secondary);
}

.search-status {
  padding: var(--spacing-md);
  border-radius: var(--radius-lg);
  background: var(--bg-secondary);
  margin-bottom: var(--spacing-sm);
}

.search-status strong,
.search-status span {
  display: block;
}

.search-status span {
  margin-top: 2px;
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
}

.search-status small {
  color: var(--color-primary);
  font-weight: 900;
}

.progress-track {
  height: 8px;
  overflow: hidden;
  border-radius: var(--radius-full);
  background: var(--color-gray-100);
  margin-bottom: var(--spacing-md);
}

.progress-track div {
  height: 100%;
  border-radius: inherit;
  background: var(--color-primary);
  transition: width .2s ease;
}

.empty-state {
  min-height: 360px;
  display: grid;
  place-items: center;
  align-content: center;
  gap: var(--spacing-sm);
  text-align: center;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  border: 1px dashed var(--color-gray-200);
  border-radius: var(--radius-lg);
}

.empty-state strong {
  color: var(--text-primary);
  font-size: var(--font-size-lg);
}

.results {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--spacing-md);
}

.results button {
  display: grid;
  grid-template-rows: 180px 1fr;
  width: 100%;
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--color-gray-100);
  border-radius: var(--radius-lg);
  background: var(--bg-primary);
  text-align: left;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast), transform var(--transition-fast);
}

.results button:hover,
.results button.active {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}

.result-preview {
  position: relative;
  min-height: 180px;
  overflow: hidden;
  background: var(--bg-tertiary);
}

.result-preview img {
  width: 100%;
  height: 100%;
  display: block;
  object-fit: cover;
}

.detect-box {
  position: absolute;
  display: flex;
  align-items: flex-start;
  justify-content: flex-start;
  border: 2px solid var(--color-primary);
  border-radius: 4px;
  color: var(--text-inverse);
  font-size: 0;
  box-shadow: 0 0 0 1px rgba(255,255,255,.42);
}

.detect-box::before {
  content: attr(label);
}

.detect-box {
  --badge-size: 24px;
}

.detect-box::after {
  content: attr(label);
  min-width: var(--badge-size);
  height: var(--badge-size);
  margin: -12px 0 0 -12px;
  display: grid;
  place-items: center;
  border: 2px solid #fff;
  border-radius: 999px;
  background: var(--color-primary);
  font-size: var(--font-size-xs);
  font-weight: 900;
}

.result-body {
  padding: var(--spacing-md);
}

.result-meta {
  color: var(--color-primary);
  font-size: var(--font-size-sm);
  font-weight: 800;
}

.results h3 {
  margin: var(--spacing-xs) 0;
  font-size: var(--font-size-lg);
  line-height: 1.35;
}

.results p {
  color: var(--text-secondary);
  line-height: 1.65;
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-xs);
  margin-top: var(--spacing-sm);
}

.tag-row span {
  padding: var(--spacing-xs) var(--spacing-sm);
  border-radius: var(--radius-full);
  background: var(--color-primary-subtle);
  color: var(--color-primary-dark);
  font-size: var(--font-size-sm);
  font-weight: 700;
}

.selected-detail {
  margin-top: var(--spacing-lg);
  padding: var(--spacing-lg);
  border: 1px solid var(--color-gray-100);
  border-radius: var(--radius-lg);
  background: var(--bg-secondary);
}

.detail-title {
  margin-bottom: var(--spacing-md);
  color: var(--color-primary);
}

.detail-title strong {
  margin-right: auto;
  color: var(--text-primary);
}

.detail-grid {
  display: grid;
  grid-template-columns: minmax(0, .9fr) minmax(0, 1.1fr);
  gap: var(--spacing-lg);
}

.selected-detail h4 {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  margin-bottom: var(--spacing-sm);
}

.selected-detail li {
  color: var(--text-secondary);
  line-height: 1.7;
}

.selected-detail code {
  display: block;
  word-break: break-all;
  white-space: normal;
  margin: var(--spacing-xs) 0 var(--spacing-sm);
  padding: var(--spacing-sm);
  border-radius: var(--radius-md);
  background: var(--bg-primary);
  color: var(--text-secondary);
  font-size: var(--font-size-xs);
}

@media (max-width: 1080px) {
  .retrieval-layout {
    grid-template-columns: 1fr;
  }

  .query-card {
    position: static;
  }
}

@media (max-width: 840px) {
  .retrieval-hero,
  .query-actions {
    flex-direction: column;
    align-items: stretch;
  }

  .mode-strip,
  .results,
  .detail-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .retrieval-page {
    padding-top: 6.5rem;
  }

  .filter-grid {
    grid-template-columns: 1fr;
  }
}
</style>
