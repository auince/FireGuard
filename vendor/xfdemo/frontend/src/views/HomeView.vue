<script setup>
import { onMounted, ref } from 'vue'
import { Activity, ArrowRight, BookOpenCheck, Database, History, ScanSearch, ShieldCheck } from 'lucide-vue-next'
import { checkHealth } from '@/api'

const systemStatus = ref('checking')

const workspaceLinks = [
  { path: '/inspect', title: '智能检测', desc: '上传巡检图片，完成设施状态识别与异常分析。', icon: ScanSearch, action: '开始检测' },
  { path: '/history', title: '检测历史', desc: '追踪检测结论、证据标记与人工确认记录。', icon: History, action: '查看记录' },
  { path: '/dataset', title: '数据集', desc: '浏览清洗后的图片、标签、划分统计和提示词版本。', icon: Database, action: '进入数据集' },
  { path: '/regulations', title: '法规库', desc: '检索消防法规条款与当前系统收录的规范资料。', icon: BookOpenCheck, action: '检索法规' }
]

const statusText = {
  online: '服务运行正常',
  checking: '正在检查服务',
  offline: '服务暂不可用'
}

onMounted(async () => {
  try {
    const res = await checkHealth()
    systemStatus.value = res.status === 'running' ? 'online' : 'offline'
  } catch {
    systemStatus.value = 'offline'
  }
})
</script>

<template>
  <div class="workspace">
    <div class="workspace__container container">
      <section class="workspace-head">
        <div class="workspace-head__content">
          <span class="workspace-head__eyebrow">XF INSPECTION WORKSPACE</span>
          <h1>消防巡检工作台</h1>
          <p>从图片检测、证据复核到历史追踪，在一个工作区完成消防设施巡检。</p>
          <router-link to="/inspect" class="btn btn-primary">
            <ScanSearch :size="18" />
            开始检测
          </router-link>
        </div>

        <aside class="system-panel" aria-label="系统状态">
          <div class="system-panel__top">
            <span class="system-panel__icon"><ShieldCheck :size="20" /></span>
            <span>
              <small>系统状态</small>
              <strong>{{ statusText[systemStatus] }}</strong>
            </span>
            <i :class="`system-panel__dot system-panel__dot--${systemStatus}`"></i>
          </div>
          <dl>
            <div><dt>分析能力</dt><dd>综合智能研判</dd></div>
            <div><dt>记录管理</dt><dd>安全留存</dd></div>
            <div><dt>结果输出</dt><dd>全程可追溯</dd></div>
          </dl>
        </aside>
      </section>

      <section class="workspace-modules">
        <div class="section-heading">
          <span>
            <small>WORKSPACE</small>
            <h2>常用功能</h2>
          </span>
          <p>按巡检流程组织的核心入口</p>
        </div>

        <div class="module-grid">
          <router-link v-for="item in workspaceLinks" :key="item.path" :to="item.path" class="module-card">
            <span class="module-card__icon"><component :is="item.icon" :size="22" /></span>
            <h3>{{ item.title }}</h3>
            <p>{{ item.desc }}</p>
            <span class="module-card__action">{{ item.action }} <ArrowRight :size="16" /></span>
          </router-link>
        </div>
      </section>

      <section class="workflow-strip">
        <span class="workflow-strip__label"><Activity :size="16" /> 工作流程</span>
        <ol>
          <li><b>01</b><span>资料提交</span></li>
          <li><b>02</b><span>智能分析</span></li>
          <li><b>03</b><span>结果确认</span></li>
          <li><b>04</b><span>记录留存</span></li>
        </ol>
      </section>
    </div>
  </div>
</template>

<style scoped>
.workspace { min-height: 100vh; padding: 108px 0 38px; background: var(--bg-secondary); }
.workspace__container { display: grid; gap: 24px; }

.workspace-head {
  min-height: 330px;
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(300px, .75fr);
  gap: 44px;
  align-items: center;
  padding: clamp(30px, 5vw, 58px);
  border: 1px solid var(--color-gray-200);
  border-radius: var(--radius-xl);
  background: #fff;
  box-shadow: var(--shadow-sm);
}

.workspace-head__eyebrow, .section-heading small { color: var(--color-primary); font-size: 12px; font-weight: 750; }
.workspace-head h1 { margin: 10px 0 12px; font-size: clamp(2.25rem, 4vw, 3.5rem); line-height: 1.12; letter-spacing: 0; }
.workspace-head__content > p { max-width: 640px; margin-bottom: 26px; color: var(--text-secondary); font-size: var(--font-size-lg); line-height: 1.8; }

