<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import cytoscape from 'cytoscape'
import { Database, Focus, Maximize2, Network, RotateCcw, Search, ShieldCheck, ZoomIn, ZoomOut } from 'lucide-vue-next'
import { ultraStrictDataset } from '@/data/hydrantUltraStrictDataset'

const graphHost = ref(null)
const activeScope = ref('all')
const searchQuery = ref('')
const selectedNode = ref(null)
let cy = null
let resizeObserver = null

const nodeSize = (kind, count = 0) => {
  if (kind === 'root') return 116
  if (kind === 'scope') return 92
  if (kind === 'ok' || kind === 'bad') return 84
  if (kind === 'object') return Math.min(82, 58 + Math.sqrt(count || 1) * 1.6)
  if (kind === 'defect') return Math.min(96, 54 + Math.sqrt(count || 1) * 2.1)
  return 64
}

const scopes = [
  {
    id: 'appearance', label: '箱体外观',
    description: '箱体、箱门、标识、铭牌、操作说明及遮挡情况。',
    objects: [
      ['access', '可见性与通道', '箱体和箱门是否被物品遮挡。', [
        ['blocked', '物品遮挡', '室内消火栓箱体或箱门被物品遮挡']
      ]],
      ['instructions', '操作说明', '明显部位是否有耐久性文字或图形操作说明。', [
        ['no-instructions', '无操作说明', '室内消火栓箱明显部位未采用耐久性文字或图形标注操作说明']
      ]],
      ['door-marking', '箱门标识', '“消火栓 / FIRE HYDRANT”字样的完整性和清晰度。', [
        ['no-marking', '无中英文标识', '室内消火栓箱门上未标注“消火栓”和英文“FIRE HYDRANT”字样'],
        ['blurred-marking', '箱门标识模糊', '室内消火栓箱门标识模糊']
      ]],
      ['nameplate', '产品铭牌', '箱体铭牌是否存在且可识别。', [
        ['no-nameplate', '箱体无铭牌', '室内消火栓箱体无铭牌']
      ]],
      ['cabinet-door', '箱门结构', '箱门是否存在且结构完整。', [
        ['door-missing', '箱门缺失', '室内消火栓箱门缺失'],
        ['glass-door', '玻璃门', '室内消火栓箱门为玻璃门']
      ]],
      ['cabinet-body', '箱体结构', '箱体是否存在、完整且无明显锈蚀。', [
        ['cabinet-missing', '无箱体', '室内消火栓无箱体'],
        ['cabinet-rust', '箱体锈蚀', '室内消火栓箱锈蚀']
      ]]
    ]
  },
  {
    id: 'internal', label: '内部组件',
    description: '手轮、栓口、水带、水枪、接口及软管卷盘等内部组件。',
    objects: [
      ['handwheel', '消火栓手轮', '手轮是否存在并具备启闭条件。', [
        ['handwheel-missing', '手轮缺失', '室内消火栓手轮缺失']
      ]],
      ['reel-pipe', '软管卷盘供水管', '供水管是否存在影响通水的严重折弯。', [
        ['pipe-bent', '供水管折弯', '消防软管卷盘供水管道折弯严重']
      ]],
      ['hydrant-outlet', '消火栓栓口', '栓口朝向是否利于快速连接和出水。', [
        ['outlet-direction', '栓口方向错误', '室内消火栓栓口方向错误']
      ]],
      ['fire-interface', '消防接口', '消防接口是否齐全。', [
        ['interface-missing', '消防接口缺失', '室内消火栓消防接口缺失']
      ]],
      ['nozzle', '消防水枪', '消防水枪是否在位。', [
        ['nozzle-missing', '无消防水枪', '室内消火栓无消防水枪']
      ]],
      ['hose', '消防水带', '消防水带是否在位。', [
        ['hose-missing', '无消防水带', '室内消火栓无消防水带']
      ]]
    ]
  }
]

const countByLabel = new Map(ultraStrictDataset.defectGroups.flatMap(group => group.items.map(item => [item.label, item.value])))

