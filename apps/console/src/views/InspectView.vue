<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ArrowRight, ShieldCheck } from 'lucide-vue-next'
import SceneFields from '@/components/SceneFields.vue'
import ImageUploader from '@/components/ImageUploader.vue'
import { request, post } from '@/api'
import { authState } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const image = ref(null)
const uploading = ref(false)
const busy = ref(false)
const error = ref('')
const original = ref(null)
const scene = ref({})

const localDate = new Date().toLocaleDateString('sv-SE')
const form = reactive({
  query: '',
  facility: 'auto',
  jurisdiction: '四川',
  as_of: localDate,
  retrieval_mode: 'rrf'
})

onMounted(async () => {
  if (route.query.revise) {
    try {
      const r = await request('/reports/' + encodeURIComponent(route.query.revise))
      original.value = r
      Object.assign(form, {
        query: r.query,
        facility: r.facility in { auto: 1, indoor_hydrant: 1, outdoor_hydrant: 1, fire_extinguisher: 1 } ? r.facility : 'auto',
        jurisdiction: r.jurisdiction,
        as_of: r.as_of,
        retrieval_mode: r.retrieval_mode || 'rrf'
      })
      image.value = r.image
      scene.value = r.scene || {}
    } catch (e) {
      error.value = e.message
    }
  } else if (route.query.session) {
    // Coming from sessions view with existing session context
    // Leave form empty for user to fill, session_id will be passed in submit
  }
})

async function submit() {
  if (busy.value || uploading.value) return
  error.value = ''
  busy.value = true
  try {
    const values = scene.value
    const input = {
      ...form,
      query: form.query.trim(),
      image: image.value,
      scene: values,
      project_id: authState.user.project_id,
      session_id: typeof route.query.session === 'string' ? route.query.session : null
    }
    if (!input.query) throw new Error('请填写巡检问题')

    const data = original.value
      ? await post('/reports/' + original.value.id + '/revise', { expected_revision: original.value.revision, input })
      : await post('/inspect', input)

    await router.push('/reports/' + data.id)
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="container feature-page">
    <header class="page-heading">
      <div>
        <h1>{{ original ? '补充巡检报告' : '提交巡检' }}</h1>
        <p>描述问题并上传设施照片，生成带法规依据的核查草稿。</p>
      </div>
      <span class="pill">01 · 现场输入</span>
    </header>

    <div class="split">
      <form class="card" @submit.prevent="submit">
        <label class="field">
          <span>巡检问题</span>
          <textarea
            v-model="form.query"
            class="input"
            rows="4"
            required
            maxlength="2000"
            placeholder="例如：消火栓前堆放了杂物，是否存在隐患？如何整改？"
          ></textarea>
        </label>

        <div class="form-row">
          <label class="field">
            <span>设施类型</span>
            <select v-model="form.facility" class="input">
              <option value="auto">自动识别</option>
              <option value="indoor_hydrant">室内消火栓</option>
              <option value="outdoor_hydrant">室外消火栓</option>
              <option value="fire_extinguisher">灭火器</option>
            </select>
          </label>
          <label class="field">
            <span>适用地域</span>
            <select v-model="form.jurisdiction" class="input">
              <option>四川</option>
              <option>全国</option>
            </select>
          </label>
        </div>

        <div class="form-row">
          <label class="field">
            <span>核查日期</span>
            <input v-model="form.as_of" class="input" type="date" required>
          </label>
          <label class="field">
            <span>检索方式</span>
            <select v-model="form.retrieval_mode" class="input">
              <option value="rrf">BM25 + 向量融合</option>
              <option value="bm25">关键词检索</option>
              <option value="dense">向量检索</option>
              <option value="rerank">混合检索 + 重排</option>
            </select>
          </label>
        </div>

        <details class="scene-details">
          <summary class="muted">补充已确认的现场条件</summary>
          <SceneFields v-model="scene"/>
        </details>

        <p v-if="error" class="message error" role="alert">{{ error }}</p>

        <div class="actions">
          <button class="btn btn-primary btn-lg" :disabled="busy || uploading">
            {{ busy ? '正在提交' : uploading ? '正在处理照片' : original ? '补充并重新生成' : '生成核查草稿' }}
            <ArrowRight :size="17" />
          </button>
        </div>
      </form>

      <div class="stack">
        <section class="card">
          <h2 class="subheading">设施照片</h2>
          <ImageUploader v-model="image" @processing="uploading = $event" />
          <p class="muted">照片可选；模糊、不可见或缺少测量信息会保留为待核查项。</p>
        </section>

        <section class="card reminder-card">
          <ShieldCheck :size="24" class="reminder-icon" />
          <h2 class="subheading">生成后，还需要人工复核</h2>
          <p class="muted">条款原文、引用标识和验证结果会展示在报告详情页。报告不会自动定稿。</p>
          <div class="actions">
            <router-link to="/history" class="btn btn-secondary">查看报告历史</router-link>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.scene-details {
  margin-top: 12px;
  padding: 12px;
  border: 1px solid var(--color-gray-200);
  border-radius: var(--radius-md);
  background: var(--bg-secondary);
}

.scene-details summary {
  font-weight: 600;
  user-select: none;
}

.scene-details[open] {
  padding-bottom: 16px;
}

.scene-details .field {
  margin-top: 12px;
  margin-bottom: 0;
}

.reminder-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.reminder-icon {
  color: var(--color-primary);
}
</style>
