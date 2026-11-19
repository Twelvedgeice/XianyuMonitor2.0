<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useDashboard } from '@/composables/useDashboard'
import { useAppearance } from '@/composables/useAppearance'
import { useWebSocket } from '@/composables/useWebSocket'
import DashboardTaskSearch from '@/components/layout/DashboardTaskSearch.vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import Badge from '@/components/ui/badge/Badge.vue'
import PriceTrendChart from '@/components/results/PriceTrendChart.vue'
import { formatNumber, formatRelativeTimeFromNow } from '@/i18n'
import {
  Activity,
  ArrowRight,
  Compass,
  Plus,
  NotebookPen,
  Ruler,
  Search,
  Sparkles,
  Target,
  Zap,
} from 'lucide-vue-next'

const router = useRouter()
const { appearance, appearances, selectAppearance } = useAppearance()
const { t } = useI18n()
const { isConnected } = useWebSocket()
const {
  focusInsights,
  focusTask,
  suggestion,
  stats,
  activities,
  isLoading,
  error,
} = useDashboard()

const statCards = computed(() => [
  {
    label: t('dashboard.stats.activeTasks'),
    value: String(stats.value.enabledTasks),
    detail: t('dashboard.stats.runningCount', { count: stats.value.runningTasks }),
    icon: Activity,
  },
  {
    label: t('dashboard.stats.scannedItems'),
    value: formatNumber(stats.value.scannedItems),
    detail: t('dashboard.stats.resultFiles', { count: stats.value.resultFiles }),
    icon: Search,
  },
  {
    label: t('dashboard.stats.recommendedItems'),
    value: String(stats.value.recommendedItems),
    detail: t('dashboard.stats.recommendedBreakdown', {
      ai: stats.value.aiRecommendedItems,
      keyword: stats.value.keywordRecommendedItems,
    }),
    icon: Target,
  },
  {
    label: t('dashboard.stats.monitoredTasks'),
    value: String(stats.value.totalTasks),
    detail: t('dashboard.stats.showAllTasks'),
    icon: Compass,
  },
])

const focusTitle = computed(() => focusTask.value?.task_name || t('dashboard.focus.defaultTitle'))
const focusMeta = computed(() => {
  if (!focusTask.value) return t('dashboard.focus.empty')
  const keyword = focusTask.value.keyword || t('dashboard.focus.missingKeyword')
  const count = focusTask.value.total_items
  return t('dashboard.focus.meta', { keyword, count })
})

const insightCards = computed(() => {
  const market = focusInsights.value?.market_summary
  const history = focusInsights.value?.history_summary
  return [
    {
      label: t('results.insights.currentAvg'),
      value: market?.avg_price ? `¥${market.avg_price}` : '—',
      hint: market
        ? t('results.insights.sampleCount', { count: market.sample_count })
        : t('results.grid.empty'),
    },
    {
      label: t('results.insights.historyAvg'),
      value: history?.avg_price ? `¥${history.avg_price}` : '—',
      hint: history
        ? t('results.insights.uniqueItems', { count: history.unique_items })
        : t('results.insights.noSnapshot'),
    },
    {
      label: t('results.insights.currentMin'),
      value: market?.min_price ? `¥${market.min_price}` : '—',
      hint: market?.max_price
        ? t('results.insights.highestPrice', { price: market.max_price })
        : t('results.insights.noRange'),
    },
  ]
})

function goCreateTask() {
  router.push({
    name: 'Tasks',
    query: { create: '1' },
  })
}

function openSuggestion() {
  router.push({
    name: suggestion.value.routeName,
    query: suggestion.value.query,
  })
}

function openActivity(activity: { filename: string | null; type: string }) {
  if (activity.filename) {
    router.push({ name: 'Results', query: { file: activity.filename } })
    return
  }
  if (activity.type === 'task') {
    router.push({ name: 'Tasks' })
    return
  }
  router.push({ name: 'Dashboard' })
}
</script>

