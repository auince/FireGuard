<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { LogOut, Menu, ShieldCheck, UserRound, X } from 'lucide-vue-next'
import { authActions, authState } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const isScrolled = ref(false)
const moreOpen = ref(false)
const accountOpen = ref(false)
const mobileOpen = ref(false)

const primaryItems = [
  { path: '/', label: '首页' },
  { path: '/inspect', label: '智能检测' },
  { path: '/pipes-counting', label: '型材计数' },
  { path: '/history', label: '检测历史' },
  { path: '/dataset', label: '数据集' }
]

const secondaryItems = [
  { path: '/regulations', label: '法规库' },
  { path: '/multimodal-search', label: '多模态检索' },
  { path: '/knowledge-graph', label: '知识图谱' }
]

const isSecondaryActive = computed(() => secondaryItems.some((item) => item.path === route.path))
const userInitial = computed(() => {
  const name = authState.user?.displayName || authState.user?.username || '用户'
  return name.slice(0, 1).toUpperCase()
})

const handleScroll = () => { isScrolled.value = window.scrollY > 12 }
const closeNavigation = () => { moreOpen.value = false; mobileOpen.value = false }

watch(() => route.path, closeNavigation)

onMounted(() => window.addEventListener('scroll', handleScroll, { passive: true }))
onUnmounted(() => window.removeEventListener('scroll', handleScroll))

const handleLogout = async () => {
  accountOpen.value = false
  await authActions.logout()
  await router.replace('/login')
}
</script>

<template>
  <header class="header" :class="{ 'header--scrolled': isScrolled, 'header--mobile-open': mobileOpen }">
    <div class="header__container container">
      <router-link to="/" class="header__logo" aria-label="消防智检">
        <span class="header__logo-icon"><ShieldCheck :size="20" /></span>
        <span class="header__logo-copy">
          <strong>消防智检</strong>
          <small>XF INSPECTION</small>
        </span>
      </router-link>

      <nav class="header__nav" aria-label="主导航">
        <router-link
          v-for="item in primaryItems"
          :key="item.path"
          :to="item.path"
          class="header__nav-link"
          :class="{ 'header__nav-link--active': route.path === item.path }"
        >{{ item.label }}</router-link>

        <div
          class="header__more"
          :class="{ 'header__more--active': isSecondaryActive, 'header__more--open': moreOpen }"
          @mouseenter="moreOpen = true"
          @mouseleave="moreOpen = false"
        >
          <button class="header__more-button" type="button" :aria-expanded="moreOpen" @click.stop="moreOpen = !moreOpen">更多</button>
          <div class="header__more-menu">
            <router-link
              v-for="item in secondaryItems"
              :key="item.path"
              :to="item.path"
              class="header__more-link"
              :class="{ 'header__more-link--active': route.path === item.path }"
            >{{ item.label }}</router-link>
          </div>
        </div>
      </nav>

      <div class="header__actions">
        <button class="header__mobile-button" type="button" :aria-expanded="mobileOpen" aria-label="打开导航" @click="mobileOpen = !mobileOpen">
          <X v-if="mobileOpen" :size="20" />
          <Menu v-else :size="20" />
        </button>

        <div class="header__account" @mouseleave="accountOpen = false">
          <button type="button" class="header__account-button" :aria-expanded="accountOpen" aria-label="账户菜单" @click="accountOpen = !accountOpen">
            <span class="header__avatar">{{ userInitial }}</span>
            <span class="header__account-name">{{ authState.user?.displayName || authState.user?.username }}</span>
          </button>
          <div class="header__account-menu" :class="{ 'header__account-menu--open': accountOpen }">
            <div class="header__account-summary">
              <UserRound :size="18" />
              <span>
                <strong>{{ authState.user?.displayName || authState.user?.username }}</strong>
                <small>{{ authState.user?.email }}</small>
              </span>
              <em v-if="authState.user?.role === 'admin'" class="header__role"><ShieldCheck :size="12" />管理员</em>
            </div>
            <button type="button" class="header__logout" @click="handleLogout"><LogOut :size="17" />退出登录</button>
          </div>
        </div>
      </div>
    </div>

    <nav v-if="mobileOpen" class="mobile-nav" aria-label="移动端导航">
      <div class="container mobile-nav__grid">
        <router-link v-for="item in primaryItems" :key="item.path" :to="item.path" :class="{ active: route.path === item.path }">{{ item.label }}</router-link>
        <router-link v-for="item in secondaryItems" :key="item.path" :to="item.path" :class="{ active: route.path === item.path }">{{ item.label }}</router-link>
      </div>
    </nav>
  </header>
</template>

