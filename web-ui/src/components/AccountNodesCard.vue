<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { CircleDot, RefreshCw, Network } from 'lucide-vue-next'
import { getAccountNodes, type AccountNode, type AccountNodesSnapshot } from '@/api/accounts'
import { Button } from '@/components/ui/button'

const snapshot = ref<AccountNodesSnapshot | null>(null)
const loading = ref(false)
const error = ref('')
let timer: ReturnType<typeof setInterval> | undefined
let disposed = false
const counts = computed(() => ({
  active: snapshot.value?.nodes.filter(n => n.status === 'active').length || 0,
  available: snapshot.value?.nodes.filter(n => n.status === 'available').length || 0,
  cooling: snapshot.value?.nodes.filter(n => n.status === 'cooling').length || 0,
}))
const browsers: Record<string, string> = { chrome: 'Chrome', edge: 'Edge', firefox: 'Firefox', pending: '未指定浏览器' }
const labels: Record<AccountNode['status'], string> = {
  active: '当前使用', available: '可用候选', cooling: '冷却中', pending: '待配置', missing: '缺少登录态', invalid: '待更新登录态',
}
function tone(node: AccountNode) {
  if (node.status === 'active') return 'border-emerald-200 bg-emerald-50/70'
  if (node.status === 'cooling') return 'border-amber-200 bg-amber-50/70'
  return 'border-slate-200 bg-slate-50/60'
}
function badge(node: AccountNode) {
  if (node.status === 'active') return 'bg-emerald-100 text-emerald-800'
  if (node.status === 'cooling') return 'bg-amber-100 text-amber-800'
  return 'bg-slate-200/70 text-slate-600'
}
function remaining(seconds: number) {
  const minutes = Math.ceil(seconds / 60)
  return `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分钟`
}
function date(seconds: number) {
  return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(seconds * 1000))
}
async function refresh() {
  if (loading.value) return
  loading.value = true
  try {
    const result = await getAccountNodes()
    if (!disposed) { snapshot.value = result; error.value = '' }
  } catch (e) {
    if (!disposed) error.value = (e as Error).message || '暂时无法读取节点状态'
  } finally {
    loading.value = false
  }
}
onMounted(() => {
  void refresh()
  timer = setInterval(() => { if (document.visibilityState === 'visible') void refresh() }, 15000)
})
onUnmounted(() => { disposed = true; if (timer) clearInterval(timer) })
</script>

<template>
  <section class="app-surface mb-6 rounded-xl border border-slate-200/80 p-5" aria-label="本地账号节点">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 class="flex items-center gap-2 text-base font-semibold text-slate-900"><Network class="h-4 w-4 text-slate-500" />本地账号节点</h2>
        <p class="mt-1 text-xs leading-5 text-slate-500">只读取本地记录，不探测备用账号。可用候选不代表已通过实时验证。</p>
      </div>
      <Button variant="outline" size="sm" :disabled="loading" @click="refresh"><RefreshCw class="mr-1.5 h-3.5 w-3.5" :class="{ 'animate-spin': loading }" />刷新状态</Button>
    </div>
    <p v-if="error" role="alert" class="mt-4 rounded-lg bg-rose-50 p-3 text-sm text-rose-700">{{ error }}<span v-if="snapshot"> · 以下为上次记录，可能已过期。</span></p>
    <p v-if="!snapshot && loading" class="py-6 text-sm text-slate-500">正在读取本地节点…</p>
    <template v-if="snapshot">
      <div class="my-4 flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-500">
        <span>当前使用 <strong class="ml-1 text-emerald-700">{{ counts.active }}</strong></span>
        <span>可用候选 <strong class="ml-1 text-slate-800">{{ counts.available }}</strong></span>
        <span>冷却中 <strong class="ml-1 text-amber-700">{{ counts.cooling }}</strong></span>
      </div>
      <div v-if="snapshot.nodes.length" class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <article v-for="node in snapshot.nodes" :key="node.name" class="min-w-0 rounded-xl border p-4" :class="tone(node)">
          <div class="flex items-center justify-between gap-2">
            <span class="flex min-w-0 items-center gap-2 font-semibold text-slate-900"><CircleDot class="h-4 w-4 shrink-0" :class="node.status === 'active' ? 'text-emerald-600' : 'text-slate-400'" /><span class="truncate">{{ node.name }}</span></span>
            <span class="shrink-0 rounded-full px-2 py-1 text-[11px] font-medium" :class="badge(node)">{{ labels[node.status] }}</span>
          </div>
          <p class="mt-2 text-sm text-slate-600">{{ browsers[node.browser] || node.browser }}</p>
          <template v-if="node.status === 'cooling' && node.cooldown_until">
            <p class="mt-3 text-sm font-medium text-amber-900">剩余 {{ remaining(node.remaining_seconds) }}</p>
            <p class="mt-1 text-xs text-amber-800">{{ date(node.cooldown_until) }} 恢复候选资格</p>
          </template>
          <template v-else-if="node.status === 'active'">
            <p class="mt-3 text-xs text-emerald-800">{{ node.running_by.length ? '正在采集' : '等待下一次定时检查' }}</p>
            <p class="mt-1 truncate text-xs text-slate-500" :title="node.selected_by.join('、')">{{ node.selected_by.join('、') }}</p>
          </template>
          <p v-else-if="node.status === 'available'" class="mt-3 text-xs text-slate-500">备用 · 需要切换时才使用</p>
          <p v-else class="mt-3 text-xs text-slate-500">请在账号管理中完善登录态与浏览器配置</p>
        </article>
      </div>
      <p v-else class="py-4 text-sm text-slate-500">尚未配置账号节点。</p>
    </template>
  </section>
</template>