<template>
  <div class="monitor-dashboard">
    <section class="dashboard-hero relative isolate bg-[#171e28] text-white">
      <div class="cover-toolbar mx-auto flex max-w-7xl justify-end px-4 pt-4 sm:px-6 lg:px-8">
        <div class="cover-switch" role="group" :aria-label="t('dashboard.appearance.label')">
          <button v-for="option in appearances" :key="option" type="button"
            :aria-pressed="appearance === option" @click="selectAppearance(option)">
            <component :is="option === 'journal' ? NotebookPen : Ruler" :size="15" aria-hidden="true" />
            {{ t('dashboard.appearance.' + option) }}
          </button>
        </div>
      </div>
      <div class="cover-sheet mx-auto flex min-h-[270px] max-w-7xl flex-col justify-center px-4 py-9 sm:min-h-[280px] sm:px-6 lg:min-h-[310px] lg:px-8">
        <h1 class="cover-title max-w-lg text-4xl font-semibold tracking-tight sm:text-5xl lg:text-6xl">
          {{ t(appearance === 'journal' ? 'dashboard.journalTitle' : 'dashboard.title') }}
        </h1>
        <p class="cover-description mt-4 max-w-sm text-sm leading-relaxed text-slate-200 sm:text-base">
          {{ t('dashboard.description') }}
        </p>
        <div class="cover-actions mt-7 flex flex-wrap items-center gap-3">
          <Button class="h-11 rounded gap-2 bg-[#2356a6] px-4 hover:bg-[#2b64b7] focus-visible:ring-sky-300 focus-visible:ring-offset-[#171e28]" @click="goCreateTask">
            <Plus aria-hidden="true" />
            {{ t('dashboard.createTask') }}
          </Button>
          <RouterLink
            to="/results"
            class="inline-flex h-11 items-center gap-2 rounded border border-white/45 px-4 text-sm font-medium text-white transition-colors hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
          >
            {{ t('routes.results') }}
            <ArrowRight class="h-4 w-4" aria-hidden="true" />
          </RouterLink>
        </div>
      </div>
    </section>

    <section :aria-label="t('dashboard.title')" class="dashboard-stats border-y border-white/10 bg-[#142338] text-white">
      <dl class="mx-auto grid max-w-7xl grid-cols-2 px-4 sm:px-6 lg:grid-cols-4 lg:px-8">
        <div
          v-for="(stat, index) in statCards"
          :key="stat.label"
          class="flex min-w-0 flex-col gap-2 border-white/15 px-3 py-4 sm:flex-row sm:gap-3 sm:px-4 lg:py-5"
          :class="[
            index % 2 === 1 && 'border-l',
            index > 1 && 'border-t lg:border-t-0',
            index === 2 && 'lg:border-l',
            index === 0 && 'lg:pl-0'
          ]"
        >
          <component :is="stat.icon" class="mt-1 h-5 w-5 shrink-0 text-blue-200" aria-hidden="true" />
          <div class="min-w-0">
            <dt class="text-xs font-medium text-slate-300 sm:text-sm">{{ stat.label }}</dt>
            <dd class="mt-1 text-2xl font-semibold tabular-nums leading-none sm:text-3xl">{{ stat.value }}</dd>
            <dd class="mt-2 text-xs leading-snug text-slate-300">{{ stat.detail }}</dd>
          </div>
        </div>
      </dl>
    </section>

    <div class="mx-auto max-w-7xl space-y-5 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <DashboardTaskSearch class="max-w-md" />
        <p class="flex items-center gap-2 text-xs text-slate-600">
          <span class="h-2 w-2 rounded-full" :class="isConnected ? 'bg-emerald-600' : 'bg-amber-500'" aria-hidden="true" />
          {{ t(isConnected ? 'sidebar.backendConnected' : 'sidebar.backendConnecting') }}
        </p>
      </div>
      <div v-if="error" class="app-alert-error" role="alert">
        {{ error.message }}
      </div>

      <div class="grid grid-cols-1 items-start gap-5 lg:grid-cols-3">
        <Card class="min-w-0 rounded-md border-slate-200 bg-white shadow-none lg:col-span-2">
          <CardHeader class="flex flex-col gap-3 border-b border-slate-200 p-5 sm:flex-row sm:items-start sm:justify-between">
            <div class="min-w-0 space-y-1.5">
              <CardTitle class="text-xl font-semibold text-slate-900">{{ focusTitle }}</CardTitle>
              <p class="text-sm text-slate-600">{{ focusMeta }}</p>
            </div>
            <Badge variant="secondary" class="w-fit rounded bg-blue-50 text-blue-900">
              {{ focusTask?.latest_crawl_time
                ? t('dashboard.focus.latestUpdate', { time: formatRelativeTimeFromNow(focusTask.latest_crawl_time) })
                : t('dashboard.focus.waiting') }}
            </Badge>
          </CardHeader>
          <CardContent class="space-y-4 p-5">
            <div v-if="isLoading || !focusTask?.filename" class="rounded border border-dashed border-slate-300 px-4 py-10 text-center text-sm text-slate-600">
              {{ t(isLoading ? 'dashboard.focus.loading' : 'dashboard.focus.noResults') }}
            </div>
            <template v-else>
              <dl class="grid gap-px overflow-hidden rounded border border-slate-200 bg-slate-200 sm:grid-cols-3">
                <div v-for="card in insightCards" :key="card.label" class="bg-slate-50 p-4">
                  <dt class="text-xs font-medium text-slate-600">{{ card.label }}</dt>
                  <dd class="mt-2 text-2xl font-semibold tabular-nums text-slate-900">{{ card.value }}</dd>
                  <dd class="mt-1 text-xs text-slate-600">{{ card.hint }}</dd>
                </div>
              </dl>
              <PriceTrendChart :points="focusInsights?.daily_trend || []" />
              <div class="grid gap-2 border-t border-slate-200 pt-4 text-sm text-slate-600 sm:grid-cols-3">
                <p>
                  {{ t('dashboard.focus.currentMedian') }}
                  <span class="font-semibold text-slate-900">
                    {{ focusInsights?.market_summary.median_price ? `¥${focusInsights.market_summary.median_price}` : '—' }}
                  </span>
                </p>
                <p>
                  {{ t('dashboard.focus.historyMin') }}
                  <span class="font-semibold text-slate-900">
                    {{ focusInsights?.history_summary.min_price ? `¥${focusInsights.history_summary.min_price}` : '—' }}
                  </span>
                </p>
                <p>
                  {{ t('dashboard.focus.historyMax') }}
                  <span class="font-semibold text-slate-900">
                    {{ focusInsights?.history_summary.max_price ? `¥${focusInsights.history_summary.max_price}` : '—' }}
                  </span>
                </p>
              </div>
            </template>
          </CardContent>
        </Card>

        <div class="min-w-0 space-y-5">
          <Card class="rounded-md border-slate-200 bg-white shadow-none">
            <CardHeader class="border-b border-slate-200 p-5">
              <CardTitle class="flex items-center gap-2 text-base font-semibold text-slate-900">
                <Activity class="h-5 w-5 text-primary" aria-hidden="true" />
                {{ t('dashboard.activity.title') }}
              </CardTitle>
            </CardHeader>
            <CardContent class="p-0">
              <p v-if="activities.length === 0" class="p-5 text-sm text-slate-600">
                {{ t('dashboard.activity.empty') }}
              </p>
              <ul v-else class="divide-y divide-slate-200">
                <li v-for="activity in activities" :key="activity.id">
                  <button
                    type="button"
                    class="flex w-full items-start justify-between gap-3 p-4 text-left transition-colors hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                    @click="openActivity(activity)"
                  >
                    <div class="min-w-0">
                      <p class="truncate text-sm font-semibold text-slate-900">{{ activity.title }}</p>
                      <p class="mt-1 text-xs text-slate-600">
                        {{ activity.task_name }} · {{ formatRelativeTimeFromNow(activity.timestamp) }}
                      </p>
                      <p v-if="activity.detail" class="mt-1 truncate text-xs text-slate-600">{{ activity.detail }}</p>
                    </div>
                    <Badge variant="outline" class="shrink-0 rounded border-slate-200 text-[10px] text-slate-700">
                      {{ activity.status }}
                    </Badge>
                  </button>
                </li>
              </ul>
              <RouterLink
                to="/logs"
                class="flex items-center gap-2 border-t border-slate-200 px-4 py-3 text-xs font-semibold text-primary hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
              >
                {{ t('dashboard.activity.viewAllLogs') }}
                <ArrowRight class="h-3.5 w-3.5" aria-hidden="true" />
              </RouterLink>
            </CardContent>
          </Card>

          <section class="rounded-md border border-slate-200 bg-white p-5">
            <h2 class="flex items-center gap-2 text-base font-semibold text-slate-900">
              <Zap class="h-5 w-5 text-primary" aria-hidden="true" />
              {{ t('dashboard.suggestion.sectionTitle') }}
            </h2>
            <p class="mt-3 text-sm font-medium text-slate-800">{{ suggestion.title }}</p>
            <p class="mt-1 text-sm leading-relaxed text-slate-600">{{ suggestion.description }}</p>
            <Button variant="outline" class="mt-4 rounded border-slate-300 bg-white text-primary" @click="openSuggestion">
              <Sparkles aria-hidden="true" />
              {{ suggestion.actionLabel }}
            </Button>
          </section>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cover-switch {
  display: inline-flex;
  gap: 3px;
  padding: 3px;
  color: #fff;
  background: #1e2630;
  border: 1px solid #738293;
  border-radius: 2rem;
}
.cover-switch button {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.45rem 0.85rem;
  min-height: 36px;
  border-radius: inherit;
  font-size: 0.875rem;
  font-weight: 600;
}
.cover-switch button[aria-pressed='true'] { background: #eff4fc; color: #17283c; }
.cover-switch button:focus-visible { outline: 2px solid #fff; outline-offset: 2px; }
[data-appearance='journal'] .dashboard-hero {
  background: var(--journal-ink);
  padding-bottom: 1.5rem;
}
[data-appearance='journal'] .cover-toolbar { padding-block: 0.9rem; }
[data-appearance='journal'] .cover-switch {
  background: #332c29;
  color: #fcebd6;
  border-color: #a7836d;
}
[data-appearance='journal'] .cover-switch button[aria-pressed='true'] {
  background: #ffae81;
  color: #29211e;
}
[data-appearance='journal'] .cover-sheet {
  align-items: center;
  text-align: center;
  width: calc(100% - 2rem);
  max-width: 76rem;
  padding: clamp(1.6rem, 4vw, 4rem);
  color: var(--journal-ink);
  background-color: var(--journal-paper);
  background-image: linear-gradient(#8d7b6524 1px, transparent 1px),
    linear-gradient(90deg, #8d7b6524 1px, transparent 1px);
  background-size: 26px 26px;
  border: 7px solid var(--journal-orange);
  border-radius: 36px 32px 33px 25px;
  box-shadow: 0 5px 0 #a94f33, 0 7px 0 #171412;
}
[data-appearance='journal'] .cover-actions { justify-content: center; }
[data-appearance='journal'] .cover-title {
  width: fit-content;
  max-width: 100%;
  color: #92391f;
  font-weight: 800;
  letter-spacing: -0.045em;
  line-height: 1.12;
}
[data-appearance='journal'] .cover-title::after {
  content: '';
  display: block;
  width: 48%;
  height: 6px;
  margin: 0.45rem auto -0.3rem;
  border-top: 3px solid var(--journal-orange);
  border-radius: 50%;
  transform: rotate(-2deg);
}
[data-appearance='journal'] .cover-description { color: #473b32; }
[data-appearance='journal'] .cover-actions > * {
  color: var(--journal-ink);
  border: 2px solid var(--journal-ink);
  border-radius: 2rem;
  background: #fff7e5;
  box-shadow: 2px 2px 0 var(--journal-ink);
}
[data-appearance='journal'] .cover-actions > button { background: #ff9d69; }
[data-appearance='journal'] .cover-actions > :hover { background: #ffd4aa; }
@media (max-width: 639px) {
  [data-appearance='journal'] .cover-sheet {
    width: calc(100% - 1.5rem);
    border-width: 5px;
    padding: 1.2rem;
    border-radius: 25px 22px 22px 18px;
  }
  [data-appearance='journal'] .cover-actions { margin-top: 1.15rem; }
}
[data-appearance='industrial'] .dashboard-hero {
  --cover-shade: linear-gradient(90deg, #171e28, rgb(23 30 40 / 86%) 27%, rgb(23 30 40 / 18%) 67%, rgb(23 30 40 / 8%));
  background: var(--cover-shade), #1d2c41 url('@/assets/inspection-station.webp') center 54% / cover no-repeat;
}
@media (max-width: 639px) {
  [data-appearance='industrial'] .dashboard-hero {
    --cover-shade: linear-gradient(90deg, rgb(23 30 40 / 94%), rgb(23 30 40 / 52%));
    background-position: center, 65% 54%;
  }
}
[data-appearance='industrial'] .cover-title {
  border-left: 4px solid #79aef5;
  padding-left: 0.35em;
}
</style>