const elements = computed(() => {
  const result = [
    { data: { id: 'root', label: '室内消火栓巡检', kind: 'root', kindLabel: '业务主体', scope: 'all', count: 1475, countLabel: '数据集样本', size: nodeSize('root'), description: '室内消火栓 V5 Ultra Strict 自动巡检知识体系。' } },
    { data: { id: 'verdict-ok', label: '合规', kind: 'ok', kindLabel: '判定结果', scope: 'all', count: 194, countLabel: '合规样本', size: nodeSize('ok'), description: '检查范围内未发现可核验隐患。' } },
    { data: { id: 'verdict-bad', label: '不合规', kind: 'bad', kindLabel: '判定结果', scope: 'all', count: 1281, countLabel: '不合规样本', size: nodeSize('bad'), description: '存在至少一项具有可核验视觉证据的隐患。' } },
    { data: { id: 'root-ok', source: 'root', target: 'verdict-ok', relation: '可判定为', scope: 'all' } },
    { data: { id: 'root-bad', source: 'root', target: 'verdict-bad', relation: '可判定为', scope: 'all' } },
    { data: { id: 'guide-verdict', source: 'verdict-ok', target: 'verdict-bad', relation: '判定对照', scope: 'all', guide: true } }
  ]

  scopes.forEach(scope => {
    const scopeCount = ultraStrictDataset.scopeDistribution.find(item => item.label === scope.label)?.value || 0
    result.push(
      { data: { id: `scope-${scope.id}`, label: scope.label, kind: 'scope', kindLabel: '检查范围', scope: scope.id, count: scopeCount, countLabel: '范围样本', size: nodeSize('scope', scopeCount), description: scope.description } },
      { data: { id: `root-${scope.id}`, source: 'root', target: `scope-${scope.id}`, relation: '包含', scope: scope.id } }
    )
    scope.objects.forEach(([objectId, objectLabel, objectDescription, defects]) => {
      const objectCount = defects.reduce((sum, defect) => sum + (countByLabel.get(defect[2]) || 0), 0)
      result.push(
        { data: { id: `object-${objectId}`, label: objectLabel, kind: 'object', kindLabel: '检查对象', scope: scope.id, count: objectCount, countLabel: '标签出现次数', size: nodeSize('object', objectCount), description: objectDescription } },
        { data: { id: `${scope.id}-${objectId}`, source: `scope-${scope.id}`, target: `object-${objectId}`, relation: '检查', scope: scope.id } }
      )
      defects.forEach(([defectId, shortLabel, fullLabel]) => {
        const defectCount = countByLabel.get(fullLabel) || 0
        result.push(
          { data: { id: `defect-${defectId}`, label: shortLabel, fullLabel, kind: 'defect', kindLabel: '隐患类别', scope: scope.id, count: defectCount, countLabel: '标签出现次数', size: nodeSize('defect', defectCount), description: fullLabel } },
          { data: { id: `${objectId}-${defectId}`, source: `object-${objectId}`, target: `defect-${defectId}`, relation: '可发现', scope: scope.id } },
          { data: { id: `${defectId}-bad`, source: `defect-${defectId}`, target: 'verdict-bad', relation: '判定为', scope: scope.id } }
        )
      })
    })
  })
  result.push(
    { data: { id: 'guide-scopes', source: 'scope-appearance', target: 'scope-internal', relation: '范围对照', scope: 'all', guide: true } },
    { data: { id: 'guide-appearance-ok', source: 'scope-appearance', target: 'verdict-ok', relation: '合规对照', scope: 'appearance', guide: true } },
    { data: { id: 'guide-internal-ok', source: 'scope-internal', target: 'verdict-ok', relation: '合规对照', scope: 'internal', guide: true } }
  )
  return result
})