<style scoped>
.header {
  position: fixed;
  inset: 0 0 auto;
  z-index: 1000;
  height: 68px;
  border-bottom: 1px solid rgba(226, 230, 229, .9);
  background: rgba(255, 255, 255, .94);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
  transition: box-shadow var(--transition-fast), background var(--transition-fast);
}
.header--scrolled { background: rgba(255, 255, 255, .98); box-shadow: 0 4px 18px rgba(28, 38, 35, .055); }
.header__container { height: 100%; display: flex; align-items: center; justify-content: space-between; gap: 24px; }
.header__logo { display: flex; align-items: center; gap: 10px; flex: 0 0 auto; }
.header__logo-icon { width: 36px; height: 36px; display: grid; place-items: center; border-radius: var(--radius-md); color: #fff; background: var(--color-primary); }
.header__logo-copy { display: grid; line-height: 1.15; }
.header__logo-copy strong { font-size: 15px; }
.header__logo-copy small { margin-top: 3px; color: var(--text-tertiary); font-size: 8px; font-weight: 700; }

.header__nav { flex: 1; display: flex; justify-content: center; align-items: center; gap: 4px; min-width: 0; }
.header__nav-link, .header__more-button, .header__more-link { color: var(--text-secondary); font-size: 13px; font-weight: 650; white-space: nowrap; }
.header__nav-link, .header__more-button { min-height: 36px; display: inline-flex; align-items: center; padding: 0 12px; border-radius: var(--radius-md); transition: color var(--transition-fast), background var(--transition-fast); }
.header__nav-link:hover, .header__more-button:hover { color: var(--text-primary); background: var(--color-gray-50); }
.header__nav-link--active, .header__more--active .header__more-button { color: var(--color-primary-dark); background: var(--color-primary-subtle); }
.header__more { position: relative; }
.header__more::after { content: ''; position: absolute; top: 100%; left: -12px; right: -12px; height: 10px; }
.header__more-menu { position: absolute; top: calc(100% + 8px); right: -8px; display: grid; min-width: 164px; padding: 6px; border: 1px solid var(--color-gray-200); border-radius: var(--radius-lg); background: #fff; box-shadow: var(--shadow-lg); opacity: 0; pointer-events: none; transform: translateY(-5px); transition: opacity var(--transition-fast), transform var(--transition-fast); }
.header__more--open .header__more-menu, .header__more:hover .header__more-menu, .header__more:focus-within .header__more-menu { opacity: 1; pointer-events: auto; transform: translateY(0); }
.header__more-link { padding: 9px 11px; border-radius: var(--radius-md); }
.header__more-link:hover, .header__more-link--active { color: var(--color-primary-dark); background: var(--color-primary-subtle); }

.header__actions { display: flex; align-items: center; gap: 8px; flex: 0 0 auto; }
.header__mobile-button { width: 38px; height: 38px; display: none; place-items: center; border: 1px solid var(--color-gray-200); border-radius: var(--radius-md); color: var(--text-secondary); background: #fff; }
.header__account { position: relative; }
.header__account-button { min-height: 38px; max-width: 148px; display: flex; align-items: center; gap: 8px; padding: 3px 10px 3px 4px; border: 1px solid var(--color-gray-200); border-radius: var(--radius-md); color: var(--text-primary); background: #fff; }
.header__avatar { width: 28px; height: 28px; flex: 0 0 28px; display: grid; place-items: center; border-radius: 5px; color: var(--color-primary-dark); background: var(--color-primary-subtle); font-size: 12px; font-weight: 750; }
.header__account-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; font-weight: 650; }
.header__account-menu { position: absolute; top: calc(100% + 9px); right: 0; width: 270px; padding: 7px; border: 1px solid var(--color-gray-200); border-radius: var(--radius-lg); background: #fff; box-shadow: var(--shadow-lg); opacity: 0; pointer-events: none; transform: translateY(-5px); transition: opacity var(--transition-fast), transform var(--transition-fast); }
.header__account-menu--open, .header__account:focus-within .header__account-menu { opacity: 1; pointer-events: auto; transform: translateY(0); }
.header__account-summary { position: relative; display: grid; grid-template-columns: 20px minmax(0,1fr); gap: 9px; padding: 10px; border-bottom: 1px solid var(--color-gray-100); color: var(--text-secondary); }
.header__account-summary > span { min-width: 0; display: grid; }
.header__account-summary strong, .header__account-summary small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.header__account-summary strong { color: var(--text-primary); font-size: 13px; }
.header__account-summary small { font-size: 11px; }
.header__role { grid-column: 2; justify-self: start; display: inline-flex; align-items: center; gap: 3px; margin-top: 3px; padding: 2px 5px; border-radius: 4px; color: var(--color-primary-dark); background: var(--color-primary-subtle); font-size: 10px; font-style: normal; font-weight: 650; }
.header__logout { width: 100%; display: flex; align-items: center; gap: 8px; margin-top: 5px; padding: 9px 10px; border-radius: var(--radius-md); color: var(--color-primary-dark); font-size: 12px; font-weight: 650; }
.header__logout:hover { background: var(--color-primary-subtle); }

.mobile-nav { display: none; border-top: 1px solid var(--color-gray-200); border-bottom: 1px solid var(--color-gray-200); background: rgba(255,255,255,.98); box-shadow: var(--shadow-md); }
.mobile-nav__grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px; padding-top: 12px; padding-bottom: 14px; }
.mobile-nav a { min-height: 42px; display: flex; align-items: center; padding: 0 13px; border-radius: var(--radius-md); color: var(--text-secondary); font-size: 13px; font-weight: 650; }
.mobile-nav a.active { color: var(--color-primary-dark); background: var(--color-primary-subtle); }

@media (max-width: 1040px) {
  .header__nav { gap: 0; }
  .header__nav-link, .header__more-button { padding: 0 9px; }
  .header__account-name { display: none; }
  .header__account-button { padding-right: 4px; }
}

@media (max-width: 860px) {
  .header__nav { display: none; }
  .header__mobile-button { display: grid; }
  .header--mobile-open { height: auto; }
  .mobile-nav { display: block; }
}

@media (max-width: 430px) {
  .header__logo-copy small { display: none; }
  .header__logo-icon { width: 34px; height: 34px; }
}
</style>
