<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MessageSquarePlus, ArrowUpRight } from 'lucide-vue-next'
import { request, post, statusLabel } from '@/api'
import { authState } from '@/stores/auth'
import ImageUploader from '@/components/ImageUploader.vue'

const route = useRoute(), router = useRouter()
const sessions = ref([]), turns = ref([]), selected = ref(''), question = ref(''), image = ref(null)
const error = ref(''), loading = ref(false), busy = ref(false), uploading = ref(false)
let generation = 0, timer, pollGeneration = 0

async function list() {
  sessions.value = (await request('/sessions')).sessions
}

async function load(id, epoch) {
  try {
    const data = await request('/sessions/' + encodeURIComponent(id))
    if (epoch !== generation) return
    turns.value = data.turns
    if (data.turns.some(t => ['queued', 'running'].includes(t.status))) {
      timer = setTimeout(() => load(id, epoch), 1200)
    }
  } catch (e) {
    if (epoch === generation) error.value = e.message
  } finally {
    if (epoch === generation) loading.value = false
  }
}

function choose(id) {
  clearTimeout(timer)
  generation++
  pollGeneration++
  busy.value = false
  uploading.value = false
  selected.value = id || ''
  turns.value = []
  question.value = ''
  image.value = null
  error.value = ''
  loading.value = !!id
  if (id) load(id, generation)
}

async function select(id) {
  if (id === selected.value) { choose(id); return }
  await router.replace({ path: '/sessions', query: id ? { id } : {} })
}

async function send() {
  if (busy.value || loading.value || uploading.value || !question.value.trim()) return
  const hasRunning = turns.value.some(t => ['queued', 'running'].includes(t.status))
  if (hasRunning) {
    error.value = '请等待上一轮完成后再发送'
    return
  }
  const epoch = generation, pollEpoch = ++pollGeneration
  busy.value = true
  error.value = ''
  try {
    const result = await post('/inspect', {
      query: question.value.trim(),
      image: image.value,
      session_id: selected.value || null,
      project_id: authState.user.project_id
    })
    if (epoch !== generation || pollEpoch !== pollGeneration) return
    question.value = ''
    image.value = null
    await list()
    if (epoch !== generation || pollEpoch !== pollGeneration) return
    if (selected.value !== result.session_id) {
      await select(result.session_id)
    } else {
      clearTimeout(timer)
      load(selected.value, ++generation)
    }
  } catch (e) {
    if (epoch === generation && pollEpoch === pollGeneration) {
      error.value = e.message
    }
  } finally {
    if (pollEpoch === pollGeneration) {
      busy.value = false
    }
  }
}

watch(() => route.query.id, id => choose(typeof id === 'string' ? id : ''))
onMounted(async () => {
  try {
    await list()
    choose(typeof route.query.id === 'string' ? route.query.id : '')
  } catch (e) {
    error.value = e.message
  }
})
onBeforeUnmount(() => {
  generation++
  pollGeneration++
  clearTimeout(timer)
})
</script>

