<script setup>
import { History } from 'lucide-vue-next'

defineProps({
  revisions: {
    type: Array,
    default: () => []
  }
})

const fieldLabels = {
  verdict: '检测结论',
  conclusion: '结论说明',
  regulations: '法律法规',
  recommendations: '整改建议'
}

const changedText = (revision) => (
  (revision?.changedFields || []).map((field) => fieldLabels[field] || field).join('、') || '复核说明'
)
</script>

<template>
  <div class="revision-timeline">
    <div v-if="!revisions.length" class="revision-timeline__empty">暂无人工修订记录</div>
    <article v-for="revision in revisions" v-else :key="revision.id" class="revision-timeline__item">
      <div class="revision-timeline__marker">
        <History :size="15" />
      </div>
      <div class="revision-timeline__content">
        <div class="revision-timeline__meta">
          <strong>v{{ revision.version }} · {{ changedText(revision) }}</strong>
          <span>{{ revision.createdText }} · {{ revision.editor?.name || '当前用户' }}</span>
        </div>
        <p>{{ revision.reviewNote }}</p>
      </div>
    </article>
  </div>
</template>

<style scoped>
.revision-timeline {
  display: grid;
  gap: 0;
}

.revision-timeline__empty {
  padding: 14px 0;
  color: #8a8e95;
  font-size: 14px;
}

.revision-timeline__item {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  gap: 10px;
  padding: 14px 0;
  border-top: 1px solid #ececef;
}

.revision-timeline__item:first-child {
  border-top: 0;
}

.revision-timeline__marker {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border-radius: 50%;
  background: #fff0f0;
  color: #d83735;
}

.revision-timeline__content {
  min-width: 0;
}

.revision-timeline__meta {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}

.revision-timeline__meta strong {
  color: #33353a;
  font-size: 14px;
}

.revision-timeline__meta span {
  flex: 0 0 auto;
  color: #8a8e95;
  font-size: 12px;
}

.revision-timeline__content p {
  margin: 7px 0 0;
  color: #62666d;
  font-size: 14px;
  line-height: 1.65;
}

@media (max-width: 640px) {
  .revision-timeline__meta {
    display: grid;
    gap: 4px;
  }
}
</style>
