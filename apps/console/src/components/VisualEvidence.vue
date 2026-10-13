<script setup>
defineProps({report:{type:Object,required:true}})
const statuses={completed:'检测完成',unavailable:'检测服务不可用',not_requested:'未提交照片',unsupported_facility:'当前设施暂不支持检测'}
</script>
<template>
  <section v-if="report.image || report.similar_cases?.length" class="card">
    <div class="visual-heading"><h2 class="subheading">现场影像与案例参考</h2><span class="pill">{{statuses[report.detector?.status]||'等待检测'}}</span></div>
    <div v-if="report.image" class="photo-evidence">
      <img :src="report.image" alt="本轮设施照片及检测定位"/>
      <svg v-if="report.detector?.detections?.length" viewBox="0 0 1000 1000" preserveAspectRatio="none" aria-label="设施检测框">
        <g v-for="item in report.detector.detections" :key="item.detector_id"><rect :x="item.bboxNorm[0]*1000" :y="item.bboxNorm[1]*1000" :width="(item.bboxNorm[2]-item.bboxNorm[0])*1000" :height="(item.bboxNorm[3]-item.bboxNorm[1])*1000"/><text :x="item.bboxNorm[0]*1000+4" :y="Math.max(24,item.bboxNorm[1]*1000-6)">{{item.detector_id}}</text></g>
      </svg>
    </div>
    <div v-if="report.detector?.detections?.length" class="detection-list"><span v-for="item in report.detector.detections" :key="item.detector_id">{{item.detector_id}} · {{item.label}} · {{Math.round(item.confidence*100)}}%</span></div>
    <p v-if="report.image" class="muted">检测框用于定位可见目标。未检出目标不能直接判定缺失。</p>
    <p v-if="report.detector?.status==='unavailable'" class="message">检测服务当前不可用，请人工核查照片；报告保留该降级记录。</p>
    <div v-if="report.similar_cases?.length" class="case-list"><h3>历史案例参考</h3><p class="muted">以下为历史记录，不作为本次现场事实或法规依据。</p><article v-for="item in report.similar_cases" :key="item.case_id"><strong>案例 {{item.case_id}}</strong><p>{{item.description}}</p><small>历史审核标记尚未重新核验</small></article></div>
    <p v-else-if="report.warnings?.includes('case_reference_unavailable')" class="muted">历史案例服务暂不可用。</p>
  </section>
</template>
<style scoped>
.visual-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:18px}.photo-evidence{position:relative;max-width:760px;margin:auto}.photo-evidence img{display:block;width:100%;height:auto}.photo-evidence svg{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}.photo-evidence rect{fill:none;stroke:#b63f36;stroke-width:3;vector-effect:non-scaling-stroke}.photo-evidence text{fill:#fff;stroke:#72231f;stroke-width:1;font-size:24px;font-weight:700;paint-order:stroke}.detection-list{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}.detection-list span{padding:5px 10px;background:var(--bg-secondary);border-radius:5px;font-size:12px}.case-list{margin-top:24px}.case-list article{border-top:1px solid var(--color-gray-200);padding:16px 0}.case-list article p{white-space:pre-wrap;font-size:13px;line-height:1.8;margin:8px 0}.case-list small{color:var(--text-tertiary)}
</style>
