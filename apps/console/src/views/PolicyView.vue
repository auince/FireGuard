<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { request, post } from '@/api'
import { authState } from '@/stores/auth'
const route = useRoute(),
  rows = ref([]),
  selected = ref(null),
  results = ref(null),
  reports = ref([]),
  chosen = ref([]),
  error = ref(''),
  message = ref(''),
  busy = ref(false),
  reason = ref(''),
  replayJob = ref(null)
const admin = computed(() => authState.user?.role === 'admin'),
  nextPercentage = computed(
    () => ({ 0: 5, 5: 20, 20: 50, 50: 100 })[selected.value?.percentage || 0],
  )
const states = {
  draft: '待验证',
  canary: '灰度中',
  active: '已生效',
  rolled_back: '已回滚',
  deprecated: '已作废',
}
const gates = {
  actual_paired_execution: '完成真实成对回放',
  no_new_paired_regressions: '无新增退化',
  defect_count_not_increased: '缺陷未增加',
  no_critical_citations: '无严重引用问题',
  latency_within_20_percent: '延迟未明显退化',
  candidate_actually_triggered: '候选策略实际触发',
}
const canPublish = computed(() => {
  if (!nextPercentage.value || !results.value?.stats || !results.value?.evaluations) return false
  const { control, treatment } = results.value.stats
  if (selected.value.percentage > 0 && Math.min(control.n, treatment.n) < 100) return false
  if (results.value.stats.regressed) return false
  return results.value.evaluations.some((x) => x.status === 'passed')
})
const eligibleReports = computed(() =>
  reports.value.filter(
    (r) =>
      ['awaiting_review', 'awaiting_information', 'complete'].includes(r.durable_status) &&
      r.project_id === selected.value?.project_id,
  ),
)
let generation = 0,
  timer = null,
  alive = true
