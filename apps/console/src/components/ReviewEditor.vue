<script setup>
import { ref, watch, toRaw } from 'vue'
import { post } from '@/api'
import SceneFields from './SceneFields.vue'
const props = defineProps({ report: { type: Object, required: true } })
const emit = defineEmits(['updated'])
const claims = ref([]),
  scene = ref({}),
  comment = ref(''),
  busy = ref(false),
  error = ref(''),
  currentReportId = ref(null)
function deepClone(obj) {
  return obj ? JSON.parse(JSON.stringify(toRaw(obj))) : obj
}
watch(
  () => [props.report.id, props.report.revision],
  () => {
    claims.value = deepClone(props.report.conclusions) || []
    scene.value = deepClone(props.report.scene) || {}
    comment.value = ''
    error.value = ''
    currentReportId.value = props.report.id
  },
  { immediate: true },
)
async function submit(action) {
  if (busy.value || currentReportId.value !== props.report.id) return
  busy.value = true
  error.value = ''
  const reportId = props.report.id,
    revision = props.report.revision
  try {
    const report = await post(`/reports/${reportId}/review`, {
      action,
      expected_revision: revision,
      comment: comment.value,
      conclusions: claims.value,
      confirmed_scene: scene.value,
      cleared_scene_fields: Object.keys(props.report.scene || {}).filter(
        (k) => !(k in scene.value),
      ),
    })
    if (currentReportId.value === reportId) emit('updated', report)
  } catch (e) {
    if (currentReportId.value === reportId) {
      error.value = e.message
      if (e.status === 409) emit('updated', null)
    }
  } finally {
    busy.value = false
  }
}
function add() {
  claims.value.push({
    claim_id: crypto.randomUUID(),
    text: '',
    recommendation: '',
    kind: 'information_request',
    observation_ids: [],
    evidence_ids: [],
    applicability: 'unknown',
    sufficiency: 'insufficient',
    missing_fields: [],
  })
}
</script>
<template>
  <section class="card">
    <h2 class="subheading">审核与修订</h2>
    <p class="muted">
      修改内容会与审核人、时间和原版本一起记录。提交后恢复原任务并重新核验，核验通过才会定稿。
    </p>
    <fieldset :disabled="busy" class="editor-fields">
      <article v-for="(claim, i) in claims" :key="claim.claim_id" class="claim-editor">
        <div class="claim-header">
          <strong>结论 {{ i + 1 }}</strong
          ><button class="btn btn-outline" type="button" @click="claims.splice(i, 1)">删除</button>
        </div>
        <label class="field"
          ><span>结论内容</span
          ><textarea
            v-model="claim.text"
            rows="3"
            maxlength="3000"
            class="input"
            placeholder="描述检查发现的问题或观察结果"
          /></label
        ><label class="field"
          ><span>整改建议</span
          ><textarea
            v-model="claim.recommendation"
            rows="2"
            maxlength="2000"
            class="input"
            placeholder="提出具体的整改措施或补救方案"
          />
        </label>
        <div class="editor-grid">
          <label class="field"
            ><span>结论性质</span
            ><select v-model="claim.kind" class="input">
              <option value="observation">现场观察</option>
              <option value="information_request">待核实事项</option>
              <option value="legal_assessment">法规判断</option>
            </select></label
          ><label class="field"
            ><span>条款适用性</span
            ><select v-model="claim.applicability" class="input">
              <option value="unknown">尚未确认</option>
              <option value="supported">适用</option>
              <option value="not_applicable">不适用</option>
            </select></label
          ><label class="field"
            ><span>材料充分性</span
            ><select v-model="claim.sufficiency" class="input">
              <option value="insufficient">不足</option>
              <option value="sufficient">充分</option>
            </select></label
          >
        </div>
        <label class="field"
          ><span>待补充条件</span
          ><input
            :value="claim.missing_fields.join(', ')"
            class="input"
            placeholder="用逗号分隔；已确认后请清除"
            @input="
              claim.missing_fields = $event.target.value
                .split(/[,，]/)
                .map((x) => x.trim())
                .filter(Boolean)
            "
        /></label>
        <details class="bindings-section">
          <summary>关联现场观察与法规依据</summary>
          <div v-if="report.observations?.length" class="binding-group">
            <strong class="binding-label">现场观察</strong
            ><label v-for="o in report.observations" :key="o.observation_id" class="binding"
              ><input
                v-model="claim.observation_ids"
                type="checkbox"
                :value="o.observation_id"
              /><span>{{ o.description }}</span></label
            >
          </div>
          <div v-if="report.evidence?.length" class="binding-group">
            <strong class="binding-label">法规依据</strong
            ><label v-for="(e, j) in report.evidence" :key="e.evidence_id" class="binding"
              ><input v-model="claim.evidence_ids" type="checkbox" :value="e.evidence_id" /><span
                >[{{ j + 1 }}] {{ e.document_title }} · {{ e.text.slice(0, 90) }}</span
              ></label
            >
          </div>
          <p v-if="!report.observations?.length && !report.evidence?.length" class="muted">
            暂无可关联的观察或依据
          </p>
        </details>
      </article>
      <button type="button" class="btn btn-secondary" @click="add">添加结论</button
      ><SceneFields v-model="scene" /><label class="field"
        ><span>审核意见</span
        ><textarea
          v-model="comment"
          maxlength="3000"
          class="input"
          rows="3"
          placeholder="说明修订依据或需要补充的材料"
        />
      </label>
      <p v-if="error" class="message error" role="alert">{{ error }}</p>
      <div class="actions">
        <button
          type="button"
          class="btn btn-primary"
          :disabled="!claims.length || claims.some((c) => !c.text.trim()) || busy"
          @click="submit('approve')"
        >
          {{ busy ? '提交中…' : '提交并核验定稿' }}</button
        ><button type="button" class="btn btn-secondary" :disabled="busy" @click="submit('return')">
          补充条件后重新生成</button
        ><button type="button" class="btn btn-outline" :disabled="busy" @click="submit('reject')">
          驳回
        </button>
      </div>
    </fieldset>
  </section>
</template>
<style scoped>
.editor-fields {
  border: 0;
  padding: 0;
  min-width: 0;
}
.claim-editor {
  padding: 20px;
  border: 1px solid var(--color-gray-200);
  border-radius: 8px;
  margin-bottom: 20px;
  background: var(--color-gray-50);
}
.claim-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.editor-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
.bindings-section {
  margin-top: 16px;
  border: 1px solid var(--color-gray-200);
  border-radius: 6px;
  padding: 12px;
}
.bindings-section summary {
  cursor: pointer;
  font-weight: 600;
  color: var(--color-primary);
  padding: 8px 0;
}
.binding-group {
  margin: 16px 0;
}
.binding-label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--color-gray-700);
}
.binding {
  display: flex;
  gap: 10px;
  margin: 10px 0;
  font-size: 14px;
  align-items: start;
  padding: 8px;
  border-radius: 4px;
  transition: background 0.2s;
}
.binding:hover {
  background: var(--color-gray-100);
}
.binding input[type='checkbox'] {
  margin-top: 2px;
  flex-shrink: 0;
}
.binding span {
  flex: 1;
}
@media (max-width: 600px) {
  .editor-grid {
    grid-template-columns: 1fr;
  }
}
</style>