const nodeTotal = computed(() => elements.value.filter(item => !item.data.source).length)
const edgeTotal = computed(() => elements.value.filter(item => item.data.source).length)
const scopeSummary = computed(() => {
  const labelMap = { all: '全部关系', appearance: '箱体外观', internal: '内部组件' }
  const inScope = item => activeScope.value === 'all' || item.data.scope === 'all' || item.data.scope === activeScope.value
  return {
    label: labelMap[activeScope.value],
    nodes: elements.value.filter(item => !item.data.source && inScope(item)).length,
    edges: elements.value.filter(item => item.data.source && inScope(item)).length
  }
})
const ranked = computed(() => {
  const allowed = activeScope.value === 'all' ? ['appearance', 'internal'] : [activeScope.value]
  return scopes.filter(scope => allowed.includes(scope.id)).flatMap(scope => scope.objects.flatMap(object => object[3].map(defect => ({
    id: `defect-${defect[0]}`, label: defect[1], count: countByLabel.get(defect[2]) || 0
  })))).sort((a, b) => b.count - a.count).slice(0, 6)
})

const styles = [
  { selector: 'node', style: { label: 'data(label)', color: '#263238', 'font-size': 10.5, 'font-weight': 700, 'text-wrap': 'wrap', 'text-max-width': 82, 'text-valign': 'center', 'text-halign': 'center', 'background-color': '#ffffff', 'border-width': 1.8, 'border-color': '#cfd8dc', width: 'data(size)', height: 'data(size)', shape: 'ellipse', 'overlay-opacity': 0, 'shadow-blur': 12, 'shadow-color': '#607d8b', 'shadow-opacity': 0.15, 'shadow-offset-x': 0, 'shadow-offset-y': 4, 'transition-property': 'opacity, border-width, border-color, background-color, shadow-opacity, shadow-blur, width, height', 'transition-duration': '150ms' } },
  { selector: 'node[kind="root"]', style: { 'background-color': '#d32f2f', 'border-color': '#9f1f1f', color: '#fff', 'font-size': 13, 'text-max-width': 82, 'shadow-blur': 22, 'shadow-color': '#d32f2f', 'shadow-opacity': 0.28 } },
  { selector: 'node[kind="scope"]', style: { 'background-color': '#fff7ed', 'border-color': '#f6a75f', color: '#7a4319', 'font-size': 12, 'shadow-color': '#f6a75f' } },
  { selector: 'node[kind="object"]', style: { 'background-color': '#eef7fb', 'border-color': '#76a5c0', color: '#264b60', 'text-max-width': 74, 'shadow-color': '#76a5c0' } },
  { selector: 'node[kind="defect"]', style: { 'background-color': '#fff4f4', 'border-color': '#e57373', color: '#9f2f2f', 'text-max-width': 76, 'shadow-color': '#e57373' } },
  { selector: 'node[kind="bad"]', style: { 'background-color': '#d32f2f', 'border-color': '#9f1f1f', color: '#fff', shape: 'diamond', 'font-size': 12, 'shadow-blur': 18, 'shadow-color': '#d32f2f', 'shadow-opacity': 0.24 } },
  { selector: 'node[kind="ok"]', style: { 'background-color': '#2e7d32', 'border-color': '#1b5e20', color: '#fff', shape: 'diamond', 'font-size': 12, 'shadow-blur': 18, 'shadow-color': '#2e7d32', 'shadow-opacity': 0.2 } },
  { selector: 'edge', style: { width: 1.15, 'line-color': '#b9c6cc', 'target-arrow-color': '#a8b8bf', 'target-arrow-shape': 'triangle', 'curve-style': 'unbundled-bezier', 'control-point-distances': 18, 'control-point-weights': 0.5, label: '', color: '#78909c', 'font-size': 8, 'font-weight': 700, 'text-background-color': '#ffffff', 'text-background-opacity': 0.92, 'text-background-padding': 2.5, 'arrow-scale': 0.62, 'overlay-opacity': 0, 'transition-property': 'opacity, line-color, target-arrow-color, width', 'transition-duration': '150ms' } },
  { selector: 'edge[guide]', style: { width: 0, opacity: 0, 'target-arrow-shape': 'none' } },
  { selector: '.soft-muted', style: { opacity: 0.18 } },
  { selector: 'node.hover-focus', style: { opacity: 1, 'shadow-opacity': 0.24 } },
  { selector: 'edge.hover-focus', style: { opacity: 1, label: 'data(relation)', 'line-color': '#e57373', 'target-arrow-color': '#d32f2f', width: 2.3 } },
  { selector: '.muted', style: { opacity: 0.08 } },
  { selector: '.hit', style: { 'border-width': 4, 'border-color': '#f57c00', 'background-color': '#fff3d6', 'shadow-color': '#f57c00', 'shadow-opacity': 0.26, 'shadow-blur': 18 } },
  { selector: ':selected', style: { 'border-width': 4, 'border-color': '#b71c1c', 'underlay-color': '#e53935', 'underlay-opacity': 0.11, 'underlay-padding': 13, 'shadow-color': '#b71c1c', 'shadow-opacity': 0.25, 'shadow-blur': 20 } }
]

