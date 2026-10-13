<script setup>
import { ref } from 'vue'
import { fileToBase64 } from '@/api'

const emit = defineEmits(['upload', 'remove'])

const isDragging = ref(false)
const preview = ref(null)
const fileInput = ref(null)

const handleDragOver = (e) => {
  e.preventDefault()
  isDragging.value = true
}

const handleDragLeave = () => {
  isDragging.value = false
}

const handleDrop = async (e) => {
  e.preventDefault()
  isDragging.value = false
  const file = e.dataTransfer.files[0]
  if (file && file.type.startsWith('image/')) {
    await processFile(file)
  }
}

const handleFileSelect = async (e) => {
  const file = e.target.files[0]
  if (file) {
    await processFile(file)
  }
}

const processFile = async (file) => {
  try {
    const base64 = await fileToBase64(file)
    preview.value = base64
    emit('upload', base64)
  } catch (error) {
    console.error('图片处理失败:', error)
  }
}

const triggerFileSelect = () => {
  fileInput.value?.click()
}

const removeImage = () => {
  preview.value = null
  if (fileInput.value) {
    fileInput.value.value = ''
  }
  emit('remove')
}
</script>

<template>
  <div class="uploader">
    <input
      ref="fileInput"
      type="file"
      accept="image/*"
      class="uploader__input"
      @change="handleFileSelect"
    />
    
    <!-- 预览状态 -->
    <div v-if="preview" class="uploader__preview">
      <img :src="preview" alt="上传的图片" class="uploader__image" />
      <button class="uploader__remove" @click="removeImage" title="移除图片">
        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M18 6L6 18M6 6l12 12" stroke="currentColor" stroke-width="2" 
                stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
    </div>
    
    <!-- 上传区域 -->
    <div
      v-else
      class="uploader__dropzone"
      :class="{ 'uploader__dropzone--active': isDragging }"
      @click="triggerFileSelect"
      @dragover="handleDragOver"
      @dragleave="handleDragLeave"
      @drop="handleDrop"
    >
      <div class="uploader__icon">
        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14" 
                stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M14 8h.01" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
          <rect x="3" y="4" width="18" height="16" rx="2" stroke="currentColor" stroke-width="1.5"/>
        </svg>
      </div>
      <p class="uploader__text">
        <span class="uploader__text-primary">点击上传</span>
        <span class="uploader__text-secondary">或拖放图片到此处</span>
      </p>
      <p class="uploader__hint">支持 JPG、PNG、WEBP 格式</p>
    </div>
  </div>
</template>

<style scoped>
.uploader {
  width: 100%;
}

.uploader__input {
  display: none;
}

.uploader__dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--spacing-3xl) var(--spacing-xl);
  border: 2px dashed var(--color-gray-300);
  border-radius: var(--radius-xl);
  background: var(--bg-secondary);
  cursor: pointer;
  transition: all var(--transition-base);
}

.uploader__dropzone:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-subtle);
}

.uploader__dropzone--active {
  border-color: var(--color-primary);
  background: var(--color-primary-subtle);
  transform: scale(1.01);
}

.uploader__icon {
  width: 48px;
  height: 48px;
  color: var(--color-gray-400);
  margin-bottom: var(--spacing-md);
}

.uploader__icon svg {
  width: 100%;
  height: 100%;
}

.uploader__dropzone:hover .uploader__icon {
  color: var(--color-primary);
}

.uploader__text {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--spacing-xs);
  margin-bottom: var(--spacing-sm);
}

.uploader__text-primary {
  font-weight: 500;
  color: var(--color-primary);
}

.uploader__text-secondary {
  color: var(--text-secondary);
}

.uploader__hint {
  font-size: var(--font-size-sm);
  color: var(--text-tertiary);
}

.uploader__preview {
  position: relative;
  border-radius: var(--radius-xl);
  overflow: hidden;
  background: var(--bg-secondary);
}

.uploader__image {
  width: 100%;
  max-height: 400px;
  object-fit: contain;
}

.uploader__remove {
  position: absolute;
  top: var(--spacing-md);
  right: var(--spacing-md);
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.6);
  color: white;
  border-radius: var(--radius-full);
  transition: all var(--transition-fast);
}

.uploader__remove:hover {
  background: var(--color-primary);
  transform: scale(1.1);
}

.uploader__remove svg {
  width: 18px;
  height: 18px;
}
</style>
