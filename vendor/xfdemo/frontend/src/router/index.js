import { createRouter, createWebHistory } from 'vue-router'
import { authActions, authState } from '@/stores/auth'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/AuthView.vue'),
    meta: { public: true, authLayout: true }
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/views/AuthView.vue'),
    meta: { public: true, authLayout: true }
  },
  {
    path: '/',
    name: 'Home',
    component: () => import('@/views/AboutView.vue')
  },
  {
    path: '/inspect',
    name: 'Inspect',
    component: () => import('@/views/InspectView.vue')
  },
  {
    path: '/pipes-counting',
    name: 'PipesCounting',
    component: () => import('@/views/PipesCountingView.vue')
  },
  {
    path: '/dataset',
    name: 'Dataset',
    component: () => import('@/views/DatasetView.vue')
  },
  {
    path: '/knowledge-graph',
    name: 'KnowledgeGraph',
    component: () => import('@/views/KnowledgeGraphView.vue')
  },
  {
    path: '/regulations',
    name: 'RegulationKnowledge',
    component: () => import('@/views/RegulationKnowledgeView.vue')
  },
  {
    path: '/multimodal-search',
    name: 'MultimodalSearch',
    component: () => import('@/views/MultimodalSearchView.vue')
  },
  {
    path: '/history',
    name: 'History',
    component: () => import('@/views/HistoryView.vue')
  },
  {
    path: '/monitor',
    name: 'Monitor',
    component: () => import('@/views/MonitorView.vue')
  },
  {
    path: '/about',
    redirect: '/'
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach(async (to) => {
  await authActions.initialize()

  if (!to.meta.public && !authState.user) {
    return { name: 'Login', query: { redirect: to.fullPath } }
  }
  if (to.meta.authLayout && authState.user) {
    return { name: 'Home' }
  }
  return true
})

export default router