async function load() {
  rows.value = await request('/policies')
  reports.value = (await request('/reports')).reports
}
async function choose(row) {
  const epoch = ++generation
  selected.value = row
  chosen.value = []
  results.value = null
  replayJob.value = null
  clearTimeout(timer)
  error.value = ''
  try {
    const r = await request(`/policies/${row.id}/results`)
    if (epoch === generation) results.value = r
  } catch (e) {
    if (epoch === generation) error.value = e.message
  }
}
async function refresh() {
  try {
    await load()
    const p = rows.value.find((r) => r.id === selected.value?.id)
    if (p) await choose(p)
  } catch (e) {
    error.value = e.message
  }
}
async function action(name, body = {}) {
  if (busy.value || !selected.value) return
  const id = selected.value.id,
    policyVersion = selected.value.version,
    epoch = generation
  busy.value = true
  error.value = ''
  message.value = ''
  try {
    const result = await post(`/policies/${id}/${name}`, body)
    if (epoch !== generation) return
    message.value = name === 'replay' ? '回放任务已排队；完成后显示验证结果。' : '操作已完成'
    if (name === 'replay') {
      replayJob.value = result.id
      poll(result.id, id, policyVersion)
    } else await refresh()
  } catch (e) {
    if (epoch === generation) error.value = e.message
  } finally {
    busy.value = false
  }
}
async function poll(jobId, policyId, policyVersion) {
  try {
    const job = await request('/jobs/' + jobId)
    if (!alive) return
    if (selected.value?.id !== policyId || selected.value?.version !== policyVersion) {
      replayJob.value = null
      busy.value = false
      return
    }
    if (['queued', 'running'].includes(job.status))
      timer = setTimeout(() => poll(jobId, policyId, policyVersion), 2000)
    else {
      replayJob.value = null
      busy.value = false
      await refresh()
      if (job.status === 'failed') error.value = job.error || '回放失败'
    }
  } catch (e) {
    error.value = e.message
    replayJob.value = null
    busy.value = false
  }
}
function publish() {
  if (
    window.confirm(
      `将此策略发布到 ${nextPercentage.value}% 灰度范围？\n\n服务端将校验：\n- 回放结果与当前策略版本匹配\n- 使用真实模型和知识快照\n- 满足灰度扩量条件`,
    )
  )
    action('publish', {
      percentage: nextPercentage.value,
      expected_revision: selected.value.version,
    })
}
function rollback() {
  if (window.confirm('回滚此策略并立即恢复基础策略？')) action('rollback', { reason: reason.value })
}
onMounted(async () => {
  try {
    await load()
    const p =
      rows.value.find((r) => r.id === route.query.id) ||
      rows.value.find((r) => r.id !== 'baseline-v2')
    if (p) await choose(p)
  } catch (e) {
    error.value = e.message
  }
})
onBeforeUnmount(() => {
  alive = false
  generation++
  clearTimeout(timer)
})
</script>
<template>
  <main class="container feature-page">
    <header class="page-heading">
      <div>
        <h1>策略管理</h1>
        <p>检查反馈生成的候选，回放历史任务，验证后逐步发布。</p>
      </div>
      <button class="btn btn-secondary" @click="refresh">刷新</button>
    </header>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <p v-if="message" class="message success" role="status">{{ message }}</p>
    <div class="policy-layout">
      <aside class="card">
        <h2 class="subheading">策略版本</h2>
        <button
          v-for="p in rows"
          :key="p.id"
          class="policy-item"
          :class="{ selected: selected?.id === p.id }"
          @click="choose(p)"
        >
          <strong>{{ p.spec.name }}</strong
          ><span
            >{{ states[p.state] || p.state }} · v{{ p.version }} · {{ p.percentage || 0 }}%</span
          >
        </button>
        <p v-if="!rows.length" class="empty">暂无策略</p>
      </aside>
      <div v-if="selected" class="stack">
        <section class="card">
          <div class="page-heading">
            <div>
              <h2>{{ selected.spec.name }}</h2>
              <p>
                {{
                  { skill: '检索策略', hook: '节点规则', rule: '现场条件约束' }[selected.spec.kind]
                }}
                · {{ states[selected.state] }}
              </p>
            </div>
            <span class="pill">版本 {{ selected.version }}</span>
          </div>
          <dl class="policy-spec">
            <dt>触发词</dt>
            <dd>{{ selected.spec.trigger_terms.join('、') || '符合设施范围的任务' }}</dd>
            <dt>检索扩展词</dt>
            <dd>{{ selected.spec.expand_terms.join('、') || '无' }}</dd>
            <dt>证据条数</dt>
            <dd>{{ selected.spec.evidence_k }}</dd>
            <dt>补充条件</dt>
            <dd>{{ selected.spec.require_fields.join('、') || '无' }}</dd>
            <dt>模板</dt>
            <dd>
              {{
                {
                  standard: '标准核查',
                  measurement_required: '补测提示',
                  version_conflict: '版本冲突核查',
                  risk_action_evidence: '风险、措施和依据',
                }[selected.spec.template]
              }}
            </dd>
          </dl>
          <p v-if="selected.rollback_reason" class="message">
            回滚原因：{{ selected.rollback_reason }}
          </p>
          <p v-if="selected.id === 'baseline-v2'" class="message">
            基础策略由版本控制维护，不通过本页面修改或回滚。
          </p>
        </section>
        <section class="card">
          <h2 class="subheading">回放与发布门槛</h2>
          <p class="muted">
            选择 3—60
            条开发任务进行同模型、同知识快照的成对回放。测试验收集不能参与策略优化。无真实回放结果时不允许发布。
          </p>
          <template v-if="admin && selected.state === 'draft' && selected.id !== 'baseline-v2'"
            ><div class="replay-selection">
              <label v-for="r in eligibleReports" :key="r.id"
                ><input
                  v-model="chosen"
                  type="checkbox"
                  :value="r.id"
                  :disabled="busy || !!replayJob"
                />{{ r.query }} · {{ r.id.slice(0, 8) }}</label
              >
            </div>
            <p v-if="chosen.length > 0 && chosen.length < 3" class="message">至少选择 3 条任务</p>
            <p v-if="chosen.length > 60" class="message error">最多选择 60 条任务</p>
            <button
              class="btn btn-primary"
              :disabled="busy || !!replayJob || chosen.length < 3 || chosen.length > 60"
              @click="action('replay', { run_ids: chosen })"
            >
              {{ replayJob ? '正在回放…' : '运行回放（已选 ' + chosen.length + ' 条）' }}
            </button></template
          >
          <article
            v-for="evaluation in results?.evaluations || []"
            :key="evaluation.id"
            class="evaluation"
          >
            <strong>{{ evaluation.status === 'passed' ? '验证通过' : '验证未通过' }}</strong>
            <p class="muted">
              {{ new Date(evaluation.created_at).toLocaleString('zh-CN') }} ·
              工程回归，不代表专家准确率
            </p>
            <ul>
              <li v-for="(passed, key) in evaluation.gates" :key="key">
                {{ passed ? '✓' : '×' }} {{ gates[key] || key }}
              </li>
            </ul>
          </article>
          <p v-if="!results?.evaluations?.length" class="empty">尚无回放验证结果</p>
        </section>
        <section v-if="results" class="card">
          <h2 class="subheading">灰度观测</h2>
          <template v-if="results.stats"
            ><div class="metrics-grid">
              <article v-for="group in ['control', 'treatment']" :key="group">
                <h3>{{ group === 'control' ? '基础策略组' : '候选策略组' }}</h3>
                <p>完成样本 {{ results.stats[group].n }} 条</p>
                <p>
                  错误率
                  {{
                    results.stats[group].n > 0
                      ? (results.stats[group].error_rate * 100).toFixed(1) + '%'
                      : '暂无'
                  }}
                </p>
                <p>
                  P95
                  {{
                    results.stats[group].n > 0
                      ? Number(results.stats[group].p95).toFixed(2) + 's'
                      : '暂无'
                  }}
                </p>
              </article>
            </div>
            <p class="muted">
              按稳定哈希分组。每组至少 100 条已完成记录后，才判断扩量条件；严重引用问题可立即回滚。
            </p>
            <p
              v-if="
                selected.percentage > 0 &&
                Math.min(results.stats.control.n, results.stats.treatment.n) < 100
              "
              class="message"
            >
              每组至少 100 条完成样本后才能扩量
            </p>
            <p v-if="results.stats.regressed" class="message error">指标退化，禁止扩量</p></template
          >
          <p v-else class="muted">尚无灰度数据</p>
          <div v-if="admin && selected.id !== 'baseline-v2'" class="actions">
            <button
              v-if="selected.spec.kind === 'rule' && !selected.rule_reviewed"
              class="btn btn-secondary"
              :disabled="busy"
              @click="action('rule-review')"
            >
              确认此版本约束内容</button
            ><button
              v-if="nextPercentage && !['rolled_back', 'deprecated'].includes(selected.state)"
              class="btn btn-primary"
              :disabled="busy || !canPublish"
              @click="publish"
            >
              发布至 {{ nextPercentage }}%
            </button>
          </div>
          <div
            v-if="
              admin &&
              ['active', 'canary'].includes(selected.state) &&
              selected.id !== 'baseline-v2'
            "
            class="rollback"
          >
            <label class="field"
              ><span>回滚原因</span><input v-model="reason" class="input" maxlength="2000" /></label
            ><button class="btn btn-outline" :disabled="busy || !reason.trim()" @click="rollback">
              回滚到基础策略
            </button>
          </div>
        </section>
      </div>
      <section v-else class="card empty">选择一项策略查看内容和验证状态</section>
    </div>
  </main>