.system-panel { border-left: 1px solid var(--color-gray-200); padding-left: 34px; }
.system-panel__top { display: grid; grid-template-columns: 42px 1fr auto; gap: 12px; align-items: center; padding-bottom: 20px; border-bottom: 1px solid var(--color-gray-200); }
.system-panel__icon { width: 42px; height: 42px; display: grid; place-items: center; border-radius: var(--radius-lg); color: var(--color-primary); background: var(--color-primary-subtle); }
.system-panel__top span:nth-child(2) { display: grid; }
.system-panel__top small { color: var(--text-tertiary); font-size: 12px; }
.system-panel__top strong { font-size: var(--font-size-base); }
.system-panel__dot { width: 9px; height: 9px; border-radius: 50%; background: var(--color-gray-400); }
.system-panel__dot--online { background: var(--color-success); box-shadow: 0 0 0 5px rgba(47,132,100,.1); }
.system-panel__dot--offline { background: var(--color-error); }
.system-panel dl { display: grid; gap: 13px; padding-top: 19px; }
.system-panel dl div { display: flex; justify-content: space-between; gap: 18px; font-size: 13px; }
.system-panel dt { color: var(--text-tertiary); }
.system-panel dd { color: var(--text-secondary); text-align: right; }

.workspace-modules { padding: 26px 0 0; }
.section-heading { display: flex; align-items: end; justify-content: space-between; gap: 20px; margin-bottom: 16px; }
.section-heading h2 { margin-top: 3px; font-size: 24px; }
.section-heading p { color: var(--text-tertiary); font-size: 13px; }

.module-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
.module-card { min-height: 220px; display: flex; flex-direction: column; padding: 24px; border: 1px solid var(--color-gray-200); border-radius: var(--radius-xl); background: #fff; box-shadow: var(--shadow-sm); transition: border-color var(--transition-fast), box-shadow var(--transition-fast), transform var(--transition-fast); }
.module-card:hover { border-color: #d7c0bd; box-shadow: var(--shadow-md); transform: translateY(-2px); }
.module-card__icon { width: 42px; height: 42px; display: grid; place-items: center; margin-bottom: 24px; border: 1px solid #ead3d1; border-radius: var(--radius-lg); color: var(--color-primary); background: #fff9f8; }
.module-card h3 { margin-bottom: 8px; font-size: 18px; }
.module-card p { color: var(--text-secondary); font-size: 13px; line-height: 1.7; }
.module-card__action { display: flex; align-items: center; gap: 6px; margin-top: auto; padding-top: 20px; color: var(--color-primary-dark); font-size: 13px; font-weight: 700; }

.workflow-strip { display: flex; align-items: center; gap: 28px; margin-top: 8px; padding: 18px 22px; border: 1px solid var(--color-gray-200); border-radius: var(--radius-xl); background: #eef1ef; }
.workflow-strip__label { display: flex; align-items: center; gap: 7px; color: var(--text-primary); font-size: 13px; font-weight: 700; white-space: nowrap; }
.workflow-strip ol { flex: 1; display: grid; grid-template-columns: repeat(4, 1fr); list-style: none; }
.workflow-strip li { display: flex; align-items: center; gap: 9px; padding: 0 18px; border-left: 1px solid var(--color-gray-300); color: var(--text-secondary); font-size: 13px; }
.workflow-strip b { color: var(--color-primary); font-size: 11px; }

@media (max-width: 980px) {
  .workspace-head { grid-template-columns: 1fr; gap: 28px; }
  .system-panel { border-left: 0; border-top: 1px solid var(--color-gray-200); padding: 24px 0 0; }
  .module-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 640px) {
  .workspace { padding-top: 88px; }
  .workspace-head { min-height: 0; padding: 24px 20px; }
  .workspace-head h1 { font-size: 32px; }
  .workspace-head__content > p { font-size: 15px; }
  .module-grid { grid-template-columns: 1fr; }
  .module-card { min-height: 184px; }
  .section-heading p { display: none; }
  .workflow-strip { align-items: flex-start; flex-direction: column; gap: 14px; }
  .workflow-strip ol { width: 100%; grid-template-columns: repeat(2, 1fr); gap: 12px 0; }
  .workflow-strip li:nth-child(odd) { border-left: 0; padding-left: 0; }
}
</style>
