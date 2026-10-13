<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ClipboardList, AlertTriangle, Clock, CheckCircle2, XCircle, FileText, Shield, TrendingUp } from 'lucide-vue-next'
import { authState } from '@/stores/auth'
import { request, statusLabel } from '@/api'

const router = useRouter()
const reports = ref([])
const loading = ref(true)
const error = ref('')

const stats = computed(() => {
  if (!reports.value.length) return { pending: 0, running: 0, failed: 0, completed: 0 }
  return {
    pending: reports.value.filter(r => ['pending','blocked'].includes(r.status)).length,
    running: reports.value.filter(r => ['queued','running'].includes(r.status)).length,
    failed: reports.value.filter(r => r.status === 'failed').length,
    completed: reports.value.filter(r => ['approved','rejected'].includes(r.status)).length
  }
})

const recentReports = computed(() => reports.value.slice(0, 5))

onMounted(async () => {
  try {
    const data = await request('/reports')
    reports.value = data.reports || []
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="dashboard">
    <div class="container dashboard__container">
      <header class="dashboard__header">
        <div>
          <h1>工作台</h1>
          <p>{{ authState.user?.displayName || authState.user?.username }} · {{ { inspector: '巡检员', reviewer: '复核员', admin: '管理员' }[authState.user?.role] }}</p>
        </div>
        <router-link to="/inspect" class="btn btn-primary">
          <ClipboardList :size="18" />
          提交巡检
        </router-link>
      </header>

      <section v-if="loading" class="dashboard__loading">
        <p>加载中...</p>
      </section>

      <section v-else-if="error" class="message error">
        {{ error }}
      </section>

      <template v-else>
        <p class="muted">统计范围：最近返回的 {{ reports.length }} 条巡检记录</p><div class="stats-grid">
          <article class="stat-card stat-card--pending">
            <span class="stat-card__icon"><Clock :size="22" /></span>
            <div class="stat-card__content">
              <span class="stat-card__value">{{ stats.pending }}</span>
              <span class="stat-card__label">待审核</span>
            </div>
          </article>

          <article class="stat-card stat-card--running">
            <span class="stat-card__icon"><TrendingUp :size="22" /></span>
            <div class="stat-card__content">
              <span class="stat-card__value">{{ stats.running }}</span>
              <span class="stat-card__label">执行中</span>
            </div>
          </article>

          <article class="stat-card stat-card--failed">
            <span class="stat-card__icon"><XCircle :size="22" /></span>
            <div class="stat-card__content">
              <span class="stat-card__value">{{ stats.failed }}</span>
              <span class="stat-card__label">失败</span>
            </div>
          </article>

          <article class="stat-card stat-card--completed">
            <span class="stat-card__icon"><CheckCircle2 :size="22" /></span>
            <div class="stat-card__content">
              <span class="stat-card__value">{{ stats.completed }}</span>
              <span class="stat-card__label">已完成</span>
            </div>
          </article>
        </div>

        <section class="dashboard__section">
          <div class="section-heading">
            <h2>最近报告</h2>
            <router-link to="/history" class="link-secondary">查看全部</router-link>
          </div>

          <div v-if="!recentReports.length" class="empty">
            <FileText :size="40" />
            <p>暂无报告</p>
          </div>

          <div v-else class="report-list">
            <router-link
              v-for="report in recentReports"
              :key="report.id"
              class="report-item"
              :to="`/reports/${report.id}`"
            >
              <div class="report-item__header">
                <h3>{{ report.query || '消防设施巡检' }}</h3>
                <span
                  class="report-item__status"
                  :class="`report-item__status--${report.status}`"
                >
                  {{ statusLabel(report.status) }}
                </span>
              </div>
              <p class="report-item__meta">
                提交时间：{{ new Date(report.created_at * 1000).toLocaleString('zh-CN') }}
              </p>
            </router-link>
          </div>
        </section>

        <section class="dashboard__section">
          <div class="section-heading">
            <h2>快速入口</h2>
          </div>
          <div class="action-grid">
            <router-link to="/inspect" class="action-card">
              <ClipboardList :size="24" />
              <span>巡检提交</span>
            </router-link>
            <router-link v-if="['reviewer','admin'].includes(authState.user?.role)" to="/review" class="action-card">
              <Shield :size="24" />
              <span>人工审核</span>
            </router-link>
            <router-link to="/history" class="action-card">
              <FileText :size="24" />
              <span>报告历史</span>
            </router-link>
            <router-link to="/regulations" class="action-card">
              <AlertTriangle :size="24" />
              <span>法规库</span>
            </router-link>
          </div>
        </section>
      </template>
    </div>
  </div>
</template>

<style scoped>
.dashboard {
  min-height: 100vh;
  padding: 100px 0 48px;
  background: var(--bg-secondary);
}

.dashboard__container {
  max-width: 1240px;
}

.dashboard__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 32px;
}

.dashboard__header h1 {
  margin: 0 0 6px;
  font-size: 32px;
  font-weight: 700;
  letter-spacing: -0.5px;
}

.dashboard__header p {
  margin: 0;
  color: var(--text-secondary);
  font-size: 14px;
}

.dashboard__loading {
  padding: 60px 20px;
  text-align: center;
  color: var(--text-secondary);
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 16px;
  margin-bottom: 40px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 24px;
  border: 1px solid var(--color-gray-200);
  border-radius: var(--radius-lg);
  background: #fff;
  box-shadow: var(--shadow-sm);
}

.stat-card__icon {
  width: 48px;
  height: 48px;
  display: grid;
  place-items: center;
  border-radius: var(--radius-md);
  flex: 0 0 48px;
}

.stat-card--pending .stat-card__icon {
  background: #fff4e4;
  color: #b97822;
}

.stat-card--running .stat-card__icon {
  background: #e8f4ff;
  color: #4d7084;
}

.stat-card--failed .stat-card__icon {
  background: #fff1ed;
  color: #c84b45;
}

.stat-card--completed .stat-card__icon {
  background: #edf7f0;
  color: #2f8464;
}

.stat-card__content {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat-card__value {
  font-size: 28px;
  font-weight: 700;
  line-height: 1;
  color: var(--text-primary);
}

.stat-card__label {
  font-size: 13px;
  color: var(--text-secondary);
}

.dashboard__section {
  margin-bottom: 40px;
}

.section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
}

.section-heading h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 650;
}

.link-secondary {
  color: var(--color-primary-dark);
  font-size: 13px;
  font-weight: 600;
}

.link-secondary:hover {
  text-decoration: underline;
}

.empty {
  padding: 60px 20px;
  text-align: center;
  color: var(--text-secondary);
  border: 1px solid var(--color-gray-200);
  border-radius: var(--radius-lg);
  background: #fff;
}

.empty svg {
  margin: 0 auto 12px;
  color: var(--color-gray-400);
}

.empty p {
  margin: 0;
  font-size: 14px;
}

.report-list {
  display: grid;
  gap: 12px;
}

.report-item {
  padding: 20px;
  border: 1px solid var(--color-gray-200);
  border-radius: var(--radius-lg);
  background: #fff;
  cursor: pointer;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.report-item:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-md);
}

