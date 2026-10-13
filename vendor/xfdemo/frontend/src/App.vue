<script setup>
import { RouterView, useRoute } from 'vue-router'
import AppHeader from '@/components/AppHeader.vue'
import AppFooter from '@/components/AppFooter.vue'

const route = useRoute()
</script>

<template>
  <div class="app">
    <AppHeader v-if="!route.meta.authLayout" />
    <main class="main" :class="{ 'main--auth': route.meta.authLayout }">
      <RouterView v-slot="{ Component }">
        <Transition name="page" mode="out-in">
          <component :is="Component" />
        </Transition>
      </RouterView>
    </main>
    <AppFooter v-if="route.path !== '/knowledge-graph' && !route.meta.authLayout" />
  </div>
</template>

<style scoped>
.app {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.main {
  flex: 1;
}

.main--auth {
  display: flex;
}
</style>
