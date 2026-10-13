<script setup>
import { computed, ref, watch } from 'vue'
import { post, statusLabel, safeSource } from '@/api'
import { authState } from '@/stores/auth'
import ReviewEditor from './ReviewEditor.vue'
import VisualEvidence from './VisualEvidence.vue'

const props = defineProps({
  report: { type: Object, required: true },
  review: { type: Boolean, default: false }
})
const emit = defineEmits(['updated'])

const busy = ref(false)
const comment = ref('')
const error = ref('')
const currentReportId = ref(null)

const canReview = computed(() =>
  props.review &&
  ['reviewer', 'admin'].includes(authState.user?.role) &&
  ['pending', 'blocked', 'returned'].includes(props.report.status)
)

const canRevise = computed(() =>
  !props.report.durable_status && ['returned', 'blocked', 'failed'].includes(props.report.status) &&
  (props.report.owner === authState.user?.username || authState.user?.role === 'admin')
)

const numbering = computed(() =>
  new Map((props.report.evidence || []).map((e, i) => [e.evidence_id, i + 1]))
)

// Clear comment when switching between reports in review mode
watch(() => props.report.id, (newId) => {
  currentReportId.value = newId
  comment.value = ''
  error.value = ''
}, { immediate: true })

async function act(action) {
  if (busy.value || currentReportId.value !== props.report.id) return
  const reportId = props.report.id
  const revision = props.report.revision
  busy.value = true
  error.value = ''
  try {
    const result = await post('/reports/' + reportId + '/review', {
      expected_revision: revision,
      action,
      comment: comment.value
    })
    if (currentReportId.value === reportId) {
      comment.value = ''
      emit('updated', result)
    }
  } catch (e) {
    if (currentReportId.value === reportId) {
      error.value = e.message
      if (e.status === 409) emit('updated', null)
    }
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
    <VisualEvidence :report="report"/>
    <section class="card">
      <div class="page-heading">
        <div>
          <h2>{{ report.query }}</h2>
          <p class="report-meta">{{ report.id.slice(0, 12) }} · v{{ report.revision }} · {{ new Date(report.created_at * 1000).toLocaleString('zh-CN') }}</p>
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

      <article v-if="report.conclusions?.length" class="conclusions-section">
        <h3 class="section-title">审核结论</h3>
        <div v-for="(claim, i) in report.conclusions" :key="claim.claim_id" class="conclusion-block">
          <div class="conclusion-header">
            <strong>{{ i + 1 }}. {{ claim.text }}</strong>
            <div class="conclusion-badges">
              <span class="badge" :class="claim.kind">{{ {observation:'现场观察',information_request:'待核实',legal_assessment:'法规判断'}[claim.kind] }}</span>
              <span v-if="claim.applicability==='supported'" class="badge good">适用</span>
              <span v-if="claim.applicability==='not_applicable'" class="badge muted">不适用</span>
              <span v-if="claim.sufficiency==='sufficient'" class="badge good">材料充分</span>
              <span v-if="claim.sufficiency==='insufficient'" class="badge warn">材料不足</span>
            </div>
          </div>
          <p v-if="claim.recommendation" class="recommendation">整改建议：{{ claim.recommendation }}</p>
          <div v-if="claim.missing_fields?.length" class="missing-fields">
            <strong>待补充条件：</strong>{{ claim.missing_fields.join('、') }}
          </div>
          <div v-if="claim.observation_ids?.length||claim.evidence_ids?.length" class="claim-references">
            <span v-if="claim.observation_ids?.length" class="ref-group">关联观察 {{ claim.observation_ids.length }} 项</span>
            <span v-if="claim.evidence_ids?.length" class="ref-group">关联依据
              <a v-for="eid in claim.evidence_ids" :key="eid" :href="'#ev-'+report.id+'-'+numbering.get(eid)" class="citation" @click.prevent="expand('ev-'+report.id+'-'+numbering.get(eid))">[{{ numbering.get(eid) }}]</a>
            </span>
          </div>
        </div>
      </article>

      <article v-for="(hazard, i) in (report.conclusions ? [] : report.answer?.hazards || [])" :key="i" class="report-block">
        <h3>{{ i + 1 }}. {{ hazard.description }}</h3>
        <p v-if="hazard.suggestion">整改建议：{{ hazard.suggestion }}</p>
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
        <button v-if="report.durable_status === 'failed'" class="btn btn-secondary" @click="post('/jobs/'+report.id+'/resume',{}).then(()=>emit('updated',null)).catch(e=>error=e.message)">从检查点恢复</button>
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

    <ReviewEditor v-if="canReview && report.conclusions" :report="report" @updated="emit('updated', $event)"/>
    <section v-if="canReview && !report.conclusions" class="card review-section">
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

.report-meta {
  color: var(--color-gray-600);
  font-size: 14px;
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

.conclusions-section {
  margin: 24px 0;
  padding: 20px;
  background: var(--color-gray-50);
  border-radius: 8px;
  border: 1px solid var(--color-gray-200);
}

.section-title {
  font-size: 18px;
  font-weight: 650;
  margin-bottom: 16px;
  color: var(--color-gray-900);
}

.conclusion-block {
  background: white;
  border: 1px solid var(--color-gray-200);
  border-radius: 6px;
  padding: 16px;
  margin-bottom: 16px;
}

.conclusion-header {
  display: flex;
  justify-content: space-between;
  align-items: start;
  gap: 12px;
  margin-bottom: 12px;
}

.conclusion-header strong {
  flex: 1;
  font-size: 15px;
  line-height: 1.5;
}

.conclusion-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.badge {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.badge.observation {
  background: var(--color-blue-100);
  color: var(--color-blue-700);
}

.badge.information_request {
  background: var(--color-orange-100);
  color: var(--color-orange-700);
}

.badge.legal_assessment {
  background: var(--color-purple-100);
  color: var(--color-purple-700);
}

.badge.good {
  background: var(--color-green-100);
  color: var(--color-green-700);
}

.badge.warn {
  background: var(--color-red-100);
  color: var(--color-red-700);
}

.badge.muted {
  background: var(--color-gray-100);
  color: var(--color-gray-600);
}

.recommendation {
  margin: 8px 0;
  padding: 10px;
  background: var(--color-blue-50);
  border-left: 3px solid var(--color-primary);
  border-radius: 4px;
  font-size: 14px;
}

.missing-fields {
  margin: 8px 0;
  padding: 10px;
  background: var(--color-orange-50);
  border-left: 3px solid var(--color-orange-500);
  border-radius: 4px;
  font-size: 13px;
}

.missing-fields strong {
  color: var(--color-orange-700);
}

.claim-references {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 10px;
  font-size: 13px;
  color: var(--color-gray-600);
}

.ref-group {
  display: flex;
  align-items: center;
  gap: 6px;
}

@media (max-width: 600px) {
  .conclusion-header {
    flex-direction: column;
  }

  .conclusion-badges {
    width: 100%;
  }
}
</style>