.report-item__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 10px;
}

.report-item h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.report-item__status {
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 650;
  white-space: nowrap;
  flex: 0 0 auto;
}

.report-item__status--pending_review {
  background: #fff4e4;
  color: #b97822;
}

.report-item__status--processing {
  background: #e8f4ff;
  color: #4d7084;
}

.report-item__status--failed {
  background: #fff1ed;
  color: #c84b45;
}

.report-item__status--completed {
  background: #edf7f0;
  color: #2f8464;
}

.report-item__meta {
  margin: 0;
  color: var(--text-secondary);
  font-size: 13px;
}

.action-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 14px;
}

.action-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 32px 20px;
  border: 1px solid var(--color-gray-200);
  border-radius: var(--radius-lg);
  background: #fff;
  color: var(--text-primary);
  text-align: center;
  transition: border-color var(--transition-fast), background var(--transition-fast);
}

.action-card:hover {
  border-color: var(--color-primary);
  background: var(--color-primary-subtle);
}

.action-card svg {
  color: var(--color-primary);
}

.action-card span {
  font-size: 14px;
  font-weight: 600;
}

@media (max-width: 768px) {
  .dashboard {
    padding: 90px 0 32px;
  }

  .dashboard__header {
    flex-direction: column;
    gap: 16px;
  }

  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
  }

  .stat-card {
    padding: 18px;
    gap: 12px;
  }

  .stat-card__icon {
    width: 40px;
    height: 40px;
    flex: 0 0 40px;
  }

  .stat-card__value {
    font-size: 24px;
  }

  .action-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
