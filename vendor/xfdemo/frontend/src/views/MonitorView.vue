<script setup>
import { computed, onMounted, ref } from 'vue'
import { fetchInspectionMonitor } from '@/api'

const loading = ref(false)
const error = ref('')
const payload = ref({ total: 0, withTrace: 0, stages: [], records: [] })
const ui = {
  title: '\u68c0\u6d4b\u94fe\u8def\u76d1\u63a7',
  subtitle: '\u6309\u6700\u8fd1\u68c0\u6d4b\u5386\u53f2\u7edf\u8ba1 QwenVL\u3001YOLO\u3001\u4e8c\u6b21\u590d\u6838\u4e09\u4e2a\u73af\u8282\u7684\u7a33\u5b9a\u6027\uff0c\u5e2e\u52a9\u5b9a\u4f4d\u54ea\u4e00\u6bb5\u6548\u679c\u4e0d\u597d\u3002',
  refresh: '\u5237\u65b0',
  refreshing: '\u5237\u65b0\u4e2d...',
  stages: '\u9636\u6bb5\u8017\u65f6\u4e0e\u72b6\u6001',
  recent: '\u6700\u8fd1\u95ee\u9898\u6837\u672c',
  noStages: '\u6682\u65e0\u8ffd\u8e2a\u9636\u6bb5\u6570\u636e\uff0c\u5b8c\u6210\u4e00\u6b21\u65b0\u68c0\u6d4b\u540e\u4f1a\u51fa\u73b0\u3002',
  noHistory: '\u6682\u65e0\u68c0\u6d4b\u5386\u53f2\u3002',
  noIssue: '\u6682\u65e0\u660e\u663e\u94fe\u8def\u95ee\u9898',
  unknown: '\u672a\u77e5',
  unknownScope: '\u672a\u77e5\u8303\u56f4',
  noLabels: '\u65e0\u6807\u7b7e',
  warn: '\u63d0\u9192',
  error: '\u5f02\u5e38',
  skipped: '\u8df3\u8fc7',
  avg: '\u5e73\u5747',
  times: '\u6b21',
  loadFailed: '\u76d1\u63a7\u6570\u636e\u8bfb\u53d6\u5931\u8d25'
}

const cards = computed(() => [
  { label: '\u6700\u8fd1\u8bb0\u5f55', value: payload.value.total || 0, hint: `\u6709\u8ffd\u8e2a ${payload.value.withTrace || 0}` },
  { label: '输入 Token', value: payload.value.usage?.inputTokens || 0, hint: `${payload.value.usage?.inputTokensPerSecond || 0} token/s` },
  { label: '输出 Token', value: payload.value.usage?.outputTokens || 0, hint: `${payload.value.usage?.outputTokensPerSecond || 0} token/s` },
  { label: '平均耗时', value: `${payload.value.usage?.avgDurationMs || 0}ms`, hint: '按最近可追溯任务统计' },
  { label: '\u521d\u68c0\u88ab\u4fee\u6b63', value: payload.value.qwenCorrected || 0, hint: 'QwenVL \u4e0e\u6700\u7ec8\u4e0d\u4e00\u81f4' },
  { label: 'YOLO \u53ef\u80fd\u6f0f\u68c0', value: payload.value.yoloPossibleMiss || 0, hint: '\u6700\u7ec8\u6807\u7b7e\u6ca1\u6709\u5019\u9009\u6846' },
  { label: 'YOLO \u53ef\u80fd\u8bef\u62a5', value: payload.value.yoloPossibleFalsePositive || 0, hint: '\u5019\u9009\u6846\u672a\u88ab\u6700\u7ec8\u91c7\u7eb3' },
  { label: '\u5927\u6a21\u578b\u515c\u5e95', value: payload.value.vlmFallbackUsed || 0, hint: '\u6c34\u5e26/\u6c34\u67aa\u7f3a\u5931\u7531\u590d\u6838\u5224\u65ad' },
  { label: '\u9700\u4eba\u5de5\u590d\u6838', value: payload.value.judgeNeedsManualReview || 0, hint: '\u4e8c\u6b21\u590d\u6838\u7f6e\u4fe1\u4e0d\u8db3' }
])

const records = computed(() => payload.value.records || payload.value.recent || [])
const formatDuration = (value) => `${Number(value || 0)}ms`
const issuesOf = (record) => record.trace?.summary?.issues || []
const labelsOf = (record) => record.labels?.length ? record.labels.join('\uff1b') : ui.noLabels
const stageText = (stage) => `${stage.title}\uff1a${ui.avg} ${formatDuration(stage.avgDurationMs)} / ${stage.count} ${ui.times}`

const loadMonitor = async () => {
  loading.value = true
  error.value = ''
  try {
    payload.value = await fetchInspectionMonitor({ limit: 200 })
  } catch (err) {
    error.value = err.message || ui.loadFailed
  } finally {
    loading.value = false
  }
}

onMounted(loadMonitor)
</script>