const layoutGraph = (animate = false) => {
  if (!cy) return
  cy.elements(':visible').layout({
    name: 'cose',
    animate,
    animationDuration: 520,
    animationEasing: 'ease-out',
    fit: true,
    padding: 58,
    randomize: false,
    componentSpacing: 86,
    nodeRepulsion: node => {
      const kind = node.data('kind')
      if (kind === 'root') return 900000
      if (kind === 'scope') return 650000
      if (kind === 'defect') return 420000
      return 520000
    },
    nodeOverlap: 18,
    idealEdgeLength: edge => edge.data('guide') ? 220 : edge.target().data('kind') === 'bad' ? 145 : 118,
    edgeElasticity: edge => edge.data('guide') ? 18 : 80,
    gravity: 0.9,
    numIter: 1400,
    initialTemp: 140,
    coolingFactor: 0.96,
    minTemp: 1
  }).run()
}

const applySearch = () => {
  if (!cy) return
  cy.elements().removeClass('muted hit')
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return
  const visibleNodes = cy.nodes(':visible')
  const hits = visibleNodes.filter(node => `${node.data('label')} ${node.data('fullLabel') || ''} ${node.data('description') || ''}`.toLowerCase().includes(query))
  cy.elements(':visible').addClass('muted')
  hits.removeClass('muted').addClass('hit')
  hits.connectedEdges().removeClass('muted')
  hits.neighborhood('node').removeClass('muted')
}

const applyScope = async () => {
  if (!cy) return
  const scope = activeScope.value
  cy.batch(() => {
    cy.nodes().forEach(node => node.style('display', scope === 'all' || node.data('scope') === 'all' || node.data('scope') === scope ? 'element' : 'none'))
    cy.edges().forEach(edge => edge.style('display', edge.source().style('display') !== 'none' && edge.target().style('display') !== 'none' ? 'element' : 'none'))
  })
  await nextTick()
  layoutGraph(true)
  applySearch()
}

const clearHoverFocus = () => cy?.elements().removeClass('soft-muted hover-focus')
const applyHoverFocus = node => {
  if (!cy || searchQuery.value.trim()) return
  cy.elements(':visible').addClass('soft-muted')
  node.closedNeighborhood().removeClass('soft-muted').addClass('hover-focus')
}

const focusNode = id => {
  if (!cy) return
  const node = cy.$id(id)
  if (!node.length) return
  cy.nodes().unselect()
  node.select()
  selectedNode.value = { ...node.data() }
  cy.animate({ center: { eles: node }, zoom: 1.2, duration: 380 })
}

const zoomBy = factor => cy?.zoom({ level: Math.min(2, Math.max(0.45, cy.zoom() * factor)), renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } })
const fitGraph = () => cy?.fit(cy.elements(':visible'), 36)
const resetGraph = () => {
  searchQuery.value = ''
  activeScope.value = 'all'
  selectedNode.value = null
  cy?.nodes().unselect()
  clearHoverFocus()
  layoutGraph(true)
}

onMounted(() => nextTick(() => {
  cy = cytoscape({ container: graphHost.value, elements: elements.value, style: styles, minZoom: 0.45, maxZoom: 2, boxSelectionEnabled: false })
  cy.on('tap', 'node', event => { cy.nodes().unselect(); event.target.select(); selectedNode.value = { ...event.target.data() } })
  cy.on('mouseover', 'node', event => applyHoverFocus(event.target))
  cy.on('mouseout', 'node', clearHoverFocus)
  cy.on('tap', event => { if (event.target === cy) { cy.nodes().unselect(); selectedNode.value = null; clearHoverFocus() } })
  layoutGraph()
  resizeObserver = new ResizeObserver(() => { cy?.resize(); fitGraph() })
  resizeObserver.observe(graphHost.value)
}))

