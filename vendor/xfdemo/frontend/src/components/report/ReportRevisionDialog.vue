<script setup>
import { computed, onBeforeUnmount, onMounted } from 'vue'
import ReportEditor from '@/components/report/ReportEditor.vue'

const props = defineProps({
  record: {
    type: Object,
    required: true
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

const effectiveDocument = computed(() => props.record?.effectiveReportDocument || null)
const modelDocument = computed(() => (
  props.record?.modelReportDocument || effectiveDocument.value
))
const baseRevisionId = computed(() => (
  props.record?.reportRevisionSummary?.latest?.id || ''
))

const cancel = () => {
  if (!props.saving) emit('cancel')
}

const handleKeydown = (event) => {
  if (event.key === 'Escape') cancel()
}

onMounted(() => window.addEventListener('keydown', handleKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', handleKeydown))
</script>

<template>
  <Teleport to="body">
    <div class="report-revision-dialog" role="dialog" aria-modal="true" aria-label="人工修订检测报告">
      <div class="report-revision-dialog__panel">
        <ReportEditor
          v-if="effectiveDocument && modelDocument"
          class="report-revision-dialog__editor"
          :model-value="effectiveDocument"
          :model-document="modelDocument"
          :base-revision-id="baseRevisionId"
          :saving="saving"
          :error="error"
          @save="emit('save', $event)"
          @cancel="cancel"
        />
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.report-revision-dialog {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(21, 23, 27, 0.58);
  backdrop-filter: blur(3px);
}

.report-revision-dialog__panel {
  width: min(860px, 100%);
  max-height: calc(100vh - 48px);
  overflow: auto;
  padding: 26px;
  border: 1px solid rgba(255, 255, 255, 0.72);
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 24px 70px rgba(15, 18, 24, 0.22);
}

.report-revision-dialog__editor {
  margin: 0;
}

.report-revision-dialog__panel :deep(.report-editor) {
  margin: 0;
  padding: 0;
  border: 0;
  background: #fff;
}

@media (max-width: 640px) {
  .report-revision-dialog {
    align-items: end;
    padding: 0;
  }

  .report-revision-dialog__panel {
    width: 100%;
    max-height: 94vh;
    padding: 20px 16px;
    border-radius: 8px 8px 0 0;
  }
}
</style>