<template>
  <div class="monitor-page">
    <div class="monitor-page__container container">
      <header class="monitor-hero">
        <div>
          <span>Monitor</span>
          <h1>{{ ui.title }}</h1>
          <p>{{ ui.subtitle }}</p>
        </div>
        <button class="monitor-button" type="button" :disabled="loading" @click="loadMonitor">
          {{ loading ? ui.refreshing : ui.refresh }}
        </button>
      </header>

      <p v-if="error" class="monitor-error">{{ error }}</p>

      <section class="monitor-cards">
        <article v-for="card in cards" :key="card.label" class="monitor-card">
          <span>{{ card.label }}</span>
          <strong>{{ card.value }}</strong>
          <p>{{ card.hint }}</p>
        </article>
      </section>

      <section class="monitor-panel">
        <h2>{{ ui.stages }}</h2>
        <div v-if="payload.stages?.length" class="monitor-stages">
          <div v-for="stage in payload.stages" :key="stage.name" class="monitor-stage">
            <strong>{{ stageText(stage) }}</strong>
            <span>{{ ui.warn }} {{ stage.warn }} / {{ ui.error }} {{ stage.error }} / {{ ui.skipped }} {{ stage.skipped || 0 }}</span>
          </div>
        </div>
        <p v-else class="monitor-empty">{{ ui.noStages }}</p>
      </section>

      <section class="monitor-panel">
        <h2>{{ ui.recent }}</h2>
        <div v-if="records.length" class="monitor-records">
          <article v-for="record in records" :key="record.id" class="monitor-record">
            <img v-if="record.imageUrl" :src="record.imageUrl" :alt="record.id" loading="lazy" />
            <div>
              <div class="monitor-record__top">
                <strong>{{ record.id }}</strong>
                <span>{{ record.verdict || ui.unknown }}</span>
              </div>
              <p>{{ record.createdText }} / {{ record.scope || ui.unknownScope }}</p>
              <p>{{ labelsOf(record) }}</p>
              <div class="monitor-record__issues">
                <span v-for="issue in issuesOf(record)" :key="`${record.id}-${issue.type}`">{{ issue.title }}</span>
                <span v-if="!issuesOf(record).length">{{ ui.noIssue }}</span>
              </div>
            </div>
          </article>
        </div>
        <p v-else class="monitor-empty">{{ ui.noHistory }}</p>
      </section>
    </div>
  </div>
</template>

<style scoped>
.monitor-page { min-height: 100vh; padding: calc(80px + var(--spacing-2xl)) 0 var(--spacing-3xl); background: var(--bg-secondary); }
.monitor-page__container { display: grid; gap: var(--spacing-xl); }
.monitor-hero, .monitor-panel, .monitor-card, .monitor-record { background: var(--bg-primary); border: 1px solid var(--color-gray-100); border-radius: var(--radius-xl); box-shadow: var(--shadow-sm); }
.monitor-hero { display: flex; justify-content: space-between; gap: var(--spacing-xl); align-items: flex-end; padding: var(--spacing-xl); }
.monitor-hero span { color: var(--color-primary); font-weight: 600; }
.monitor-hero h1 { margin: var(--spacing-xs) 0; font-size: var(--font-size-4xl); }
.monitor-hero p, .monitor-card p, .monitor-stage span, .monitor-record p, .monitor-empty { color: var(--text-secondary); }
.monitor-button { min-height: 42px; padding: 0 var(--spacing-lg); border: 0; border-radius: var(--radius-full); background: var(--color-primary); color: var(--text-inverse); }
.monitor-error { color: var(--color-primary); }
.monitor-cards { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: var(--spacing-md); }
.monitor-card { padding: var(--spacing-lg); }
.monitor-card span { color: var(--text-secondary); font-size: var(--font-size-sm); }
.monitor-card strong { display: block; margin: var(--spacing-xs) 0; font-size: var(--font-size-3xl); }
.monitor-panel { padding: var(--spacing-xl); }
.monitor-panel h2 { margin-bottom: var(--spacing-md); font-size: var(--font-size-2xl); }
.monitor-stages, .monitor-records { display: grid; gap: var(--spacing-md); }
.monitor-stage { display: flex; justify-content: space-between; gap: var(--spacing-md); padding: var(--spacing-md); border-left: 4px solid var(--color-primary); border-radius: var(--radius-md); background: var(--bg-secondary); }
.monitor-record { display: grid; grid-template-columns: 160px minmax(0, 1fr); overflow: hidden; }
.monitor-record img { width: 100%; height: 100%; min-height: 128px; object-fit: cover; background: var(--bg-tertiary); }
.monitor-record > div { min-width: 0; padding: var(--spacing-md); }
.monitor-record__top { display: flex; justify-content: space-between; gap: var(--spacing-md); }
.monitor-record__top strong, .monitor-record p { overflow-wrap: anywhere; }
.monitor-record__top span, .monitor-record__issues span { padding: 3px var(--spacing-sm); border-radius: var(--radius-full); background: var(--color-primary-subtle); color: var(--color-primary-dark); font-size: var(--font-size-xs); }
.monitor-record__issues { display: flex; flex-wrap: wrap; gap: var(--spacing-xs); margin-top: var(--spacing-sm); }
@media (max-width: 1100px) { .monitor-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 700px) { .monitor-hero, .monitor-stage, .monitor-record { grid-template-columns: 1fr; flex-direction: column; } .monitor-cards { grid-template-columns: 1fr; } }
</style>
