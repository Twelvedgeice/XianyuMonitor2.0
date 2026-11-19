<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import TheHeader from '@/components/layout/TheHeader.vue'
import TheSidebar from '@/components/layout/TheSidebar.vue'
import { useMobileNav } from '@/composables/useMobileNav'

const { isMobileNavOpen, closeMobileNav } = useMobileNav()
const { t } = useI18n()
const route = useRoute()
const isDashboard = computed(() => route.name === 'Dashboard')
</script>

<template>
  <div class="relative min-h-screen w-full flex flex-col bg-background selection:bg-primary/15">
    <a
      href="#main-content"
      class="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[120] focus:rounded-lg focus:bg-primary focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-primary-foreground"
    >
      {{ t('common.skipToContent') }}
    </a>

    <!-- Header -->
    <TheHeader />

    <transition name="mobile-nav">
      <div v-if="isMobileNavOpen" class="fixed inset-x-0 bottom-0 top-16 z-[90] lg:hidden" @keydown.esc="closeMobileNav">
        <button
          type="button"
          class="absolute inset-0 bg-slate-950/25 backdrop-blur-[2px]"
          :aria-label="t('common.close')"
          @click="closeMobileNav"
        />
        <aside id="monitor-menu" class="relative h-full w-72 max-w-[85vw] overflow-y-auto border-r border-slate-200 bg-white p-4 shadow-xl">
          <TheSidebar @navigate="closeMobileNav" />
        </aside>
      </div>
    </transition>

    <main
      id="main-content"
      tabindex="-1"
      class="flex-1 focus:outline-none"
      :class="isDashboard ? '' : 'mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8'"
    >
      <RouterView v-slot="{ Component }">
        <transition name="page" mode="out-in">
          <component :is="Component" />
        </transition>
      </RouterView>
    </main>
  </div>
</template>

<style scoped>
.page-enter-active,
.page-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.page-enter-from {
  opacity: 0;
  transform: translateY(10px);
}

.page-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}

.mobile-nav-enter-active,
.mobile-nav-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.mobile-nav-enter-from,
.mobile-nav-leave-to {
  opacity: 0;
  transform: translateX(-12px);
}

@media (prefers-reduced-motion: reduce) {
  .page-enter-active,
  .page-leave-active,
  .mobile-nav-enter-active,
  .mobile-nav-leave-active {
    transition: none;
  }

  .page-enter-from,
  .page-leave-to,
  .mobile-nav-enter-from,
  .mobile-nav-leave-to {
    opacity: 1;
    transform: none;
  }
}
</style>
