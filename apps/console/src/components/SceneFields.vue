<script setup>
import { ref, watch, toRaw } from 'vue'
const props=defineProps({modelValue:{type:Object,default:()=>({})}})
const emit=defineEmits(['update:modelValue'])
const fields=[{key:'building_use',label:'建筑用途',type:'text'}, {key:'building_height',label:'建筑高度',type:'number',displayUnit:'米'},
 {key:'measured_width',label:'通道实测净宽',type:'number',unit:'米'}, {key:'pressure_measurement',label:'实测压力',type:'number',unit:'MPa'},
 {key:'required_quantity',label:'应配数量',type:'number',unit:'具'}, {key:'observed_quantity',label:'现场数量',type:'number',unit:'具'}]
const values=ref({}); const confirmed=ref({});let lastEmitted=null
watch(()=>props.modelValue,v=>{if(toRaw(v)===lastEmitted)return;const newValues={},newConfirmed={};for(const f of fields){const x=v?.[f.key];if(x?.value!==undefined){newValues[f.key]=String(x.value);newConfirmed[f.key]=x.confirmed===true}else if(x!==undefined&&typeof x!=='object'){newValues[f.key]=String(x);newConfirmed[f.key]=true}else{newValues[f.key]='';newConfirmed[f.key]=false}}values.value=newValues;confirmed.value=newConfirmed},{immediate:true})
function update(){const output={...props.modelValue};for(const f of fields){delete output[f.key];if(confirmed.value[f.key]&&values.value[f.key]!==''){let value=values.value[f.key];if(f.type==='number'){value=Number(value);if(!Number.isFinite(value)||value<0)continue}output[f.key]=f.unit?{value,unit:f.unit,confirmed:true}:value}}lastEmitted=output;emit('update:modelValue',output)}
</script>
<template><fieldset class="scene-fields"><legend>现场条件</legend><p class="muted">只勾选已现场核实或查阅资料确认的项目。未确认的信息保持空白。</p><div class="scene-grid"><label v-for="field in fields" :key="field.key" class="field"><span>{{ field.label }}{{ (field.unit||field.displayUnit)?'（'+(field.unit||field.displayUnit)+'）':'' }}</span><input v-model="values[field.key]" :type="field.type" min="0" :step="field.key.includes('quantity')?'1':'any'" class="input" @change="update"><span class="confirmation"><input v-model="confirmed[field.key]" type="checkbox" @change="update">已确认</span></label></div></fieldset></template>
<style scoped>.scene-fields{border:0;padding:0;min-width:0}.scene-fields legend{font-weight:650;margin:12px 0}.scene-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.confirmation{display:flex;gap:8px;font-size:12px}@media(max-width:560px){.scene-grid{grid-template-columns:1fr}}</style>
