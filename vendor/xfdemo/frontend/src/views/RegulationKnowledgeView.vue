<script setup>
import { computed, ref } from 'vue'
import { BookOpen, ClipboardCheck, FileText, Filter, Link2, Search, ShieldCheck } from 'lucide-vue-next'

const query = ref('')
const activeScope = ref('all')
const activeRisk = ref('all')
const selectedClauseId = ref('gb50974-12-3-9')

const scopes = [
  { id: 'all', label: '全部' },
  { id: 'appearance', label: '箱体外观' },
  { id: 'internal', label: '内部组件' },
  { id: 'operation', label: '维护管理' }
]

const risks = [
  { id: 'all', label: '全部风险' },
  { id: 'missing', label: '组件缺失' },
  { id: 'marking', label: '标识问题' },
  { id: 'blocked', label: '遮挡占用' },
  { id: 'direction', label: '安装方向' },
  { id: 'damage', label: '损坏变形' }
]

const sourceDocs = [
  {
    title: '中华人民共和国消防法',
    file: '中华人民共和国消防法.doc',
    role: '上位法依据',
    summary: '用于确认单位消防安全职责、消防设施器材配置维护、损坏挪用或遮挡消防设施等违法事实的上位法依据。',
    keyPoints: ['第十六条：配置消防设施、器材和消防安全标志，并定期检验维修，确保完好有效', '第二十八条：不得损坏、挪用、擅自拆除停用消防设施器材，不得埋压、圈占、遮挡消火栓']
  },
  {
    title: '高层民用建筑消防安全管理规定',
    file: '《高层民用建筑消防安全管理规定》.doc',
    role: '高层建筑专项规定',
    summary: '用于高层民用建筑场景下的消火栓箱、消防设施维护、标识、遮挡和日常巡查判断。',
    keyPoints: ['禁止圈占、遮挡消火栓，禁止在消火栓箱内堆放杂物', '消火栓箱、灭火器箱上应当张贴使用方法标识', '存在故障、缺损的，应当立即组织维修、更换，确保完好有效']
  },
  {
    title: '四川省消防行政处罚裁量规则（2023年）',
    file: '关于印发《四川省消防行政处罚裁量.doc',
    role: '四川处罚裁量参考',
    summary: '用于四川地区行政处罚裁量、轻微不罚、首违可不罚和设施器材缺失故障数量等分级参考。',
    keyPoints: ['消防设施、器材或者消防安全标志配置设置不符合标准，或者未保持完好有效', 'B类设施器材包括消火栓箱、消防水带水枪、消防软管卷盘、灭火器等', '该规则不得单独或者直接作为行政处罚决定的援引依据']
  }
]

