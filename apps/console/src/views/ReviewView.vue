<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { request, statusLabel } from '@/api'
import { authState } from '@/stores/auth'
import ReportBody from '@/components/ReportBody.vue'

const route = useRoute()
const rows = ref([])
const selected = ref(null)
const error = ref('')
let generation = 0
let timer = null

const allowed = ['reviewer', 'admin'].includes(authState.user?.role)

async function choose(id) {
  const epoch = ++generation
  selected.value = null
  error.value = ''
  try {
    const result = await request('/reports/' + encodeURIComponent(id))
    if (epoch === generation) selected.value = result
  } catch (e) {
    if (epoch === generation) error.value = e.message
  }
}

async function refresh() {
  if (!allowed) return
  try {
    rows.value = (await request('/reports')).reports.filter((r) =>
      ['pending', 'blocked', 'returned'].includes(r.status),
    )
    error.value = ''
  } catch (e) {
    error.value = e.message
  }
}

async function updated(report) {
  if (report) selected.value = report
  else if (selected.value) await choose(selected.value.id)
  await refresh()
  if (report && ['queued', 'running'].includes(report.status)) poll(report.id)
}
function poll(id) {
  clearTimeout(timer)
  timer = setTimeout(async () => {
    if (selected.value?.id !== id) return
    try {
      const r = await request('/reports/' + id)
      if (selected.value?.id !== id) return
      selected.value = r
      if (['queued', 'running'].includes(r.status)) poll(id)
      else await refresh()
    } catch (e) {
      error.value = e.message
    }
  }, 1500)
}

onMounted(async () => {
  await refresh()
  if (allowed && route.query.report) await choose(route.query.report)
})

onBeforeUnmount(() => {
  generation++
  clearTimeout(timer)
})
</script>

<template>
  <div class="container feature-page">
    <header class="page-heading">
      <div>
        <h1>人工审核</h1>
        <p>逐份核对现场、引用和结论，保留审核意见与版本记录。</p>
      </div>
      <button v-if="allowed" class="btn btn-secondary" @click="refresh">刷新待审队列</button>
    </header>

    <div v-if="!allowed" class="card empty">
      当前账号为巡检员。请由复核员或管理员登录后审核报告。
    </div>

    <template v-else>
      <p v-if="error" class="message error" role="alert">{{ error }}</p>
      <div class="review-layout">
        <aside class="review-sidebar">
          <p class="muted">最近 100 份报告中的待审项 · {{ rows.length }} 份</p>
          <button
            v-for="row in rows"
            :key="row.id"
            class="review-item card"
            :class="{ selected: selected?.id === row.id }"
            @click="choose(row.id)"
          >
            <strong>{{ row.query }}</strong>
            <span>{{ statusLabel(row.status) }} · v{{ row.revision }}</span>
          </button>
          <p v-if="!rows.length" class="empty">暂无待审核报告。</p>
        </aside>
        <ReportBody v-if="selected" :report="selected" review @updated="updated" />
        <div v-else class="card empty">从左侧选择一份报告开始核查。</div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.review-layout {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: 24px;
}

.review-sidebar {
  display: flex;
  flex-direction: column;
}

.review-item {
  display: block;
  width: 100%;
  text-align: left;
  margin-top: 12px;
  padding: 17px;
  border: 1px solid var(--color-gray-200);
  transition:
    border-color var(--transition-fast),
    background var(--transition-fast);
}

.review-item:hover {
  border-color: var(--color-gray-300);
}

.review-item strong {
  display: block;
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.review-item span {
  display: block;
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}

.review-item.selected {
  border-color: var(--color-primary);
  background: #fff8f7;
}

@media (max-width: 900px) {
  .review-layout {
    grid-template-columns: 1fr;
  }

  .review-sidebar {
    max-height: 400px;
    overflow-y: auto;
  }
}
</style>
