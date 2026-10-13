<script setup>
import {computed} from 'vue'
const props=defineProps({trace:{type:Array,default:()=>[]},status:String})
const stages=[['Intent','意图与影像'],['Rewrite','查询改写'],['Retrieval','条款检索'],['Answer','结论生成'],['Verify','结果复核']]
const stageFor=t=>t.stage||({intent:'Intent',rewrite:'Rewrite',retrieve:'Retrieval',draft:'Answer',verify:'Verify',repair:'Verify'}[t.node])||(t.node.includes(':')?'Intent':t.node)
const groups=computed(()=>Object.fromEntries(stages.map(([id])=>[id,props.trace.filter(t=>stageFor(t)===id)])))
</script>
<template><div><ol class="trace-grid" aria-label="执行阶段" :aria-busy="['queued','running'].includes(status)"><li v-for="[id,name] in stages" :key="id" :class="{done:groups[id].length}"><span>{{groups[id].some(t=>t.outcome==='error'||t.degraded)?'!':groups[id].length?'✓':'—'}} {{name}}</span><small>{{groups[id].length?groups[id].reduce((n,t)=>n+Number(t.seconds||0),0).toFixed(2)+'s · '+groups[id].length+' 次节点执行':'尚无记录'}}</small></li></ol><details v-if="trace.length" class="node-details"><summary>查看逐节点执行记录</summary><table><thead><tr><th>节点</th><th>状态</th><th>耗时</th><th>模型调用</th></tr></thead><tbody><tr v-for="(t,i) in trace" :key="i"><td>{{t.node}}</td><td>{{t.outcome==='error'?'失败并降级':t.outcome==='budget_exhausted'?'预算耗尽':t.degraded?'已降级':'完成'}}</td><td>{{t.seconds}}s</td><td>{{t.calls_delta??'—'}}</td></tr></tbody></table></details></div></template>
<style scoped>.node-details{margin-top:16px;overflow:auto}.node-details summary{cursor:pointer;color:var(--text-secondary)}table{width:100%;font-size:12px;border-collapse:collapse}td,th{text-align:left;padding:10px;border-bottom:1px solid var(--color-gray-200)}</style>
