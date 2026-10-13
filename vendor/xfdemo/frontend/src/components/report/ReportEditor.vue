<script setup>
import { computed, ref, watch } from 'vue'
import { Save, X } from 'lucide-vue-next'

const props = defineProps({
  modelValue: {
    type: Object,
    required: true
  },
  modelDocument: {
    type: Object,
    required: true
  },
  baseRevisionId: {
    type: String,
    default: ''
  },
  saving: {
    type: Boolean,
    default: false
  },
  error: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['save', 'cancel'])
const draft = ref({})
const reviewNote = ref('')
const reviewNoteDirty = ref(false)

const verdictLabels = {
  qualified: '合格',
  unqualified: '不合格',
  unknown: '无法判断'
}
const fieldLabels = {
  conclusion: '结论说明',
  regulations: '涉及法律法规',
  recommendations: '整改建议'
}

const cloneDocument = (document) => JSON.parse(JSON.stringify(document || {}))

watch(
  () => props.modelValue,
  (value) => {
    draft.value = cloneDocument(value)
    reviewNote.value = ''
    reviewNoteDirty.value = false
  },
  { immediate: true, deep: true }
)

const changedFromModel = computed(() => {
  const fields = ['verdict', 'conclusion', 'regulations', 'recommendations']
  return fields.filter((field) => draft.value?.[field] !== props.modelDocument?.[field])
})

const generatedReviewNote = computed(() => {
  const fields = changedFromModel.value
  if (!fields.length) return '人工复核后确认当前报告内容，无需修正。'
  const sentences = []
  if (fields.includes('verdict')) {
    sentences.push(
      `原模型结论为${verdictLabels[props.modelDocument?.verdict] || '无法判断'}，` +
      `人工复核后修正为${verdictLabels[draft.value?.verdict] || '无法判断'}`
    )
  }
  const sections = fields.filter((field) => field !== 'verdict').map((field) => fieldLabels[field])
  if (sections.length) {
    sentences.push(`${sentences.length ? '同步修正' : '人工复核后修正'}${sections.join('、')}`)
  }
  return `${sentences.join('；')}。`
})

watch(
  generatedReviewNote,
  (value) => {
    if (!reviewNoteDirty.value) reviewNote.value = value
  },
  { immediate: true }
)

const canSave = computed(() => (
  !props.saving &&
  draft.value?.verdict &&
  String(draft.value?.conclusion || '').trim() &&
  String(draft.value?.regulations || '').trim() &&
  String(draft.value?.recommendations || '').trim() &&
  String(reviewNote.value || '').trim()
))

const markReviewNoteDirty = () => {
  reviewNoteDirty.value = true
}

const save = () => {
  if (!canSave.value) return
  emit('save', {
    baseRevisionId: props.baseRevisionId,
    document: cloneDocument(draft.value),
    reviewNote: reviewNote.value.trim()
  })
}
</script>

<template>
  <form class="report-editor" @submit.prevent="save">
    <div class="report-editor__topline">
      <div>
        <h3>人工修订报告</h3>
        <p>以模型报告为底稿修改，保存后会生成新的可追溯版本。</p>
      </div>
      <button class="report-editor__icon" type="button" title="取消修订" @click="emit('cancel')">
        <X :size="20" />
      </button>
    </div>

    <fieldset class="report-editor__field">
      <legend>检测结论</legend>
      <div class="report-editor__segments">
        <label v-for="(label, value) in verdictLabels" :key="value">
          <input v-model="draft.verdict" type="radio" :value="value" />
          <span>{{ label }}</span>
        </label>
      </div>
    </fieldset>

    <label class="report-editor__field">
      <span>结论说明</span>
      <textarea v-model="draft.conclusion" rows="7" maxlength="6000"></textarea>
    </label>

    <label class="report-editor__field">
      <span>涉及法律法规</span>
      <textarea v-model="draft.regulations" rows="5" maxlength="6000"></textarea>
    </label>

    <label class="report-editor__field">
      <span>整改建议</span>
      <textarea v-model="draft.recommendations" rows="5" maxlength="6000"></textarea>
    </label>

    <label class="report-editor__field report-editor__field--review">
      <span>复核说明</span>
      <textarea
        v-model="reviewNote"
        rows="3"
        maxlength="2000"
        placeholder="说明人工判断依据和主要修改内容"
        @input="markReviewNoteDirty"
      ></textarea>
      <small>已根据模型原报告和当前修改自动生成，可继续补充。</small>
    </label>

    <p v-if="error" class="report-editor__error">{{ error }}</p>

    <div class="report-editor__actions">
      <button type="button" class="report-editor__button report-editor__button--secondary" @click="emit('cancel')">
        取消
      </button>
      <button type="submit" class="report-editor__button report-editor__button--primary" :disabled="!canSave">
        <Save :size="18" />
        {{ saving ? '保存中...' : '保存修订' }}
      </button>
    </div>
  </form>
</template>

<style scoped>
.report-editor {
  margin-top: 18px;
  padding: 24px;
  border: 1px solid #e2e3e6;
  border-radius: 8px;
  background: #fafafa;
}

.report-editor__topline {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 24px;
}

.report-editor__topline h3 {
  margin: 0;
  font-size: 20px;
  letter-spacing: 0;
}

.report-editor__topline p {
  margin: 6px 0 0;
  color: #777b82;
  font-size: 14px;
}

.report-editor__icon {
  display: inline-grid;
  width: 38px;
  height: 38px;
  place-items: center;
  flex: 0 0 auto;
  border: 1px solid #dedfe2;
  border-radius: 6px;
  background: #fff;
  color: #555960;
  cursor: pointer;
}

.report-editor__field {
  display: block;
  min-width: 0;
  margin: 0 0 20px;
  padding: 0;
  border: 0;
}

.report-editor__field > span,
.report-editor__field legend {
  display: block;
  margin-bottom: 9px;
  color: #34363a;
  font-size: 14px;
  font-weight: 650;
}

.report-editor__field textarea {
  box-sizing: border-box;
  width: 100%;
  resize: vertical;
  padding: 12px 14px;
  border: 1px solid #d9dade;
  border-radius: 6px;
  outline: none;
  background: #fff;
  color: #242424;
  font: inherit;
  font-size: 15px;
  line-height: 1.7;
  transition: border-color 150ms ease, box-shadow 150ms ease;
}

.report-editor__field textarea:focus {
  border-color: #ef3b39;
  box-shadow: 0 0 0 3px rgba(239, 59, 57, 0.1);
}

.report-editor__segments {
  display: inline-grid;
  grid-template-columns: repeat(3, minmax(92px, 1fr));
  padding: 3px;
  border: 1px solid #dedfe2;
  border-radius: 7px;
  background: #fff;
}

.report-editor__segments label {
  position: relative;
}

.report-editor__segments input {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}

.report-editor__segments span {
  display: grid;
  min-height: 38px;
  place-items: center;
  padding: 0 14px;
  border-radius: 5px;
  color: #656971;
  font-size: 14px;
  cursor: pointer;
}

.report-editor__segments input:checked + span {
  background: #ef3b39;
  color: #fff;
  font-weight: 650;
}

.report-editor__field--review {
  padding-top: 20px;
  border-top: 1px solid #e2e3e6;
}

.report-editor__field small {
  display: block;
  margin-top: 7px;
  color: #858991;
}

.report-editor__error {
  margin: -4px 0 18px;
  color: #c92f2d;
  font-size: 14px;
}

.report-editor__actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.report-editor__button {
  display: inline-flex;
  min-height: 42px;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 0 18px;
  border: 1px solid transparent;
  border-radius: 6px;
  font: inherit;
  font-weight: 650;
  cursor: pointer;
}

.report-editor__button--secondary {
  border-color: #d9dade;
  background: #fff;
  color: #4e5157;
}

.report-editor__button--primary {
  background: #ef3b39;
  color: #fff;
}

.report-editor__button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

@media (max-width: 640px) {
  .report-editor {
    padding: 18px;
  }

  .report-editor__segments {
    display: grid;
    width: 100%;
  }

  .report-editor__actions {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }
}
</style>
