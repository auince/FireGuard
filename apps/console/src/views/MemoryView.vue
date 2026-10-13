<script setup>
import { ref, onMounted } from 'vue'
import { request, post } from '@/api'
import { Layers, Check } from 'lucide-vue-next'

const data = ref(null)
const style = ref('concise')
const consent = ref(false)
const busy = ref(false)
const message = ref('')
const error = ref('')

async function load() {
  data.value = await request('/memory')
  style.value = data.value.preferences.answer_style || 'concise'
}

async function save() {
  if (!consent.value) {
    error.value = '请勾选同意后再保存偏好'
    return
  }
  busy.value = true
  error.value = ''
  message.value = ''
  try {
    await post('/memory/preferences', { answer_style: style.value, consent: consent.value })
    await load()
    consent.value = false
    message.value = '回答偏好已保存，将用于下一轮生成。'
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

async function forget() {
  if (!data.value.preferences.answer_style) {
    error.value = '当前没有已保存的偏好'
    return
  }
  busy.value = true
  error.value = ''
  message.value = ''
  try {
    await request('/memory/preferences', { method: 'DELETE' })
    await load()
    consent.value = false
    message.value = '已清除长期偏好，巡检记录继续保留。'
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  try {
    await load()
  } catch (e) {
    error.value = e.message
  }
})
</script>

<template>
  <div class="container feature-page">
    <header class="page-heading">
      <div>
        <h1>记忆管理</h1>
        <p>查看系统会记住什么，并自行管理长期回答偏好。</p>
      </div>
      <span class="pill">仅当前账号可见</span>
    </header>

    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <p v-if="message" role="status" class="message success">{{ message }}</p>

    <div v-if="data" class="split">
      <section class="card">
        <h2 class="subheading"><Layers :size="20" /> 记忆与知识的边界</h2>
        <article v-for="(layer, i) in data.layers" :key="layer.name" class="memory-layer">
          <span class="layer-number">0{{ i + 1 }}</span>
          <div>
            <h3>{{ layer.name }}</h3>
            <p class="muted">{{ layer.description }}</p>
          </div>
        </article>
        <p class="message">
          历史对话和个人偏好不会作为官方条款引用。每次生成都会重新检索有效法规。
        </p>
      </section>

      <div class="stack">
        <form class="card" @submit.prevent="save">
          <h2 class="subheading">回答偏好</h2>
          <p class="muted">
            {{
              data.preferences.answer_style
                ? '当前已保存：' + (data.preferences.answer_style === 'concise' ? '简洁' : '详细')
                : '尚未保存长期偏好。'
            }}
          </p>

          <label class="field">
            <span>希望建议多详细？</span>
            <select v-model="style" class="input" :disabled="busy">
              <option value="concise">简洁，突出隐患与整改要点</option>
              <option value="detailed">详细，补充依据与核查步骤</option>
            </select>
          </label>

          <label class="consent">
            <input v-model="consent" type="checkbox" :disabled="busy" />
            我同意保存此偏好，用于后续巡检回答。
          </label>

          <div class="actions">
            <button class="btn btn-primary" :disabled="busy || !consent">
              <Check :size="16" />
              {{ busy ? '保存中…' : '保存偏好' }}
            </button>
            <button
              type="button"
              class="btn btn-secondary"
              :disabled="busy || !data.preferences.answer_style"
              @click="forget"
            >
              {{ busy ? '清除中…' : '清除已保存偏好' }}
            </button>
          </div>
        </form>

        <section class="card">
          <h2 class="subheading">上下文使用范围</h2>
          <p class="muted">
            会话工作记忆保留 {{ data.working_ttl_minutes || 30 }} 分钟，注入内容按
            {{ data.context_budget_bytes }} 字节预算裁剪。上传新照片时，不继承旧照片或测量值。
          </p>
          <div class="actions">
            <router-link to="/sessions" class="btn btn-outline">查看我的会话</router-link>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.memory-layer {
  display: flex;
  gap: 18px;
  padding: 22px 0;
  border-bottom: 1px solid var(--color-gray-200);
}
.memory-layer:last-of-type {
  border-bottom: 0;
}
.memory-layer h3 {
  font-size: 16px;
  margin-bottom: 6px;
}
.layer-number {
  color: var(--color-primary);
  font-size: 12px;
  font-weight: 700;
  padding-top: 4px;
  flex: 0 0 auto;
}
.consent {
  display: flex;
  gap: 10px;
  align-items: start;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-secondary);
  margin: 16px 0;
}
.consent input {
  margin-top: 5px;
  accent-color: var(--color-primary);
  cursor: pointer;
}
.consent input:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}
.subheading {
  display: flex;
  gap: 8px;
  align-items: center;
}
</style>
