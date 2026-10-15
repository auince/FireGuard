<script setup>
import { ref } from 'vue'
import { post, fileToBase64 } from '@/api'
import { authState } from '@/stores/auth'

const query = ref('')
const image = ref('')
const facility = ref('')
const project = ref(authState.user?.project_id || '')
const result = ref(null)
const error = ref('')
const busy = ref(false)
const uploading = ref(false)
let uploadVersion = 0

async function upload(event) {
  const version = ++uploadVersion
  const file = event.target.files?.[0]
  image.value = ''
  error.value = ''
  uploading.value = Boolean(file)
  if (!file) return
  try {
    const value = await fileToBase64(file)
    if (version === uploadVersion) image.value = value
  } catch (e) {
    if (version === uploadVersion) error.value = e.message
  } finally {
    if (version === uploadVersion) uploading.value = false
  }
}

async function search() {
  busy.value = true
  error.value = ''
  result.value = null
  try {
    result.value = await post('/cases/search', {
      query: query.value.trim(),
      image: image.value || null,
      project_id: project.value,
      facility: facility.value || null,
    })
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
        <h1>案例检索</h1>
        <p>通过文字或现场照片查找已审核案例，查看历史现场描述与整改记录。</p>
      </div>
    </header>
    <form class="card" @submit.prevent="search">
      <fieldset :disabled="busy" class="search-fields">
        <div class="form-row">
          <label class="field">
            <span>所属项目</span>
            <select v-model="project" class="input">
              <option v-for="item in authState.user?.projects || []" :key="item" :value="item">
                {{ item }}
              </option>
            </select>
          </label>
          <label class="field">
            <span>设施类别</span>
            <select v-model="facility" class="input">
              <option value="">全部设施</option>
              <option value="indoor_hydrant">室内消火栓</option>
              <option value="outdoor_hydrant">室外消火栓</option>
              <option value="fire_extinguisher">灭火器</option>
            </select>
          </label>
        </div>
        <label class="field">
          <span>现场描述</span>
          <textarea
            v-model="query"
            class="input"
            rows="3"
            maxlength="1000"
            placeholder="例如：箱门关闭，前方堆放杂物"
          />
        </label>
        <label class="field">
          <span>现场照片（可选）</span>
          <input type="file" accept="image/jpeg,image/png" @change="upload" />
        </label>
        <img v-if="image" :src="image" class="query-photo" alt="待检索现场照片" />
        <button
          class="btn btn-primary"
          :disabled="uploading || (!query.trim() && !image) || !project"
        >
          {{ busy ? '正在检索…' : '检索参考案例' }}
        </button>
      </fieldset>
    </form>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <p v-if="result?.warnings?.length" class="message" role="status">
      部分检索通道暂不可用，以下为其余通道返回的结果。
    </p>
    <template v-if="result">
      <p class="muted">
        找到
        {{ result.cases.length }}
        条参考记录。相似程度不代表隐患概率，历史结论需结合本次现场重新核查。
      </p>
      <p v-if="!result.cases.length" class="card">
        未找到符合权限、设施及审核条件的案例，请调整描述或补充案例库。
      </p>
      <div class="case-grid">
        <article v-for="item in result.cases" :key="item.id" class="card case-card">
          <img :src="item.image_url" alt="历史案例现场照片" loading="lazy" />
          <h2 class="subheading">案例 {{ item.id }}</h2>
          <span class="pill">{{ item.synthetic ? '仿真案例' : '历史案例' }}</span>
          <p class="case-description">{{ item.description }}</p>
          <p v-if="item.review_conclusion">
            <strong>历史审核结论：</strong>{{ item.review_conclusion }}
          </p>
          <p v-if="item.remediation"><strong>历史整改记录：</strong>{{ item.remediation }}</p>
          <small class="muted">{{
            item.review_status === 'approved' ? '审核已通过' : '沿用历史人工审核标记'
          }}</small>
        </article>
      </div>
    </template>
  </div>
</template>

<style scoped>
.search-fields {
  border: 0;
  padding: 0;
  display: grid;
  gap: 18px;
  min-width: 0;
}
.query-photo {
  max-width: 280px;
  max-height: 220px;
  object-fit: contain;
}
.case-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr));
  gap: 20px;
}
.case-card img {
  width: 100%;
  height: 220px;
  object-fit: contain;
  background: var(--bg-secondary);
  margin-bottom: 16px;
}
.case-description {
  white-space: pre-wrap;
  line-height: 1.8;
}
</style>
