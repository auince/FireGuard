<script setup>
import { Activity, ShieldCheck } from 'lucide-vue-next'

const currentYear = new Date().getFullYear()
</script>

<template>
  <footer class="footer">
    <div class="footer__container container">
      <div class="footer__brand">
        <span class="footer__mark"><ShieldCheck :size="18" /></span>
        <span>
          <strong>消防智检</strong>
          <small>消防设施智能巡检工作台</small>
        </span>
      </div>

      <nav class="footer__nav" aria-label="页脚导航">
        <router-link to="/inspect">智能检测</router-link>
        <router-link to="/history">检测历史</router-link>
        <router-link to="/dataset">数据集</router-link>
        <router-link to="/">首页</router-link>
      </nav>

      <div class="footer__meta">
        <span class="footer__status"><Activity :size="14" /> 服务状态监控</span>
        <span>© {{ currentYear }} XFDemo</span>
      </div>
    </div>
  </footer>
</template>

<style scoped>
.footer {
  margin-top: var(--spacing-2xl);
  border-top: 1px solid var(--color-gray-200);
  background: #eef1ef;
}

.footer__container {
  min-height: 96px;
  display: grid;
  grid-template-columns: minmax(210px, 1fr) auto minmax(210px, 1fr);
  align-items: center;
  gap: var(--spacing-xl);
}

.footer__brand,
.footer__brand > span:last-child,
.footer__meta,
.footer__status { display: flex; align-items: center; }

.footer__brand { gap: 10px; }
.footer__brand > span:last-child { align-items: flex-start; flex-direction: column; line-height: 1.35; }
.footer__brand strong { font-size: var(--font-size-sm); }
.footer__brand small { color: var(--text-tertiary); font-size: 11px; }

.footer__mark {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border: 1px solid #e5c6c3;
  border-radius: var(--radius-md);
  color: var(--color-primary);
  background: #fff8f7;
}

.footer__nav { display: flex; align-items: center; gap: 22px; }
.footer__nav a { color: var(--text-secondary); font-size: 13px; font-weight: 600; }
.footer__nav a:hover { color: var(--color-primary-dark); }

.footer__meta { justify-content: flex-end; gap: 16px; color: var(--text-tertiary); font-size: 12px; }
.footer__status { gap: 6px; color: var(--color-success); }

@media (max-width: 820px) {
  .footer__container { grid-template-columns: 1fr auto; padding-top: 18px; padding-bottom: 18px; }
  .footer__nav { display: none; }
}

@media (max-width: 520px) {
  .footer__container { grid-template-columns: 1fr; gap: 12px; }
  .footer__meta { justify-content: flex-start; }
}
</style>
