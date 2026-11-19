<script setup lang="ts">
import { Globe } from 'lucide-vue-next'
import { useLocale } from '@/i18n'
import { useI18n } from 'vue-i18n'

defineProps<{ dark?: boolean; compact?: boolean }>()

const { locale, toggleLocale } = useLocale()
const { t } = useI18n()

const localeOptions = [
  { value: 'zh-CN', label: '中文', shortLabel: '中' },
  { value: 'en-US', label: 'English', shortLabel: 'EN' },
] as const
</script>

<template>
  <div
    class="inline-flex items-center gap-0.5 rounded border p-0.5"
    :class="dark ? 'border-white/20 bg-white/5' : 'border-slate-200 bg-white'"
    :aria-label="t('locale.switchLabel')"
    role="group"
  >
    <span v-if="!compact" class="hidden pl-2 text-slate-500 sm:inline-flex">
      <Globe class="h-4 w-4" />
    </span>
    <button
      v-for="option in localeOptions"
      :key="option.value"
      type="button"
      class="rounded-sm px-2 py-1 text-[11px] font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
      :aria-pressed="locale === option.value"
      :aria-label="option.label"
      :class="locale === option.value ? 'bg-primary text-primary-foreground' : dark ? 'text-slate-200 hover:bg-white/10' : 'text-slate-600 hover:bg-slate-100'"
      @click="toggleLocale(option.value)"
    >
      <span :class="compact ? '' : 'sm:hidden'">{{ option.shortLabel }}</span>
      <span v-if="!compact" class="hidden sm:inline">{{ option.label }}</span>
    </button>
  </div>
</template>
