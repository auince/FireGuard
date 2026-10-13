<script setup>
defineProps({
  size: {
    type: String,
    default: 'md',
    validator: (v) => ['sm', 'md', 'lg'].includes(v),
  },
  text: {
    type: String,
    default: '',
  },
})
</script>

<template>
  <div class="spinner" :class="`spinner--${size}`">
    <div class="spinner__ring">
      <div class="spinner__ring-inner"></div>
    </div>
    <p v-if="text" class="spinner__text">{{ text }}</p>
  </div>
</template>

<style scoped>
.spinner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--spacing-md);
}

.spinner__ring {
  position: relative;
  border-radius: 50%;
  border: 3px solid var(--color-primary-subtle);
  border-top-color: var(--color-primary);
  animation: spin 0.85s linear infinite;
  backface-visibility: hidden;
  transform: translateZ(0);
  will-change: transform;
}

.spinner--sm .spinner__ring {
  width: 24px;
  height: 24px;
  border-width: 2px;
}

.spinner--md .spinner__ring {
  width: 40px;
  height: 40px;
}

.spinner--lg .spinner__ring {
  width: 56px;
  height: 56px;
  border-width: 4px;
}

.spinner__ring-inner {
  display: none;
}

.spinner__text {
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
