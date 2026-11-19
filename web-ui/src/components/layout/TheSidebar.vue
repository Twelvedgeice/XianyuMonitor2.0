<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { LayoutDashboard, ListTodo, Users, Layers, Search, Terminal, Settings2 } from 'lucide-vue-next'
import { useWebSocket } from '@/composables/useWebSocket'
import { useI18n } from 'vue-i18n'

defineProps<{ horizontal?: boolean }>()

const emit = defineEmits<{ navigate: [] }>()
const { isConnected } = useWebSocket()
const { t } = useI18n()
const navItems = computed(() => [
  { to: '/dashboard', label: t('routes.dashboard'), icon: LayoutDashboard },
  { to: '/tasks', label: t('routes.tasks'), icon: ListTodo },
  { to: '/accounts', label: t('routes.accounts'), icon: Users },
  { to: '/results', label: t('routes.results'), icon: Layers },
  { to: '/price-survey', label: t('routes.priceSurvey'), icon: Search },
  { to: '/logs', label: t('routes.logs'), icon: Terminal },
  { to: '/settings', label: t('routes.settings'), icon: Settings2 },
])
</script>

<template>
  <nav :class="horizontal ? 'items-stretch gap-1' : 'space-y-1'">
    <RouterLink
      v-for="item in navItems"
      :key="item.to"
      :to="item.to"
      class="flex items-center gap-3 whitespace-nowrap text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-sky-400"
      :class="horizontal
        ? 'border-b-2 border-transparent px-2.5 text-slate-300 hover:border-white/25 hover:text-white aria-[current=page]:border-[#6fafff] aria-[current=page]:text-white'
        : 'rounded border-l-2 border-transparent px-3 py-3 text-slate-700 hover:bg-slate-100 aria-[current=page]:border-primary aria-[current=page]:bg-blue-50 aria-[current=page]:text-primary'"
      @click="emit('navigate')"
    >
      <component :is="item.icon" v-if="!horizontal" class="h-4 w-4 shrink-0" aria-hidden="true" />
      {{ item.label }}
    </RouterLink>

    <div v-if="!horizontal" class="mt-6 border-t border-slate-200 px-3 pt-4 text-xs text-slate-600">
      <span class="mr-2 inline-block h-2 w-2 rounded-full" :class="isConnected ? 'bg-emerald-500' : 'bg-amber-500'" aria-hidden="true" />
      {{ t(isConnected ? 'sidebar.backendConnected' : 'sidebar.backendConnecting') }}
    </div>
  </nav>
</template>