<template>
  <div class="container feature-page">
    <header class="page-heading">
      <div>
        <p class="kicker">CONVERSATIONS</p>
        <h1>多轮巡检</h1>
        <p>围绕同一次巡检继续追问，每轮结论都保留独立报告与审核状态。</p>
      </div>
      <button class="btn btn-secondary" :disabled="busy" @click="select('')">
        <MessageSquarePlus :size="17"/>新建会话
      </button>
    </header>

    <p v-if="error" class="message error" role="alert">{{ error }}</p>

    <div class="conversation-layout">
      <aside class="card session-list">
        <h2 class="subheading">我的会话</h2>
        <p v-if="!sessions.length" class="muted">提交第一个问题后，会话会保存在这里。</p>
        <button
          v-for="s in sessions"
          :key="s.id"
          class="session-item"
          :class="{selected:selected===s.id}"
          :disabled="busy"
          @click="select(s.id)"
        >
          <strong>{{ s.title || '巡检会话 ' + s.id.slice(0, 8) }}</strong>
          <small>{{ new Date(s.updated * 1000).toLocaleString('zh-CN') }}</small>
        </button>
      </aside>

      <div class="stack">
        <section class="card conversation-turns" aria-live="polite">
          <p v-if="loading" class="muted">正在读取会话…</p>
          <div v-else-if="!turns.length" class="empty">
            <MessageSquarePlus :size="30"/>
            <h2>从一个现场问题开始</h2>
            <p>可以追问"这个如何整改"，也可以上传新照片开始核查另一处设施。</p>
          </div>
          <article v-for="(turn, i) in turns" :key="turn.id" class="conversation-turn">
            <p class="kicker">第 {{ i + 1 }} 轮 · {{ statusLabel(turn.status) }}</p>
            <h3>{{ turn.query }}</h3>

            <p v-if="turn.model?.includes('fixture')" class="muted">仿真响应 · 用于流程演示</p>
            <p v-if="['queued','running'].includes(turn.status)" class="message">正在检索法规并生成草稿…</p>
            <p v-else-if="turn.error" class="message error">{{ turn.error }}</p>
            <div v-for="(hazard, j) in turn.answer?.hazards || []" :key="j" class="turn-answer">
              <p>{{ hazard.description }}</p>
              <p class="muted">{{ hazard.suggestion }}</p>
            </div>
            <p v-for="item in turn.answer?.missing_information || []" :key="item" class="muted">待补充：{{ item }}</p>
            <router-link :to="'/reports/' + turn.id" class="citation">
              查看完整报告与引用 <ArrowUpRight :size="14"/>
            </router-link>
          </article>
        </section>

        <form class="card" @submit.prevent="send">
          <label class="field">
            <span>{{ selected ? '继续追问' : '首轮巡检问题' }}</span>
            <textarea
              v-model="question"
              class="input"
              rows="3"
              required
              maxlength="2000"
              placeholder="例如：这个消火栓需要如何整改？"
              :disabled="busy || uploading"
            ></textarea>
          </label>

          <details class="session-photo">
            <summary>添加本轮照片（可选）</summary>
            <ImageUploader :key="selected" v-model="image" @processing="uploading=$event"/>
          </details>

          <p class="muted">新照片会清空旧现场上下文。测量值和条件请在"巡检提交"中单独填写。</p>

          <div class="actions">
            <button
              class="btn btn-primary"
              :disabled="busy || loading || uploading || turns.some(t=>['queued','running'].includes(t.status))"
            >
              {{ busy ? '正在提交…' : uploading ? '正在处理照片…' : '发送并生成草稿' }}
            </button>
            <router-link
              v-if="selected"
              :to="{path:'/inspect',query:{session:selected}}"
              class="btn btn-secondary"
            >
              补充详细现场条件
            </router-link>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<style scoped>
.conversation-layout{display:grid;grid-template-columns:270px minmax(0,1fr);gap:24px;align-items:start}
.session-list{position:sticky;top:92px;max-height:75vh;overflow:auto}
.session-item{display:grid;gap:8px;width:100%;text-align:left;padding:16px 12px;border-bottom:1px solid var(--color-gray-200);border-radius:6px;transition:background var(--transition-fast)}
.session-item:hover{background:var(--color-gray-50)}
.session-item strong{font-size:13px;overflow-wrap:anywhere}
.session-item small{color:var(--text-tertiary);font-size:11px}
.session-item.selected{background:var(--color-primary-subtle);color:var(--color-primary-dark)}
.conversation-turns{min-height:200px}
.conversation-turn{padding:24px 0;border-bottom:1px solid var(--color-gray-200)}
.conversation-turn:first-child{padding-top:0}
.conversation-turn:last-child{border:0;padding-bottom:0}
.conversation-turn h3{font-size:17px;line-height:1.7;margin-bottom:14px}
.turn-image-container{margin:14px 0}
.turn-photo{max-width:100%;height:auto;border-radius:var(--radius-md);border:1px solid var(--color-gray-200)}
.turn-answer{padding:14px 18px;background:var(--bg-secondary);border-radius:8px;margin-bottom:14px}
.turn-answer p+p{margin-top:8px}
.session-photo{margin:14px 0}
.session-photo summary{cursor:pointer;color:var(--text-secondary);margin-bottom:14px}
.empty{text-align:center;padding:48px 24px}
.empty h2{font-size:21px;margin:16px 0}
@media(max-width:800px){.conversation-layout{grid-template-columns:1fr}.session-list{position:static;max-height:240px}}
</style>
