<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { request, statusLabel } from '@/api'
import TracePanel from '@/components/TracePanel.vue'

const route = useRoute()
const rows = ref([])
const selected = ref('')
const report = ref(null)
const error = ref('')
let timer = null
let version = 0

const diagnostics = computed(() =>
  JSON.stringify(
    {
      verification: report.value?.verification,
      warnings: report.value?.warnings || [],
      retrieval: report.value?.telemetry || {}
    },
    null,
    2
  )
)

async function poll(id, epoch) {
  try {
    const result = await request('/reports/' + encodeURIComponent(id))
    if (epoch !== version) return
    report.value = result
    if (['queued', 'running'].includes(result.status)) {
      timer = setTimeout(() => poll(id, epoch), 1000)
    }
  } catch (e) {
    if (epoch === version) error.value = e.message
  }
}

function choose() {
  clearTimeout(timer)
  error.value = ''
  report.value = null
  if (selected.value) poll(selected.value, ++version)
}

onMounted(async () => {
  try {
    rows.value = (await request('/reports')).reports
    selected.value = typeof route.query.run === 'string' ? route.query.run : rows.value[0]?.id || ''
    choose()
  } catch (e) {
    error.value = e.message
  }
})

onBeforeUnmount(() => {
  version++
  clearTimeout(timer)
})
</script>

<template>
  <div class="container feature-page">
    <header class="page-heading">
      <div>
        <h1>执行链路</h1>
        <p>查看实际节点顺序、耗时、检索查询和验证结果。</p>
      </div>
      <span class="pill">LangGraph · 固定 DAG</span>
    </header>

    <section class="card">
      <label class="field">
        <span>选择巡检记录</span>
        <select v-model="selected" class="input" @change="choose">
          <option value="">请选择报告</option>
          <option v-for="row in rows" :value="row.id" :key="row.id">
            {{ row.query }} · {{ statusLabel(row.status) }}
          </option>
        </select>
      </label>

      <p v-if="error" class="message error" role="alert">{{ error }}</p>

      <TracePanel :trace="report?.trace || []" :status="report?.status" />

      <p class="muted">节点仅在实际执行完成后显示耗时。等待状态不代表已调用模型。</p>
    </section>

    <div v-if="report" class="split monitor-details">
      <section class="card">
        <h2 class="subheading">运行上下文</h2>
        <p class="muted">模型：{{ report.model || '尚未返回' }}</p>
        <p class="muted">快照：{{ report.snapshot_id || '尚未检索' }}</p>
        <p class="muted">模型调用次数：{{ report.model_calls ?? '尚未返回' }}</p>

        <h3 class="queries-heading">检索查询</h3>
        <p v-for="text in report.queries || []" :key="text" class="audit-line">{{ text }}</p>

        <router-link :to="'/reports/' + report.id" class="btn btn-secondary report-link">
          查看对应报告
        </router-link>
      </section>

      <section class="card">
        <h2 class="subheading">校验与降级信息</h2>
        <p v-if="report.error" class="message error">{{ report.error }}</p>
        <pre class="diagnostics-pre">{{ diagnostics }}</pre>
      </section>
    </div>
  </div>
</template>

<style scoped>
.monitor-details {
  margin-top: 24px;
}

.queries-heading {
  margin-top: 20px;
  margin-bottom: 12px;
  font-size: 15px;
  font-weight: 600;
}

.report-link {
  margin-top: 18px;
}

.diagnostics-pre {
  max-height: 400px;
  overflow: auto;
  padding: 12px;
  background: var(--bg-secondary);
  border-radius: var(--radius-md);
}
</style>
