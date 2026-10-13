<script setup>
import { computed, ref, watch } from 'vue'
import { post, statusLabel, safeSource } from '@/api'
import { authState } from '@/stores/auth'

const props = defineProps({
  report: { type: Object, required: true },
  review: { type: Boolean, default: false }
})
const emit = defineEmits(['updated'])

const busy = ref(false)
const comment = ref('')
const error = ref('')

const canReview = computed(() =>
  props.review &&
  ['reviewer', 'admin'].includes(authState.user?.role) &&
  ['pending', 'blocked'].includes(props.report.status)
)

const canRevise = computed(() =>
  ['returned', 'blocked', 'failed'].includes(props.report.status) &&
  (props.report.owner === authState.user?.username || authState.user?.role === 'admin')
)

const numbering = computed(() =>
  new Map((props.report.evidence || []).map((e, i) => [e.evidence_id, i + 1]))
)

// Clear comment when switching between reports in review mode
watch(() => props.report.id, () => {
  comment.value = ''
  error.value = ''
})

async function act(action) {
  if (busy.value) return
  const reportId = props.report.id
  busy.value = true
  error.value = ''
  try {
    const result = await post('/reports/' + props.report.id + '/review', {
      expected_revision: props.report.revision,
      action,
      comment: comment.value
    })
    if (props.report.id !== reportId) return
    comment.value = ''
    emit('updated', result)
  } catch (e) {
    if (props.report.id !== reportId) return
    error.value = e.message
    if (e.status === 409) emit('updated', null)
  } finally {
    busy.value = false
  }
}

function expand(id) {
  const details = document.getElementById(id)
  if (details) { details.open = true; details.scrollIntoView({block: 'center', behavior: 'smooth'}) }
}
</script>