const clauses = [
  {
    id: 'fire-law-16',
    source: '中华人民共和国消防法',
    article: '第十六条',
    title: '消防设施器材配置维护义务',
    scope: 'internal',
    risk: 'missing',
    status: '真实法规源',
    summary: '机关、团体、企业、事业等单位应按国家标准、行业标准配置消防设施、器材，设置消防安全标志，并定期组织检验、维修，确保完好有效。',
    checks: ['消防水带、水枪、接口、手轮等器材是否在位', '消防设施是否完好有效', '消防安全标志是否配置并可识别'],
    evidence: ['箱内全景', '组件局部框', 'YOLO 内部组件候选框', '人工标注标签'],
    mapping: ['室内消火栓无消防水带', '室内消火栓无消防水枪', '室内消火栓消防接口缺失', '室内消火栓手轮缺失']
  },
  {
    id: 'fire-law-28',
    source: '中华人民共和国消防法',
    article: '第二十八条',
    title: '不得损坏、停用、遮挡消防设施',
    scope: 'appearance',
    risk: 'blocked',
    status: '真实法规源',
    summary: '任何单位、个人不得损坏、挪用、擅自拆除或停用消防设施、器材，不得埋压、圈占、遮挡消火栓。',
    checks: ['箱门或消火栓是否被遮挡', '消防设施是否被占用或停用', '外部通道是否影响取用'],
    evidence: ['外观全景', '遮挡区域', '外观 YOLO 框', '巡检说明'],
    mapping: ['室内消火栓箱体或箱门被物品遮挡']
  },
  {
    id: 'high-rise-hydrant-box',
    source: '高层民用建筑消防安全管理规定',
    article: '消火栓箱管理相关条款',
    title: '消火栓箱遮挡、杂物和使用标识',
    scope: 'appearance',
    risk: 'marking',
    status: '真实法规源',
    summary: '高层民用建筑场景下，禁止圈占、遮挡消火栓，禁止在消火栓箱内堆放杂物；消火栓箱、灭火器箱上应张贴使用方法标识。',
    checks: ['箱门标识是否清晰', '操作说明或使用方法标识是否存在', '箱内是否堆放杂物', '箱门是否被遮挡'],
    evidence: ['外观 YOLO 框', 'OCR 区域', '箱门正面图', '历史相似样例'],
    mapping: ['未标注“消火栓”和英文“FIRE HYDRANT”字样', '明显部位未标注操作说明', '室内消火栓箱体无铭牌']
  },
  {
    id: 'high-rise-maintenance',
    source: '高层民用建筑消防安全管理规定',
    article: '维护保养相关条款',
    title: '消防设施故障缺损应及时维修更换',
    scope: 'internal',
    risk: 'damage',
    status: '真实法规源',
    summary: '对建筑消防设施应维护保养和检测；存在故障、缺损的，应立即组织维修、更换，确保完好有效。',
    checks: ['红色供水软管是否明显锐角折弯', '接口、阀门、手轮是否损坏或缺损', '是否影响消防设施主要功能'],
    evidence: ['红色软管局部图', '卷盘出口位置', '折痕区域', '复核模型说明'],
    mapping: ['消防软管卷盘供水管道折弯严重', '消防接口损坏', '手轮损坏']
  },
  {
    id: 'sichuan-penalty-equipment',
    source: '四川省消防行政处罚裁量规则（2023年）',
    article: '消防行政处罚裁量基准',
    title: '设施器材未保持完好有效的裁量参考',
    scope: 'internal',
    risk: 'missing',
    status: '四川裁量参考',
    summary: '裁量基准将消火栓箱、消防水带水枪、消防软管卷盘、灭火器等列为 B 类设施器材；可用于缺失、故障、设置不符合标准的数量和情节分级参考，但不得单独作为处罚决定援引依据。',
    checks: ['缺失数、故障数、设置不符合标准数', '是否及时整改', '是否属于轻微不罚或首违可不罚情形'],
    evidence: ['检测记录', '隐患标签', '人工复核结论', '整改记录'],
    mapping: ['室内消火栓无消防水带', '室内消火栓无消防水枪', '消防软管卷盘缺失', '灭火器缺失']
  }
]


const filteredClauses = computed(() => {
  const text = query.value.trim().toLowerCase()
  return clauses.filter((clause) => {
    const inScope = activeScope.value === 'all' || clause.scope === activeScope.value
    const inRisk = activeRisk.value === 'all' || clause.risk === activeRisk.value
    const searchable = [clause.title, clause.source, clause.summary, ...clause.checks, ...clause.mapping].join(' ').toLowerCase()
    return inScope && inRisk && (!text || searchable.includes(text))
  })
})

const selectedClause = computed(() => clauses.find((item) => item.id === selectedClauseId.value) || filteredClauses.value[0] || clauses[0])

const stats = computed(() => [
  { label: '法规文件', value: sourceDocs.length, hint: '已接入真实文件' },
  { label: '规则条目', value: clauses.length, hint: '条款 + 裁量参考' },
  { label: '标签映射', value: clauses.reduce((sum, item) => sum + item.mapping.length, 0), hint: '对齐检测隐患' }
])
</script>

