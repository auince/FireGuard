<script setup>
const props=defineProps({trace:{type:Array,default:()=>[]},status:String})
const names={Intent:'意图识别',Rewrite:'查询改写',Retrieval:'条款检索',Answer:'答案生成',Verify:'结果复核'}
</script>
<template><ol class="trace-grid" aria-label="Harness 执行记录" :aria-busy="['queued','running'].includes(props.status)"><li v-for="(name,key) in names" :key="key" :class="{done:trace.some(t=>t.node===key)}"><span>{{trace.some(t=>t.node===key)?'✓':'—'}} {{name}}</span><small>{{trace.find(t=>t.node===key)?Number(trace.find(t=>t.node===key).seconds).toFixed(2)+'s':'等待执行'}}</small></li></ol></template>
