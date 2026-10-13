<script setup>
import {ref,watch,onBeforeUnmount} from 'vue'
import {fileToBase64} from '@/api'
const props=defineProps({modelValue:{type:String,default:null}}),emit=defineEmits(['update:modelValue','processing'])
const preview=ref(props.modelValue),fileInput=ref(null),isDragging=ref(false),error=ref(''),busy=ref(false);let generation=0
watch(()=>props.modelValue,value=>preview.value=value)
onBeforeUnmount(()=>generation++)
async function processFile(file){if(!file)return;const current=++generation;busy.value=true;emit('processing',true);error.value='';emit('update:modelValue',null);preview.value=null;try{const data=await fileToBase64(file);if(current!==generation)return;preview.value=data;emit('update:modelValue',data)}catch(e){if(current===generation)error.value=e.message}finally{if(current===generation){busy.value=false;emit('processing',false)}}}
function removeImage(){generation++;preview.value=null;busy.value=false;if(fileInput.value)fileInput.value.value='';emit('update:modelValue',null);emit('processing',false)}
function handleDrop(e){e.preventDefault();isDragging.value=false;processFile(e.dataTransfer.files[0])}
</script>
<template><div class="uploader"><input ref="fileInput" type="file" accept="image/jpeg,image/png" class="uploader__input" aria-label="选择设施照片" @change="processFile($event.target.files[0])"><div v-if="preview" class="uploader__preview"><img :src="preview" alt="本次上传的设施照片" class="uploader__image"><button class="uploader__remove" type="button" aria-label="移除照片" @click="removeImage">×</button></div><button v-else type="button" class="uploader__dropzone" :class="{'uploader__dropzone--active':isDragging}" :disabled="busy" @click="fileInput?.click()" @dragover.prevent="isDragging=true" @dragleave="isDragging=false" @drop="handleDrop"><div class="uploader__icon"><svg viewBox="0 0 24 24" fill="none"><path d="M4 16l5-5 7 7m-2-2 3-3 3 3" stroke="currentColor" stroke-width="1.5"/><rect x="3" y="4" width="18" height="16" rx="2" stroke="currentColor" stroke-width="1.5"/></svg></div><p class="uploader__text"><span class="uploader__text-primary">{{busy?'正在处理照片':'点击上传'}}</span><span v-if="!busy" class="uploader__text-secondary">或拖放图片到此处</span></p><p class="uploader__hint">JPEG / PNG · ≤10MiB · ≤1600万像素</p></button><p v-if="error" class="message error" role="alert">{{error}}</p></div></template>

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