<template>
  <div class="regulation-page">
    <div class="regulation-shell">
      <header class="regulation-hero">
        <div class="regulation-hero__copy">
          <p class="regulation-hero__eyebrow">REGULATION KNOWLEDGE</p>
          <h1>法规知识库</h1>
          <p>把条文、业务规则、隐患标签和视觉证据组织成可追溯的判断依据，后续可直接支撑检测报告解释。</p>
        </div>
        <div class="regulation-hero__badge">
          <ShieldCheck :size="18" />
          <span>本地原型 · 未部署公网</span>
        </div>
      </header>

      <section class="source-doc-strip">
        <article v-for="doc in sourceDocs" :key="doc.file">
          <div>
            <span>{{ doc.role }}</span>
            <strong>{{ doc.title }}</strong>
            <small>{{ doc.file }}</small>
          </div>
          <p>{{ doc.summary }}</p>
          <ul>
            <li v-for="point in doc.keyPoints" :key="point">{{ point }}</li>
          </ul>
        </article>
      </section>

      <section class="source-doc-strip">
        <article v-for="doc in sourceDocs" :key="doc.file">
          <div>
            <span>{{ doc.role }}</span>
            <strong>{{ doc.title }}</strong>
            <small>{{ doc.file }}</small>
          </div>
          <p>{{ doc.summary }}</p>
          <ul>
            <li v-for="point in doc.keyPoints" :key="point">{{ point }}</li>
          </ul>
        </article>
      </section>

      <section class="stat-strip">
        <article v-for="item in stats" :key="item.label">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
          <small>{{ item.hint }}</small>
        </article>
      </section>

      <section class="knowledge-workbench">
        <aside class="filter-panel">
          <div class="panel-heading"><Filter :size="17" />筛选条件</div>
          <label class="field-label">关键词</label>
          <div class="search-box">
            <Search :size="17" />
            <input v-model="query" placeholder="搜索条文、标签、检查项" />
          </div>

          <label class="field-label">检查范围</label>
          <div class="button-grid">
            <button v-for="item in scopes" :key="item.id" :class="{ active: activeScope === item.id }" @click="activeScope = item.id">{{ item.label }}</button>
          </div>

          <label class="field-label">风险类型</label>
          <div class="chip-list">
            <button v-for="item in risks" :key="item.id" :class="{ active: activeRisk === item.id }" @click="activeRisk = item.id">{{ item.label }}</button>
          </div>
        </aside>

        <main class="clause-panel">
          <div class="panel-heading"><BookOpen :size="17" />规则列表</div>
          <button v-for="clause in filteredClauses" :key="clause.id" class="clause-card" :class="{ active: selectedClause?.id === clause.id }" @click="selectedClauseId = clause.id">
            <div>
              <span>{{ clause.source }} · {{ clause.article }}</span>
              <strong>{{ clause.title }}</strong>
            </div>
            <p>{{ clause.summary }}</p>
          </button>
          <div v-if="!filteredClauses.length" class="empty-state">没有匹配的规则</div>
        </main>

        <aside class="detail-panel">
          <div class="panel-heading"><FileText :size="17" />规则详情</div>
          <div class="detail-head">
            <span>{{ selectedClause.source }} · {{ selectedClause.article }}</span>
            <h2>{{ selectedClause.title }}</h2>
            <small>{{ selectedClause.status }}</small>
          </div>

          <section class="detail-block">
            <h3><ClipboardCheck :size="15" />检查项</h3>
            <ul>
              <li v-for="item in selectedClause.checks" :key="item">{{ item }}</li>
            </ul>
          </section>

          <section class="detail-block">
            <h3><Link2 :size="15" />隐患标签映射</h3>
            <div class="tag-cloud tag-cloud--danger">
              <span v-for="item in selectedClause.mapping" :key="item">{{ item }}</span>
            </div>
          </section>

          <section class="detail-block">
            <h3>证据来源</h3>
            <div class="tag-cloud">
              <span v-for="item in selectedClause.evidence" :key="item">{{ item }}</span>
            </div>
          </section>
        </aside>
      </section>
    </div>
  </div>
</template>

