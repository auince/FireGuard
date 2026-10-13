<script setup>
import { computed } from 'vue'

const props = defineProps({
  document: {
    type: Object,
    default: null
  },
  text: {
    type: String,
    default: ''
  },
  revised: {
    type: Boolean,
    default: false
  }
})

const verdictLabels = {
  qualified: '合格',
  unqualified: '不合格',
  unknown: '无法判断'
}

const parseText = (text) => {
  const lines = String(text || '').split(/\r?\n/)
  const positions = {}
  let verdict = 'unknown'
  lines.forEach((line, index) => {
    const match = line.trim().match(/^([一二三])、(.+)$/)
    if (!match) return
    positions[match[1]] = index
    if (match[1] === '一') {
      const label = match[2].replace(/^检测结论\s*[：:]?\s*/, '').trim()
      verdict = Object.entries(verdictLabels).find(([, value]) => value === label)?.[0] || 'unknown'
    }
  })
  const first = positions['一'] ?? -1
  const second = positions['二'] ?? lines.length
  const third = positions['三'] ?? lines.length
  const body = (start, end) => lines.slice(start, end).join('\n').trim()
  return {
    schemaVersion: 1,
    verdict,
    conclusion: body(first + 1, second),
    regulations: body(second + 1, third),
    recommendations: body(third + 1, lines.length)
  }
}

const report = computed(() => props.document || parseText(props.text))
const verdictText = computed(() => verdictLabels[report.value?.verdict] || '无法判断')
const verdictClass = computed(() => ({
  qualified: 'report-viewer__badge--qualified',
  unqualified: 'report-viewer__badge--unqualified',
  unknown: 'report-viewer__badge--unknown'
}[report.value?.verdict] || 'report-viewer__badge--unknown'))
</script>

<template>
  <div class="report-viewer">
    <section class="report-viewer__section report-viewer__section--primary">
      <div class="report-viewer__heading">
        <span class="report-viewer__index">01</span>
        <h3>检测结论</h3>
        <span :class="['report-viewer__badge', verdictClass]">{{ verdictText }}</span>
        <span v-if="revised" class="report-viewer__revised">已人工修订</span>
      </div>
      <p>{{ report.conclusion }}</p>
    </section>

    <section class="report-viewer__section">
      <div class="report-viewer__heading">
        <span class="report-viewer__index report-viewer__index--neutral">02</span>
        <h3>涉及法律法规</h3>
      </div>
      <p>{{ report.regulations }}</p>
    </section>

    <section class="report-viewer__section">
      <div class="report-viewer__heading">
        <span class="report-viewer__index report-viewer__index--neutral">03</span>
        <h3>整改建议</h3>
      </div>
      <p>{{ report.recommendations }}</p>
    </section>
  </div>
</template>

<style scoped>
.report-viewer {
  color: #242424;
}

.report-viewer__section {
  padding: 24px 0;
  border-top: 1px solid #ececec;
}

.report-viewer__section:first-child {
  padding-top: 4px;
  border-top: 0;
}

.report-viewer__heading {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  margin-bottom: 14px;
}

.report-viewer__heading h3 {
  margin: 0;
  font-size: 20px;
  line-height: 1.35;
  letter-spacing: 0;
}

.report-viewer__index {
  display: inline-grid;
  width: 34px;
  height: 34px;
  place-items: center;
  flex: 0 0 auto;
  border-radius: 6px;
  background: #ef3b39;
  color: #fff;
  font-size: 12px;
  font-weight: 700;
}

.report-viewer__index--neutral {
  background: #f0f1f3;
  color: #4c4f55;
}

.report-viewer__badge,
.report-viewer__revised {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 650;
}

.report-viewer__badge--qualified {
  background: #edf8f1;
  color: #237a45;
}

.report-viewer__badge--unqualified {
  background: #fff0f0;
  color: #c92f2d;
}

.report-viewer__badge--unknown {
  background: #f2f3f5;
  color: #666a71;
}

.report-viewer__revised {
  margin-left: auto;
  background: #fff7e8;
  color: #9a6817;
}

.report-viewer__section p {
  margin: 0;
  white-space: pre-wrap;
  font-size: 17px;
  line-height: 1.9;
  color: #343434;
}

@media (max-width: 640px) {
  .report-viewer__section {
    padding: 20px 0;
  }

  .report-viewer__heading {
    flex-wrap: wrap;
  }

  .report-viewer__heading h3 {
    font-size: 18px;
  }

  .report-viewer__revised {
    margin-left: 0;
  }

  .report-viewer__section p {
    font-size: 16px;
    line-height: 1.8;
  }
}
</style>