watch(activeScope, applyScope)
watch(searchQuery, applySearch)
onUnmounted(() => { resizeObserver?.disconnect(); cy?.destroy(); cy = null })
</script>

<template>
  <div class="knowledge-page">
    <header class="knowledge-header">
      <div class="knowledge-title">
        <Network :size="22" />
        <div><h1>室内消火栓知识图谱</h1><p>V5 Ultra Strict · 类别体系与检查关系</p></div>
      </div>
      <div class="knowledge-stats"><div><strong>{{ nodeTotal }}</strong><span>节点</span></div><div><strong>{{ edgeTotal }}</strong><span>关系</span></div><div><strong>1475</strong><span>样本</span></div></div>
    </header>

    <main class="knowledge-workspace">
      <section class="graph-tool">
        <div class="graph-toolbar">
          <div class="scope-control">
            <button v-for="item in [{id:'all',label:'全部关系'},{id:'appearance',label:'箱体外观'},{id:'internal',label:'内部组件'}]" :key="item.id" type="button" :class="{active:activeScope===item.id}" @click="activeScope=item.id">{{ item.label }}</button>
          </div>
          <label class="graph-search"><Search :size="16" /><input v-model="searchQuery" type="search" placeholder="搜索类别或检查对象" /></label>
          <div class="graph-actions">
            <button type="button" title="放大" aria-label="放大" @click="zoomBy(1.18)"><ZoomIn :size="18" /></button>
            <button type="button" title="缩小" aria-label="缩小" @click="zoomBy(0.84)"><ZoomOut :size="18" /></button>
            <button type="button" title="适应画布" aria-label="适应画布" @click="fitGraph"><Maximize2 :size="17" /></button>
            <button type="button" title="重置" aria-label="重置" @click="resetGraph"><RotateCcw :size="17" /></button>
          </div>
        </div>
        <div class="graph-stage">
          <div class="graph-status">
            <span>当前视图</span>
            <strong>{{ scopeSummary.label }}</strong>
            <em>{{ scopeSummary.nodes }} 节点 / {{ scopeSummary.edges }} 关系</em>
          </div>
          <div ref="graphHost" class="graph-canvas"></div>
          <div class="graph-path relation-mode">
            <span>中心辐射</span><i></i><span>双簇关系</span><i></i><span>权重节点</span><i></i><span>Hover 追踪</span>
          </div>
          <div class="graph-legend"><span><i class="root"></i>业务主体</span><span><i class="scope"></i>检查范围</span><span><i class="object"></i>检查对象</span><span><i class="defect"></i>隐患类别</span><span><i class="verdict"></i>判定结果</span></div>
        </div>
      </section>

      <aside class="knowledge-panel">
        <section class="node-detail">
          <template v-if="selectedNode">
            <span class="panel-kicker"><Focus :size="15" />{{ selectedNode.kindLabel }}</span>
            <h2>{{ selectedNode.label }}</h2>
            <p v-if="selectedNode.fullLabel" class="full-label">{{ selectedNode.fullLabel }}</p>
            <p>{{ selectedNode.description }}</p>
            <div class="node-metric"><strong>{{ selectedNode.count }}</strong><span>{{ selectedNode.countLabel }}</span></div>
          </template>
          <template v-else>
            <ShieldCheck :size="28" class="empty-icon" />
            <span class="panel-kicker">图谱概览</span>
            <h2>V5 巡检知识体系</h2>
            <p>现有类别按检查范围、检查对象、隐患标签和判定结果组织。</p>
            <div class="panel-quick-stats">
              <div><strong>2</strong><span>检查范围</span></div>
              <div><strong>12</strong><span>检查对象</span></div>
              <div><strong>14</strong><span>隐患标签</span></div>
            </div>
          </template>
        </section>
        <section class="ranked-section">
          <div class="panel-heading"><div><span class="panel-kicker"><Database :size="15" />数据分布</span><h2>高频隐患</h2></div><span>{{ activeScope==='all'?'全部':activeScope==='appearance'?'外观':'内部' }}</span></div>
          <button v-for="(item,index) in ranked" :key="item.id" type="button" class="ranked-item" @click="focusNode(item.id)"><span>{{ String(index+1).padStart(2,'0') }}</span><span>{{ item.label }}</span><strong>{{ item.count }}</strong></button>
        </section>
      </aside>
    </main>
  </div>