<style scoped>
.regulation-page {
  min-height: 100vh;
  padding: 96px 0 40px;
  background: var(--bg-secondary);
  color: var(--text-primary);
}

.regulation-shell {
  width: min(1320px, calc(100% - 2rem));
  margin: 0 auto;
}

.regulation-hero {
  display: flex;
  justify-content: space-between;
  gap: var(--spacing-xl);
  padding: 30px;
  border: 1px solid var(--color-gray-200);
  border-radius: var(--radius-xl);
  background: var(--bg-primary);
  box-shadow: var(--shadow-sm);
}

.regulation-hero__eyebrow {
  color: var(--color-primary);
  font-size: var(--font-size-sm);
  font-weight: 700;
  letter-spacing: .08em;
}

.regulation-hero h1 {
  margin: var(--spacing-sm) 0 var(--spacing-md);
  font-size: clamp(2rem, 3vw, 2.65rem);
  line-height: 1.15;
  letter-spacing: 0;
}

.regulation-hero p {
  max-width: 760px;
  color: var(--text-secondary);
  font-size: var(--font-size-base);
  line-height: 1.75;
}

.regulation-hero__badge {
  align-self: flex-start;
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-sm);
  padding: var(--spacing-sm) var(--spacing-md);
  border-radius: var(--radius-full);
  background: var(--color-primary-subtle);
  color: var(--color-primary-dark);
  font-weight: 700;
  white-space: nowrap;
}

.source-doc-strip {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--spacing-md);
  margin: var(--spacing-md) 0;
}

.source-doc-strip article {
  display: grid;
  gap: var(--spacing-sm);
  padding: var(--spacing-lg);
  border: 1px solid var(--color-gray-200);
  border-radius: var(--radius-lg);
  background: var(--bg-primary);
  box-shadow: var(--shadow-sm);
}

.source-doc-strip span {
  color: var(--color-primary);
  font-size: var(--font-size-sm);
  font-weight: 700;
}

.source-doc-strip strong {
  display: block;
  margin-top: var(--spacing-xs);
  font-size: var(--font-size-lg);
}

.source-doc-strip small,
.source-doc-strip p,
.source-doc-strip li {
  color: var(--text-secondary);
  line-height: 1.7;
}

.source-doc-strip ul {
  padding-left: 1.1rem;
}

.source-doc-strip {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--spacing-md);
  margin: var(--spacing-md) 0;
}

.source-doc-strip article {
  display: grid;
  gap: var(--spacing-sm);
  padding: var(--spacing-lg);
  border: 1px solid var(--color-gray-100);
  border-radius: var(--radius-xl);
  background: var(--bg-primary);
  box-shadow: var(--shadow-sm);
}

.source-doc-strip span {
  color: var(--color-primary);
  font-size: var(--font-size-sm);
  font-weight: 700;
}

.source-doc-strip strong {
  display: block;
  margin-top: var(--spacing-xs);
  font-size: var(--font-size-lg);
}

.source-doc-strip small,
.source-doc-strip p,
.source-doc-strip li {
  color: var(--text-secondary);
  line-height: 1.7;
}

.source-doc-strip ul {
  padding-left: 1.1rem;
}

.stat-strip {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--spacing-md);
  margin: var(--spacing-md) 0;
}

.stat-strip article {
  padding: var(--spacing-lg);
  border: 1px solid var(--color-gray-200);
  border-radius: var(--radius-xl);
  background: var(--bg-primary);
  box-shadow: var(--shadow-sm);
}

.stat-strip span,
.stat-strip small {
  display: block;
  color: var(--text-secondary);
  font-weight: 600;
}

.stat-strip strong {
  display: block;
  margin: var(--spacing-xs) 0;
  font-size: var(--font-size-3xl);
  line-height: 1.1;
}

.knowledge-workbench {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr) 380px;
  gap: var(--spacing-md);
  align-items: start;
}

