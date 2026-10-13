<script setup>
import { ref, onMounted } from 'vue'
import { request, safeSource } from '@/api'

const documents = ref([])
const snapshot = ref('')
const current = ref(null)
const hits = ref(null)
const query = ref('')
const error = ref('')
const busy = ref(false)
const date = ref(new Date().toLocaleDateString('sv-SE'))
const region = ref('四川')
let selection = 0
let catalogVersion = 0

function parameters() {
  return new URLSearchParams({ as_of: date.value, jurisdiction: region.value }).toString()
}

async function catalog() {
  const epoch = ++catalogVersion
  busy.value = true
  error.value = ''
  current.value = null
  hits.value = null
  selection++
  documents.value = []
  snapshot.value = ''
  try {
    const data = await request('/knowledge/documents?' + parameters())
    if (epoch !== catalogVersion) return
    documents.value = data.documents
    snapshot.value = data.snapshot_id
  } catch (e) {
    if (epoch === catalogVersion) error.value = e.message
  } finally {
    if (epoch === catalogVersion) busy.value = false
  }
}

async function open(doc) {
  const epoch = ++selection
  error.value = ''
  hits.value = null
  current.value = null
  try {
    const data = await request('/knowledge/documents/' + encodeURIComponent(doc.doc_id) + '?' + parameters())
    if (epoch === selection) current.value = data
  } catch (e) {
    if (epoch === selection) error.value = e.message
  }
}

async function search() {
  if (!query.value.trim()) return
  const epoch = ++selection
  busy.value = true
  current.value = null
  error.value = ''
  try {
    const result = await request('/knowledge/search?' + parameters() + '&q=' + encodeURIComponent(query.value.trim()))
    if (epoch === selection) hits.value = result.evidence
  } catch (e) {
    if (epoch === selection) error.value = e.message
  } finally {
    if (epoch === selection) busy.value = false
  }
}

onMounted(catalog)
</script>

<template>
  <div class="container feature-page">
    <header class="page-heading">
      <div>
        <h1>法规库</h1>
        <p>浏览当前事实库的有效版本，查看完整原文和条款出处。</p>
      </div>
      <span class="pill">{{ documents.length }} 份适用文档</span>
    </header>

    <section class="card">
      <div class="form-row">
        <label class="field">
          <span>核查日期</span>
          <input v-model="date" type="date" class="input" @change="catalog">
        </label>
        <label class="field">
          <span>地域</span>
          <select v-model="region" class="input" @change="catalog">
            <option>四川</option>
            <option>全国</option>
          </select>
        </label>
      </div>

      <form class="search-row" @submit.prevent="search">
        <input
          v-model="query"
          class="input"
          aria-label="检索法规条款"
          placeholder="输入条款关键词，例如：消火栓 遮挡"
          maxlength="1000"
        >
        <button class="btn btn-primary" :disabled="busy || !query.trim()">检索条款</button>
      </form>

      <p class="muted">快照：{{ snapshot || '正在加载' }}</p>
    </section>

    <p v-if="error" class="message error" role="alert">{{ error }}</p>

    <div class="knowledge-layout">
      <aside class="card document-list">
        <h2 class="subheading">有效法规目录</h2>
        <div class="document-list-scroll">
          <button
            v-for="doc in documents"
            :key="doc.doc_id"
            class="document-button"
            :disabled="busy"
            @click="open(doc)"
          >
            <strong>{{ doc.title }}</strong>
            <span>{{ doc.jurisdiction }} · {{ doc.effective_from || '未标注生效日期' }}</span>
          </button>
        </div>
        <p v-if="!busy && !documents.length" class="muted">当前条件下没有适用文档。</p>
      </aside>

      <section class="card content-area">
        <template v-if="current">
          <h2 class="subheading">{{ current.title }}</h2>
          <p class="muted">版本：{{ current.version_id }}</p>
          <a
            v-if="safeSource(current.url)"
            :href="safeSource(current.url)"
            target="_blank"
            rel="noopener noreferrer"
            class="citation"
          >
            查看原始来源 ↗
          </a>
          <pre class="legal-body">{{ current.full_text }}</pre>
        </template>

        <template v-else-if="hits">
          <h2 class="subheading">条款检索结果 · {{ hits.length }} 条</h2>
          <article v-for="(hit, i) in hits" :key="hit.evidence_id" class="evidence-card">
            <h3>{{ i + 1 }}. {{ hit.document_title }}</h3>
            <blockquote>{{ hit.text }}</blockquote>
            <a
              v-if="safeSource(hit.source_url)"
              :href="safeSource(hit.source_url)"
              target="_blank"
              rel="noopener noreferrer"
            >
              查看来源 ↗
            </a>
          </article>
          <p v-if="!hits.length" class="empty">没有召回相关条款，请尝试其他关键词。</p>
        </template>

        <div v-else class="empty">选择左侧文档查看原文，或检索相关条款。</div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.knowledge-layout {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: 24px;
  margin-top: 24px;
}

.document-list {
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 300px);
}

.document-list-scroll {
  flex: 1;
  overflow-y: auto;
  margin-top: 12px;
}

.document-button {
  display: block;
  width: 100%;
  text-align: left;
  padding: 16px 0;
  border-bottom: 1px solid var(--color-gray-200);
  transition: background var(--transition-fast);
}

.document-button:hover {
  background: var(--bg-secondary);
}

.document-button strong {
  font-size: 13px;
  display: block;
}

.document-button span {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 4px;
  display: block;
}

.content-area {
  min-height: 400px;
}

.legal-body {
  font-family: inherit;
  font-size: 14px;
  line-height: 1.9;
  margin-top: 20px;
  max-height: 70vh;
  overflow: auto;
  padding: 12px;
  background: var(--bg-secondary);
  border-radius: var(--radius-md);
}

@media (max-width: 900px) {
  .knowledge-layout {
    grid-template-columns: 1fr;
  }

  .document-list {
    max-height: 400px;
  }
}
</style>
