<script setup>
import { ref, watch, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { request } from '@/api'
import ReportBody from '@/components/ReportBody.vue'
import TracePanel from '@/components/TracePanel.vue'

const route = useRoute()
const report = ref(null)
const error = ref('')
let timer = null
let version = 0

async function load(id, epoch) {
  try {
    const result = await request('/reports/' + encodeURIComponent(id))
    if (epoch !== version) return
    report.value = result
    error.value = ''
    if (['queued', 'running'].includes(result.status)) {
      timer = setTimeout(() => load(id, epoch), 1000)
    }
  } catch (e) {
    if (epoch === version) error.value = e.message
  }
}

function restart() {
  clearTimeout(timer)
  report.value = null
  error.value = ''
  load(route.params.id, ++version)
}

watch(() => route.params.id, restart, { immediate: true })
onBeforeUnmount(() => {
  version++
  clearTimeout(timer)
})
</script>

<template>
  <div class="container feature-page">
    <header class="page-heading">
      <div>
        <h1>巡检报告详情</h1>
        <p>现场输入、隐患建议、原文依据与复核记录。</p>
      </div>
      <router-link to="/history" class="btn btn-secondary">返回报告历史</router-link>
    </header>

    <p v-if="error" class="message error" role="alert">
      {{ error }}
      <button class="btn btn-secondary btn-sm" @click="restart">重新加载</button>
    </p>

    <ReportBody v-if="report" :report="report" @updated="restart" />
    <p v-else-if="!error" class="empty">正在读取报告…</p>

    <section v-if="report" class="card trace-section">
      <h2 class="subheading">本次执行进度</h2>
      <TracePanel :trace="report.trace || []" :status="report.status" />
    </section>
  </div>
</template>

<style scoped>
.trace-section {
  margin-top: 20px;
}
</style>