.filter-panel,
.clause-panel,
.detail-panel {
  padding: var(--spacing-lg);
  border: 1px solid var(--color-gray-200);
  border-radius: var(--radius-xl);
  background: var(--bg-primary);
  box-shadow: var(--shadow-sm);
}

.panel-heading {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  margin-bottom: var(--spacing-md);
  color: var(--text-primary);
  font-weight: 700;
}

.field-label {
  display: block;
  margin: var(--spacing-lg) 0 var(--spacing-sm);
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
  font-weight: 600;
}

.search-box {
  display: flex;
  align-items: center;
  gap: var(--spacing-sm);
  padding: var(--spacing-sm) var(--spacing-md);
  border: 1px solid var(--color-gray-200);
  border-radius: var(--radius-md);
  background: var(--bg-primary);
}

.search-box:focus-within {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-subtle);
}

.search-box input {
  width: 100%;
  border: 0;
  outline: 0;
  background: transparent;
}

.button-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--spacing-sm);
}

.button-grid button,
.chip-list button {
  border: 1px solid var(--color-gray-200);
  border-radius: var(--radius-full);
  padding: var(--spacing-sm) var(--spacing-md);
  background: var(--bg-primary);
  color: var(--text-secondary);
  font-weight: 600;
}

.button-grid button.active,
.chip-list button.active {
  border-color: var(--color-primary);
  background: var(--color-primary);
  color: var(--text-inverse);
}

.chip-list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-sm);
}

.clause-panel {
  display: grid;
  gap: var(--spacing-sm);
}

.clause-card {
  width: 100%;
  text-align: left;
  padding: var(--spacing-md);
  border: 1px solid var(--color-gray-100);
  border-radius: var(--radius-lg);
  background: var(--bg-primary);
  transition: all var(--transition-fast);
}

.clause-card:hover,
.clause-card.active {
  border-color: var(--color-primary);
  background: var(--color-primary-subtle);
}

.clause-card div {
  display: flex;
  justify-content: space-between;
  gap: var(--spacing-md);
  margin-bottom: var(--spacing-sm);
}

.clause-card span {
  color: var(--color-primary);
  font-size: var(--font-size-sm);
  font-weight: 700;
}

.clause-card strong {
  color: var(--text-primary);
  font-size: var(--font-size-base);
}

.clause-card p,
.detail-block li {
  color: var(--text-secondary);
  line-height: 1.75;
}

.empty-state {
  padding: var(--spacing-xl);
  color: var(--text-secondary);
  text-align: center;
  background: var(--bg-secondary);
  border-radius: var(--radius-lg);
}

.detail-head {
  padding-bottom: var(--spacing-md);
  border-bottom: 1px solid var(--color-gray-100);
}

.detail-head span {
  color: var(--color-primary);
  font-size: var(--font-size-sm);
  font-weight: 700;
}

.detail-head h2 {
  margin: var(--spacing-xs) 0;
  font-size: var(--font-size-2xl);
}

.detail-head small {
  color: var(--text-secondary);
}

.detail-block {
  margin-top: var(--spacing-lg);
}

.detail-block h3 {
  display: flex;
  align-items: center;
  gap: var(--spacing-xs);
  margin-bottom: var(--spacing-sm);
  font-size: var(--font-size-base);
}

.detail-block ul {
  padding-left: 1.1rem;
}

.tag-cloud {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-sm);
}

.tag-cloud span {
  padding: var(--spacing-xs) var(--spacing-sm);
  border-radius: var(--radius-full);
  background: var(--bg-secondary);
  color: var(--text-secondary);
  font-size: var(--font-size-sm);
  font-weight: 600;
}

.tag-cloud--danger span {
  background: var(--color-primary-subtle);
  color: var(--color-primary-dark);
}

@media (max-width: 1180px) {
  .knowledge-workbench {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .regulation-page {
    padding-top: 7rem;
  }

  .regulation-hero,
  .source-doc-strip,
  .stat-strip {
    grid-template-columns: 1fr;
  }

  .regulation-hero {
    flex-direction: column;
    padding: var(--spacing-xl);
  }
}
</style>