</template>
<style scoped>
.policy-layout {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 24px;
}
.policy-item {
  display: grid;
  text-align: left;
  width: 100%;
  padding: 14px 10px;
  gap: 5px;
  border-bottom: 1px solid var(--color-gray-200);
}
.policy-item.selected {
  background: var(--color-primary-subtle);
}
.policy-item span {
  color: var(--text-secondary);
  font-size: 12px;
}
.policy-spec {
  display: grid;
  grid-template-columns: 110px 1fr;
  gap: 12px;
  font-size: 14px;
}
.policy-spec dt {
  color: var(--text-secondary);
}
.replay-selection {
  max-height: 280px;
  overflow: auto;
  margin: 16px 0;
}
.replay-selection label {
  display: flex;
  gap: 10px;
  padding: 10px;
  font-size: 13px;
}
.evaluation {
  padding: 20px 0;
  border-bottom: 1px solid var(--color-gray-200);
}
.evaluation ul {
  list-style: none;
  padding: 0;
  font-size: 13px;
  line-height: 2;
}
.metrics-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}
.metrics-grid article {
  padding: 16px;
  background: var(--bg-secondary);
  border-radius: 8px;
}
.metrics-grid p {
  font-size: 13px;
  margin-top: 8px;
}
.rollback {
  margin-top: 20px;
}
aside.card {
  max-height: 500px;
  overflow-y: auto;
}
@media (max-width: 800px) {
  .policy-layout {
    grid-template-columns: 1fr;
  }
  .metrics-grid {
    grid-template-columns: 1fr;
  }
  aside.card {
    max-height: 250px;
  }
}
</style>
