<script setup>
import { onMounted, ref } from 'vue'
import { request, statusLabel } from '@/api'

const rows = ref([])
const error = ref('')
const loading = ref(false)

async function refresh() {
  loading.value = true
  try {
    rows.value = (await request('/reports')).reports
    error.value = ''
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

onMounted(refresh)
</script>

<template>
  <div class="container feature-page">
    <header class="page-heading">
      <div>
        <p class="kicker">REPORT HISTORY</p>
        <h1>报告历史</h1>
        <p>追溯现场问题、模型结论和每一次人工审核。</p>
      </div>
      <div class="actions">
        <button class="btn btn-secondary" :disabled="loading" @click="refresh">刷新</button>
        <router-link to="/inspect" class="btn btn-primary">新建巡检</router-link>
      </div>
    </header>

    <p v-if="error" role="alert" class="message error">{{ error }}</p>
    <p v-if="loading" class="muted">正在加载记录…</p>

    <div v-else-if="!rows.length" class="card empty">
      还没有巡检记录。提交第一份巡检后，可在这里查看。
    </div>

    <article v-for="row in rows" :key="row.id" class="list-card">
      <div>
        <h3>{{ row.query }}</h3>
        <small>{{ new Date(row.created_at * 1000).toLocaleString('zh-CN') }} · v{{ row.revision }}</small>
      </div>
      <div class="actions">
        <span class="pill" :class="row.status === 'approved' ? 'good' : 'warn'">
          {{ statusLabel(row.status) }}
        </span>
        <router-link :to="'/reports/' + row.id" class="btn btn-secondary btn-sm">查看详情</router-link>
      </div>
    </article>
  </div>
</template>
