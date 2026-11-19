<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { Bell, CircleHelp, Menu, ScanLine, X } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import LocaleToggle from '@/components/layout/LocaleToggle.vue'
import TheSidebar from '@/components/layout/TheSidebar.vue'
import { useMobileNav } from '@/composables/useMobileNav'

const router = useRouter()
const { t } = useI18n()
const { isMobileNavOpen, toggleMobileNav } = useMobileNav()
</script>

<template>
  <header class="monitor-header sticky top-0 z-[100] border-b border-white/10 bg-[#151c26] text-white">
    <div class="mx-auto flex min-h-16 max-w-7xl items-center justify-between gap-2 px-4 sm:gap-4 sm:px-6 lg:px-8">
      <RouterLink
        to="/dashboard"
        class="flex min-w-0 items-center gap-2.5 rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
        :aria-label="t('app.name') + ' · ' + t('header.goHome')"
      >
        <span class="hidden h-8 w-8 shrink-0 items-center justify-center rounded border border-white/30 text-white sm:flex">
          <ScanLine class="h-5 w-5" aria-hidden="true" />
        </span>
        <span class="text-sm font-semibold leading-tight tracking-tight sm:whitespace-nowrap sm:text-base">
          {{ t('app.name') }}
        </span>
      </RouterLink>

      <TheSidebar horizontal class="hidden min-h-16 min-w-0 lg:flex" />

      <div class="flex shrink-0 items-center gap-1 sm:gap-2">
        <LocaleToggle dark compact />
        <Button
          variant="ghost"
          size="icon"
          class="h-8 w-8 rounded-sm text-slate-200 hover:bg-white/10 hover:text-white focus-visible:ring-sky-300 focus-visible:ring-offset-[#151c26]"
          :aria-label="t('header.openNotifications')"
          @click="router.push({ name: 'Settings', query: { tab: 'notifications' } })"
        >
          <Bell aria-hidden="true" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          class="h-8 w-8 rounded-sm text-slate-200 hover:bg-white/10 hover:text-white focus-visible:ring-sky-300 focus-visible:ring-offset-[#151c26]"
          :aria-label="t('header.openPrompts')"
          @click="router.push({ name: 'Settings', query: { tab: 'prompts' } })"
        >
          <CircleHelp aria-hidden="true" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          class="h-8 w-8 rounded-sm text-slate-200 hover:bg-white/10 hover:text-white focus-visible:ring-sky-300 focus-visible:ring-offset-[#151c26] lg:hidden"
          :aria-label="t(isMobileNavOpen ? 'common.close' : 'header.openNavigation')"
          :aria-expanded="isMobileNavOpen"
          aria-controls="monitor-menu"
          @click="toggleMobileNav"
        >
          <X v-if="isMobileNavOpen" aria-hidden="true" />
          <Menu v-else aria-hidden="true" />
        </Button>
      </div>
    </div>
  </header>
</template>
