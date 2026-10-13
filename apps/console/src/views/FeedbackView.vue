<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute } from 'vue-router'
import { request, post } from '@/api'
import { authState } from '@/stores/auth'
const route = useRoute(),
  rows = ref([]),
  reports = ref([]),
  backlog = ref({}),
  run = ref(''),
  signal = ref('correction'),
  category = ref(''),
  text = ref(''),
  error = ref(''),
  message = ref(''),
  busy = ref(false),
  loading = ref(false)
const labels = {
  intent: '意图识别',
  vision: '图片识别',
  retrieval: '条款检索',
  applicability: '条款适用条件',
  generation: '结论生成',
  knowledge_gap: '知识缺口',
  weak_signal: '一般使用反馈',
}
const categories = Object.fromEntries(Object.entries(labels).filter(([k]) => k !== 'weak_signal'))
const revisions = ref({}),
  reasons = ref({})
let timer = null
let alive = true
let submissionKey = crypto.randomUUID()
watch([run, signal, category, text], () => {
  submissionKey = crypto.randomUUID()
})
async function load() {
  if (loading.value) return
  loading.value = true
  try {
    const [newRows, newBacklog] = await Promise.all([
      request('/feedback'),
      request('/improvement/backlog'),
    ])
    rows.value = newRows
    backlog.value = newBacklog
    if (
      alive &&
      newRows.some((r) => ['queued', 'running'].includes(r.job_status || 'unavailable'))
    ) {
      clearTimeout(timer)
      timer = setTimeout(load, 2000)
    }
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}
async function send() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  message.value = ''
  try {
    await request('/feedback', {
      method: 'POST',
      headers: { 'Idempotency-Key': submissionKey },
      body: JSON.stringify({
        run_id: run.value,
        signal: signal.value,
        text: text.value.trim(),
        category: category.value || null,
      }),
    })
    submissionKey = crypto.randomUUID()
    text.value = ''
    category.value = ''
    message.value = '反馈已登记，正在后台处理。'
    await load()
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
async function correct(row) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  const expectedVersion = row.attribution_version ?? 1
  try {
    const result = await post(`/feedback/${row.id}/attribution`, {
      category: revisions.value[row.id],
      reason: reasons.value[row.id]?.trim() || row.text,
      expected_version: expectedVersion,
    })
    row.attribution_version = result.attribution_version
    delete revisions.value[row.id]
    delete reasons.value[row.id]
    message.value = '归因更正已提交'
    await load()
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
onMounted(async () => {
  try {
    reports.value = (await request('/reports')).reports
    run.value = String(route.query.run || reports.value[0]?.id || '')
    await load()
  } catch (e) {
    error.value = e.message
  }
})
onBeforeUnmount(() => {
  alive = false
  clearTimeout(timer)
})
</script>
<template>
  <main class="container feature-page">
    <header class="page-heading">
      <div>
        <h1>反馈中心</h1>
        <p>记录使用中发现的问题，跟踪归因、策略修复与数据补充。</p>
      </div>
      <button class="btn btn-secondary" @click="load" :disabled="loading">
        {{ loading ? '加载中…' : '刷新' }}
      </button>
    </header>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <p v-if="message" class="message success" role="status">{{ message }}</p>
    <div class="split">
      <form class="card" @submit.prevent="send">
        <h2 class="subheading">提交反馈</h2>
        <label class="field"
          ><span>关联巡检记录</span
          ><select v-model="run" required class="input">
            <option value="">请选择</option>
            <option v-for="r in reports" :key="r.id" :value="r.id">{{ r.query }}</option>
          </select></label
        ><label class="field"
          ><span>反馈类型</span
          ><select v-model="signal" class="input">
            <option value="correction">指出问题或纠正结论</option>
            <option value="dislike">结果未满足需求</option>
            <option value="follow_up">补充信息</option>
            <option value="like">结果有帮助</option>
          </select></label
        ><label class="field"
          ><span>问题环节</span
          ><select v-model="category" class="input">
            <option value="">暂不确定，由系统辅助归因</option>
            <option v-for="(label, key) in categories" :key="key" :value="key">{{ label }}</option>
          </select></label
        ><label class="field"
          ><span>具体说明</span
          ><textarea
            v-model="text"
            class="input"
            rows="5"
            maxlength="4000"
            :required="signal !== 'like'"
            placeholder="描述遗漏内容、错误位置或更合理的结论，便于复核与修复。"
          />
        </label>
        <p class="muted">"有帮助"只计为使用反馈，不作为答案正确或自动发布策略的依据。</p>
        <button class="btn btn-primary" :disabled="busy || !run">
          {{ busy ? '提交中…' : '提交反馈' }}
        </button>
      </form>
      <section class="card">
        <h2 class="subheading">数据补充待办</h2>
        <p class="muted">视觉问题进入标注待办；知识缺口进入资料补充，不自动生成法规。</p>
        <article
          v-for="item in [...(backlog.annotation_backlog || []), ...(backlog.knowledge_gaps || [])]"
          :key="item.id"
          class="audit-line"
        >
          <strong>{{ item.query }}</strong>
          <p>{{ item.feedback }}</p>
          <span class="pill">待人工补充</span>
        </article>
        <p
          v-if="!(backlog.annotation_backlog?.length || backlog.knowledge_gaps?.length)"
          class="empty"
        >
          暂无待补充事项
        </p>
      </section>
    </div>
    <section class="card feedback-list">
      <h2 class="subheading">反馈处理记录</h2>
      <p v-if="!rows.length" class="empty">暂无反馈</p>
      <article v-for="row in rows" :key="row.id" class="feedback-row">
        <div class="page-heading">
          <div>
            <strong>{{ labels[row.category] || '等待归因' }}</strong>
            <p>{{ row.text || '结果有帮助' }}</p>
          </div>
          <span class="pill">{{
            {
              queued: '等待处理',
              running: '处理中',
              failed: '处理失败',
              complete: '已处理',
              unavailable: '状态未知',
            }[row.job_status || 'unavailable'] || row.job_status
          }}</span>
        </div>
        <p v-if="row.execution_error" class="message error">{{ row.execution_error }}</p>
        <p v-if="row.attribution?.reason" class="muted">归因说明：{{ row.attribution.reason }}</p>
        <div class="actions">
          <router-link :to="'/reports/' + row.run_id" class="btn btn-outline"
            >查看原报告</router-link
          ><router-link
            v-if="row.candidate_id"
            :to="{ path: '/policies', query: { id: row.candidate_id } }"
            class="btn btn-secondary"
            >查看修复候选</router-link
          >
        </div>
        <details v-if="['reviewer', 'admin'].includes(authState.user?.role)">
          <summary>纠正归因</summary>
          <label class="field"
            ><span>正确的问题环节</span
            ><select v-model="revisions[row.id]" class="input">
              <option v-for="(label, key) in categories" :key="key" :value="key">
                {{ label }}
              </option>
            </select></label
          ><label class="field"
            ><span>更正理由</span
            ><input v-model="reasons[row.id]" maxlength="4000" class="input" /></label
          ><button
            :disabled="busy || !revisions[row.id]"
            class="btn btn-secondary"
            @click="correct(row)"
          >
            提交归因更正
          </button>
        </details>
      </article>
    </section>
  </main>
</template>
<style scoped>
.feedback-list {
  margin-top: 24px;
}
.feedback-row {
  padding: 22px 0;
  border-bottom: 1px solid var(--color-gray-200);
}
.feedback-row:last-child {
  border: 0;
}
.feedback-row p {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.feedback-row details {
  margin-top: 16px;
}
.feedback-row summary {
  cursor: pointer;
  color: var(--text-secondary);
}
@media (max-width: 800px) {
  .split {
    grid-template-columns: 1fr;
  }
}
</style>