<template>
  <div class="stack">
    <section class="card">
      <div class="page-heading">
        <div>
          <p class="kicker">INSPECTION REPORT</p>
          <h2>{{ report.query }}</h2>
          <p>{{ report.id.slice(0, 12) }} · v{{ report.revision }} · {{ new Date(report.created_at * 1000).toLocaleString('zh-CN') }}</p>
        </div>
        <span class="pill" :class="report.status === 'approved' ? 'good' : 'warn'">
          {{ statusLabel(report.status) }}
        </span>
      </div>

      <p v-if="report.model?.includes('fixture')" class="message">
        仿真演示：本报告的模型响应为测试注入数据。
      </p>

      <p v-if="report.error" class="message error" role="alert">{{ report.error }}</p>

      <p v-else-if="['queued', 'running'].includes(report.status)" class="message" role="status">
        正在执行巡检，请稍候。节点执行记录可在下方或执行链路页查看。
      </p>

      <p v-else class="message" :class="report.verification?.passed ? 'success' : 'error'">
        {{ report.verification?.passed
          ? '验证通过。' + (report.status === 'approved' ? '已由复核员确认定稿。' : report.status === 'pending' ? '等待人工确认。' : '审核状态：' + statusLabel(report.status))
          : '验证未通过，请核查条款或补充现场信息。' }}
        <span v-if="report.verification?.errors?.length">
          {{ report.verification.errors.map(v => typeof v === 'string' ? v : v.code).join('；') }}
        </span>
      </p>

      <div v-if="report.image" class="report-image-container">
        <img :src="report.image" class="report-photo" alt="本报告提交的设施照片">
      </div>

      <article v-for="(hazard, i) in report.answer?.hazards || []" :key="i" class="report-block">
        <h3>{{ i + 1 }}. {{ hazard.description }}</h3>
        <p>整改建议：{{ hazard.suggestion }}</p>
        <div class="citations">
          <a
            v-for="eid in hazard.evidence_ids"
            :key="eid"
            :href="'#ev-' + report.id + '-' + numbering.get(eid)"
            class="citation"
            @click.prevent="expand('ev-' + report.id + '-' + numbering.get(eid))"
          >
            [{{ numbering.get(eid) || '?' }}] 查看依据
          </a>
        </div>
      </article>

      <div v-if="report.answer?.missing_information?.length" class="message missing-info">
        <strong>需要补充的信息</strong>
        <p v-for="text in report.answer.missing_information" :key="text">• {{ text }}</p>
      </div>

      <div class="actions">
        <router-link
          v-if="report.owner === authState.user?.username && report.session_id"
          :to="{path:'/sessions',query:{id:report.session_id}}"
          class="btn btn-primary"
        >
          继续本次会话
        </router-link>
        <router-link v-if="canRevise" :to="{ path: '/inspect', query: { revise: report.id } }" class="btn btn-primary">
          补充并重新生成
        </router-link>
        <router-link :to="{ path: '/monitor', query: { run: report.id } }" class="btn btn-secondary">
          查看执行链路
        </router-link>
        <router-link
          v-if="!review && ['reviewer', 'admin'].includes(authState.user?.role)"
          :to="{ path: '/review', query: { report: report.id } }"
          class="btn btn-outline"
        >
          进入人工审核
        </router-link>
      </div>
    </section>

    <section class="card">
      <h2 class="subheading">
        法规条款依据
        <span class="muted">{{ report.evidence?.length || 0 }} 条</span>
      </h2>
      <p v-if="!report.evidence?.length" class="muted">尚未取得可引用条款。</p>
      <details
        v-for="(item, i) in report.evidence || []"
        :id="'ev-' + report.id + '-' + (i + 1)"
        :key="item.evidence_id"
        class="evidence-card"
      >
        <summary>[{{ i + 1 }}] {{ item.document_title || '条款原文' }}</summary>
        <blockquote>{{ item.text }}</blockquote>
        <p v-if="item.version_id" class="muted">版本：{{ item.version_id }}</p>
        <a
          v-if="safeSource(item.source_url)"
          :href="safeSource(item.source_url)"
          target="_blank"
          rel="noopener noreferrer"
        >
          查看原始来源 ↗
        </a>
      </details>
    </section>

    <section v-if="canReview" class="card review-section">
      <h2 class="subheading">人工审核</h2>
      <p class="muted">批准前重新核验条款和结论。证据不足时，请退回补充。</p>
      <label class="field">
        <span>审核意见</span>
        <textarea
          v-model="comment"
          class="input"
          maxlength="3000"
          placeholder="说明确认结果或需要补充的信息"
          rows="4"
        ></textarea>
      </label>
      <p v-if="error" role="alert" class="message error">{{ error }}</p>
      <div class="actions">
        <button
          class="btn btn-primary"
          :disabled="busy || report.status !== 'pending' || !report.verification?.passed"
          @click="act('approve')"
        >
          {{ busy ? '处理中…' : '批准定稿' }}
        </button>
        <button class="btn btn-secondary" :disabled="busy" @click="act('return')">退回补充</button>
        <button class="btn btn-outline" :disabled="busy" @click="act('reject')">驳回</button>
      </div>
    </section>

    <section v-if="report.reviews?.length" class="card">
      <h2 class="subheading">审核记录</h2>
      <div v-for="(entry, i) in report.reviews" :key="i" class="audit-line">
        <strong>
          {{ entry.reviewer }} · {{ { approve: '批准定稿', return: '退回补充', reject: '驳回' }[entry.action] }}
        </strong>
        <p>{{ entry.comment || '未填写意见' }}</p>
        <small class="muted">{{ new Date(entry.at * 1000).toLocaleString('zh-CN') }}</small>
      </div>
    </section>
  </div>
</template>

<style scoped>
.report-image-container {
  margin: 16px 0;
}

.citations {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}

.missing-info {
  margin-top: 16px;
}

.missing-info strong {
  display: block;
  margin-bottom: 8px;
}

.missing-info p {
  margin: 4px 0;
}

.review-section {
  border: 2px solid var(--color-primary-subtle);
}
</style>