</template>

<style scoped>
.knowledge-page{
  min-height:100vh;
  padding-top:72px;
  color:#263238;
  background:#f3f5f7;
}
.knowledge-header{
  min-height:88px;
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:24px;
  padding:16px 28px;
  border-bottom:1px solid #e3e7ea;
  background:linear-gradient(180deg,#fff 0%,#fafbfc 100%);
}
.knowledge-title{
  display:flex;
  align-items:center;
  gap:12px;
  min-width:0;
}
.knowledge-title>svg{
  flex:0 0 auto;
  color:#d32f2f;
  filter:drop-shadow(0 5px 10px rgba(211,47,47,.18));
}
.knowledge-title h1,
.knowledge-panel h2{
  margin:0;
  letter-spacing:0;
}
.knowledge-title h1{
  font-size:20px;
  line-height:1.35;
  color:#1f2529;
}
.knowledge-title p{
  margin:3px 0 0;
  color:#7b858c;
  font-size:12px;
}
.knowledge-stats{
  display:grid;
  grid-template-columns:repeat(3,minmax(72px,1fr));
  border:1px solid #e1e5e8;
  border-radius:8px;
  overflow:hidden;
  box-shadow:0 8px 20px rgba(38,50,56,.06);
}
.knowledge-stats div{
  min-width:76px;
  padding:8px 14px;
  text-align:center;
  background:#fff;
}
.knowledge-stats div+div{
  border-left:1px solid #edf0f2;
}
.knowledge-stats strong,
.knowledge-stats span{
  display:block;
}
.knowledge-stats strong{
  font-size:17px;
  font-variant-numeric:tabular-nums;
  color:#1f2529;
}
.knowledge-stats span{
  font-size:10px;
  color:#8a949a;
}
.knowledge-workspace{
  display:grid;
  grid-template-columns:minmax(0,1fr) 326px;
  height:calc(100vh - 160px);
  min-height:620px;
}
.graph-tool{
  min-width:0;
  display:grid;
  grid-template-rows:auto minmax(0,1fr);
  border-right:1px solid #e1e5e8;
  background:#fff;
}
.graph-toolbar{
  min-height:62px;
  display:flex;
  align-items:center;
  gap:12px;
  padding:11px 16px;
  border-bottom:1px solid #e5e9ec;
  background:#fff;
}
.scope-control{
  display:inline-flex;
  padding:3px;
  border:1px solid #dfe4e7;
  border-radius:8px;
  background:#f5f7f8;
}
.scope-control button{
  min-height:34px;
  padding:0 13px;
  border-radius:6px;
  color:#6f797f;
  font-size:12px;
  white-space:nowrap;
  transition:color .16s ease,background .16s ease,box-shadow .16s ease;
}
.scope-control button:hover{
  color:#b71c1c;
  background:#fff;
}
.scope-control button.active{
  color:#fff;
  background:#d32f2f;
  box-shadow:0 8px 18px rgba(211,47,47,.2);
}
.graph-search{
  min-width:200px;
  max-width:340px;
  flex:1;
  display:flex;
  align-items:center;
  gap:8px;
  height:40px;
  padding:0 12px;
  border:1px solid #dfe4e7;
  border-radius:8px;
  color:#9aa3a8;
  background:#fff;
  box-shadow:0 1px 2px rgba(38,50,56,.03);
  transition:border-color .16s ease,box-shadow .16s ease;
}
.graph-search:focus-within{
  border-color:#e57373;
  box-shadow:0 0 0 3px rgba(229,57,53,.09);
}
.graph-search input{
  min-width:0;
  width:100%;
  border:0;
  outline:0;
  color:#263238;
  background:transparent;
  font-size:12px;
}
.graph-search input::placeholder{
  color:#9aa3a8;
}
.graph-actions{
  display:flex;
  gap:6px;
  margin-left:auto;
}
.graph-actions button{
  width:38px;
  height:38px;
  display:grid;
  place-items:center;
  border:1px solid #dfe4e7;
  border-radius:8px;
  color:#607d8b;
  background:#fff;
  box-shadow:0 1px 2px rgba(38,50,56,.04);
  transition:transform .16s ease,color .16s ease,border-color .16s ease,background .16s ease;
}
.graph-actions button:hover{
  color:#b71c1c;
  border-color:#ef9a9a;
  background:#fff7f7;
  transform:translateY(-1px);
}
.graph-stage{
  position:relative;
  min-height:0;
  overflow:hidden;
  background-color:#fbfcfd;
  background-image:
    linear-gradient(rgba(120,144,156,.16) 1px,transparent 1px),
    linear-gradient(90deg,rgba(120,144,156,.16) 1px,transparent 1px),
    linear-gradient(rgba(211,47,47,.04),rgba(46,125,50,.035));
  background-size:30px 30px,30px 30px,100% 100%;
}
.graph-stage::before{
  content:"";
  position:absolute;
  inset:0;
  border-top:1px solid rgba(255,255,255,.75);
  box-shadow:inset 0 22px 42px rgba(38,50,56,.035);
  pointer-events:none;
  z-index:1;
}
.graph-canvas{
  position:absolute;
  inset:0;
  z-index:2;
}
.graph-status,
.graph-path,
.graph-legend{
  position:absolute;
  z-index:3;
  border:1px solid rgba(207,216,220,.92);
  border-radius:8px;
  background:rgba(255,255,255,.9);
  box-shadow:0 12px 28px rgba(38,50,56,.09);
  backdrop-filter:blur(10px);
}
.graph-status{
  left:16px;
  top:16px;
  display:grid;
  gap:3px;
  min-width:150px;
  padding:10px 12px;
  pointer-events:none;
}
.graph-status span{
  color:#8a949a;
  font-size:10px;
}
.graph-status strong{
  color:#1f2529;
  font-size:15px;
}
.graph-status em{
  color:#d32f2f;
  font-size:10px;
  font-style:normal;
}
.graph-path{
  right:16px;
  top:16px;
  display:flex;
  align-items:center;
  gap:8px;
  padding:9px 11px;
  color:#69777e;
  font-size:10px;
  pointer-events:none;
}
.graph-path i{
  width:18px;
  height:1px;
  background:#cfd8dc;
}
.graph-legend{
  left:16px;
  bottom:16px;
  display:flex;
  flex-wrap:wrap;
  gap:8px 14px;
  max-width:calc(100% - 32px);
  padding:9px 12px;
  pointer-events:none;
}
.graph-legend span{
  display:inline-flex;
  align-items:center;
  gap:6px;
  color:#5f6b72;
  font-size:10px;
  white-space:nowrap;
}
.graph-legend i{
  width:9px;
  height:9px;
  border-radius:2px;
  border:1px solid;
}
.graph-legend .root{
  background:#d32f2f;
  border-color:#9f1f1f;
}
.graph-legend .scope{
  background:#fff7ed;
  border-color:#f6a75f;
}
.graph-legend .object{
  background:#eef7fb;
  border-color:#76a5c0;
}
.graph-legend .defect{
  background:#fff4f4;
  border-color:#e57373;
}
.graph-legend .verdict{
  background:#2e7d32;
  border-color:#1b5e20;
  transform:rotate(45deg);
}
.knowledge-panel{
  min-width:0;
  overflow-y:auto;
  background:#fff;
}
.node-detail,
.ranked-section{
  padding:23px 20px;
}
.node-detail{
  min-height:292px;
  border-bottom:1px solid #edf0f2;
  background:linear-gradient(180deg,#fff 0%,#fcfcfd 100%);
}
.panel-kicker{
  display:inline-flex;
  align-items:center;
  gap:6px;
  color:#d32f2f;
  font-size:10px;
  font-weight:800;
}
.node-detail h2,
.ranked-section h2{
  color:#1f2529;
  font-size:16px;
}
.node-detail h2{
  margin-top:10px;
}
.node-detail p{
  margin:10px 0 0;
  color:#657178;
  font-size:12px;
  line-height:1.75;
}
.full-label{
  padding:10px 11px;
  border-left:2px solid #d32f2f;
  color:#4f5a60!important;
  background:#fff6f6;
  border-radius:0 8px 8px 0;
}
.empty-icon{
  display:block;
  margin-bottom:16px;
  color:#e57373;
  filter:drop-shadow(0 8px 14px rgba(211,47,47,.16));
}
.node-metric{
  display:flex;
  align-items:baseline;
  gap:8px;
  margin-top:18px;
  padding-top:14px;
  border-top:1px solid #edf0f2;
}
.node-metric strong{
  color:#c62828;
  font-size:26px;
  font-variant-numeric:tabular-nums;
}
.node-metric span{
  color:#7d878d;
  font-size:11px;
}
.panel-quick-stats{
  display:grid;
  grid-template-columns:repeat(3,1fr);
  gap:8px;
  margin-top:18px;
}
.panel-quick-stats div{
  min-width:0;
  padding:10px 8px;
  border:1px solid #edf0f2;
  border-radius:8px;
  background:#fff;
}
.panel-quick-stats strong,
.panel-quick-stats span{
  display:block;
}
.panel-quick-stats strong{
  color:#c62828;
  font-size:18px;
  font-variant-numeric:tabular-nums;
}
.panel-quick-stats span{
  margin-top:2px;
  color:#8a949a;
  font-size:10px;
  white-space:nowrap;
}
.panel-heading{
  display:flex;
  align-items:flex-start;
  justify-content:space-between;
  gap:12px;
  margin-bottom:14px;
}
.panel-heading h2{
  margin-top:5px;
}
.panel-heading>span{
  padding:4px 8px;
  border:1px solid #e1e5e8;
  border-radius:6px;
  color:#69777e;
  background:#fafbfc;
  font-size:9px;
}
.ranked-item{
  width:100%;
  min-height:46px;
  display:grid;
  grid-template-columns:30px minmax(0,1fr) auto;
  align-items:center;
  gap:8px;
  border-top:1px solid #edf0f2;
  color:#424b50;
  text-align:left;
  transition:color .16s ease,background .16s ease,transform .16s ease;
}
.ranked-item:last-child{
  border-bottom:1px solid #edf0f2;
}
.ranked-item:hover{
  color:#b71c1c;
  background:#fff7f7;
  transform:translateX(2px);
}
.ranked-item span:first-child{
  color:#9aa3a8;
  font-size:10px;
  font-variant-numeric:tabular-nums;
}
.ranked-item span:nth-child(2){
  min-width:0;
  overflow:hidden;
  text-overflow:ellipsis;
  white-space:nowrap;
  font-size:12px;
}
.ranked-item strong{
  color:#c62828;
  font-size:12px;
  font-variant-numeric:tabular-nums;
}
@media(max-width:960px){
  .knowledge-workspace{
    grid-template-columns:1fr;
    height:auto;
  }
  .graph-tool{
    height:680px;
    border-right:0;
    border-bottom:1px solid #e1e5e8;
  }
  .knowledge-panel{
    display:grid;
    grid-template-columns:1fr 1fr;
    overflow:visible;
  }
  .node-detail{
    border-right:1px solid #edf0f2;
    border-bottom:0;
  }
}
@media(max-width:720px){
  .knowledge-page{
    padding-top:64px;
  }
  .knowledge-header{
    align-items:flex-start;
    flex-direction:column;
    padding:16px;
  }
  .knowledge-stats{
    width:100%;
  }
  .knowledge-stats div{
    min-width:0;
  }
  .graph-toolbar{
    align-items:stretch;
    flex-wrap:wrap;
  }
  .scope-control{
    width:100%;
  }
  .scope-control button{
    flex:1;
    padding:0 7px;
  }
  .graph-search{
    max-width:none;
  }
  .graph-tool{
    height:640px;
  }
  .knowledge-panel{
    grid-template-columns:1fr;
  }
  .node-detail{
    border-right:0;
    border-bottom:1px solid #edf0f2;
  }
  .graph-path,
  .graph-legend{
    display:none;
  }
}
</style>
