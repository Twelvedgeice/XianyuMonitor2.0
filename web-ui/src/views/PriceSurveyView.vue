<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { getAllTasks } from '@/api/tasks'
import type { Task } from '@/types/task'
import * as api from '@/api/priceSurveys'
import type { SurveyItem, SurveyRun, SurveySettings, SurveyItems } from '@/api/priceSurveys'

const tasks = ref<Task[]>([])
const form = ref<SurveySettings>({task_id:null, keyword:'', item_limit:100})
const run = ref<SurveyRun | null>(null)
const results = ref<SurveyItems>({items:[],total:0,page:1,limit:30,keywords:[]})
const keyword = ref('')
const query = ref('')
const status = ref('')
const page = ref(1)
const busy = ref(false)
const error = ref('')
const message = ref('')
const editing = ref<SurveyItem | null>(null)
const soldPrice = ref('')
let timer: ReturnType<typeof setInterval> | undefined
let polling = false
let searchVersion = 0
const active = computed(() => run.value && ['queued','running'].includes(run.value.state))
const historyCategories = computed(() => Object.keys(results.value.history_counts || {}))
const valid = computed(() => form.value.task_id !== null && form.value.keyword.trim() &&
  (results.value.history_counts?.[form.value.keyword] || 0) > 0 &&
  Number.isInteger(form.value.item_limit) && form.value.item_limit >= 1 && form.value.item_limit <= 500)
const runLabel = computed(() => ({queued:'等待核验',running:'正在核验',completed:'核验完成',failed:'核验已停止',cancelled:'已取消核验'}[run.value?.state || ''] || '尚未核验'))
const historyExport = computed(() => '/api/price-surveys/history/export?'+new URLSearchParams({keyword:keyword.value,q:query.value,status:status.value}))
const names: Record<string,string> = {available:'当前在售',unavailable:'无法访问 / 已下架',unknown:'待确认',check_failed:'核验失败',observed:'旧列表已读取',missing:'旧列表未出现',history:'尚未核验',sold:'已卖出'}
const price = (value: number | null | undefined) => value == null ? '—' : '¥'+value.toLocaleString('zh-CN',{maximumFractionDigits:2})
const time = (value: string | null | undefined) => value ? value.replace('T',' ').slice(0,19) : '—'
const safeLink = (value: string) => /^https?:\/\//.test(value) ? value : undefined
async function search(reset = true) {
  if (reset) page.value = 1
  const version = ++searchVersion
  try {
    const value = await api.getSurveyItems(keyword.value,query.value,status.value,page.value)
    if (version === searchVersion) results.value = value
  } catch (e) { error.value = (e as Error).message }
}
async function action(operation: () => Promise<unknown>, success = '') {
  busy.value=true; error.value=''; message.value=''
  try { await operation(); message.value=success } catch(e) { error.value=(e as Error).message }
  finally { busy.value=false }
}
function chooseTask() {
  const task = tasks.value.find(t=>t.id===form.value.task_id)
  if (task) form.value.keyword=task.keyword
}
async function start() {
  await action(async()=>{
    run.value=await api.startSurvey(form.value)
    keyword.value=form.value.keyword
  })
}
async function poll() {
  if (polling || !active.value || document.hidden) return
  polling=true
  try {
    const previous=run.value?.actual_count
    run.value=(await api.getSurveyState()).latest
    if (!active.value || previous!==run.value?.actual_count) await search(false)
  } catch(e) { error.value=(e as Error).message }
  finally { polling=false }
}
async function confirmSold() {
  const item=editing.value
  if (!item) return
  const value=soldPrice.value.trim() === '' ? null : Number(soldPrice.value)
  if (value !== null && (!Number.isFinite(value) || value < 0)) { error.value='请输入有效的非负成交价'; return }
  await action(async()=>{ await api.markSurveySold(item,true,value); editing.value=null; await search(false) },'已保存手动售出确认')
}
onMounted(async()=>{
  await action(async()=>{
    const [all,state]=await Promise.all([getAllTasks(),api.getSurveyState()])
    tasks.value=all; form.value=state.settings; run.value=state.latest
    if (form.value.task_id === null && all.length) {
      form.value.task_id=all[0]!.id ?? null; form.value.keyword=all[0]!.keyword
    }
    keyword.value=form.value.keyword
    await search()
  })
  timer=setInterval(poll,2500)
})
onUnmounted(()=>{ if(timer) clearInterval(timer); searchVersion++ })
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-bold text-slate-900">历史商品售出核验</h1>
      <p class="mt-2 text-sm text-slate-500">点击后逐件访问本地 JSON / JSONL 历史商品详情，核实哪些已卖出。本地搜索无需连接闲鱼。</p>
    </div>
    <section class="app-surface space-y-5 p-5 md:p-6">
      <div class="grid gap-4 md:grid-cols-3">
        <div class="space-y-2">
          <Label for="survey-task">使用账号的参考任务</Label>
          <select id="survey-task" v-model="form.task_id" class="w-full rounded-md border bg-white p-2 text-sm" :disabled="!!active" @change="chooseTask">
            <option v-for="task in tasks" :key="task.id" :value="task.id">{{ task.task_name }}</option>
          </select>
          <p class="text-xs text-slate-500">复用当前可用的常驻浏览器；不会切换主节点或解除冷却。</p>
        </div>
        <div class="space-y-2">
          <Label for="survey-keyword">本地历史分类</Label>
          <select id="survey-keyword" v-model="form.keyword" class="w-full rounded-md border bg-white p-2 text-sm" :disabled="!!active">
            <option value="" disabled>选择历史商品分类</option>
            <option v-for="tag in historyCategories" :key="tag" :value="tag">{{ tag }}</option>
          </select>
          <p class="text-xs text-slate-500">可核验历史 JSON 商品 {{ results.history_counts?.[form.keyword] || 0 }} 件；不重新搜索最新商品。</p>
        </div>
        <div class="space-y-2">
          <Label for="survey-limit">本次最多核验件数</Label>
          <Input id="survey-limit" v-model.number="form.item_limit" type="number" min="1" max="500" step="1" :disabled="!!active" />
          <p class="text-xs text-slate-500">支持 1–500 件；优先核验尚未检查或较早检查的历史商品。</p>
        </div>
      </div>
      <div class="flex flex-wrap gap-3">
        <Button :disabled="busy || !!active || !valid" @click="start">核验历史商品售出状态</Button>
        <Button variant="outline" :disabled="busy || !!active || !valid" @click="action(()=>api.saveSurveySettings(form),'调查设置已保存')">保存默认设置</Button>
        <Button v-if="active" variant="outline" :disabled="busy" @click="action(async()=>{await api.cancelSurvey(); await poll()})">停止本次核验</Button>
      </div>
      <p class="text-xs leading-5 text-slate-500">仅手动点击时按本次上限逐件读取历史详情。只有当前商品明确显示“卖掉了 / 已卖出”等证据才自动标记；下架、删除、404、验证和超时均不算已卖出。每件之间让监测任务优先使用浏览器，检查频率不变。遇到登录、验证或网络故障会停止，已完成核验保留。关闭此页面后核验仍会继续，可随时回来停止。</p>
      <p v-if="error" role="alert" class="text-sm text-red-600">{{ error }}</p>
      <p v-if="message" role="status" class="text-sm text-emerald-700">{{ message }}</p>
    </section>

    <section v-if="run" class="app-surface space-y-4 p-5 md:p-6">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 class="font-semibold">{{ run.kind==='history_detail'?runLabel:'旧版列表调查记录' }} · {{ run.keyword }}</h2>
          <p class="mt-1 text-xs text-slate-500">{{ time(run.started_at) }} · {{ run.account || '等待可用账号' }} · 已核验 {{ run.actual_count }} / {{ run.target_count || run.item_limit }} 件</p>
          <p v-if="active" class="mt-1 text-xs text-slate-500">{{ run.summary.stage || runLabel }}</p>
        </div>
        <a v-if="!active && (run.kind==='history_detail' || run.state==='completed')" :href="'/api/price-surveys/runs/'+run.id+'/export'" class="text-sm text-blue-600" download>下载本次核验 JSON</a>
      </div>
      <progress v-if="active" class="w-full accent-blue-600" :value="run.actual_count" :max="run.target_count || run.item_limit" />
      <p v-if="run.error" class="text-sm text-amber-700">{{ run.error }}</p>
      <div v-if="run.kind==='history_detail'" class="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <div v-for="metric in [{label:'明确已卖出',value:run.summary.sold_count},{label:'当前在售',value:run.summary.available_count},{label:'无法访问 / 下架',value:run.summary.unavailable_count},{label:'待确认',value:run.summary.unknown_count},{label:'核验失败',value:run.summary.failed_count}]" :key="metric.label" class="rounded-xl bg-slate-50 p-4">
          <p class="text-xs text-slate-500">{{ metric.label }}</p><p class="mt-2 text-xl font-semibold">{{ metric.value || 0 }} 件</p>
        </div>
      </div>
      <div v-else-if="run.state === 'completed'" class="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div v-for="metric in [{label:'有效标价样本',value:String(run.summary.priced_count ?? 0)+' 件'},{label:'最低标价',value:price(run.summary.min)},{label:'标价中位数',value:price(run.summary.median)},{label:'最高标价',value:price(run.summary.max)}]" :key="metric.label" class="rounded-xl bg-slate-50 p-4">
          <p class="text-xs text-slate-500">{{ metric.label }}</p><p class="mt-2 text-xl font-semibold">{{ metric.value }}</p>
        </div>
      </div>
      <p class="text-xs leading-5 text-slate-500">已完成的核验逐件保存时间和证据来源；取消不会把未检查商品判为售出。历史挂牌价与本次可见挂牌价均不代表成交价，成交价仅显示手动填写的金额。已有手动售出确认保留。</p>
    </section>

    <section class="space-y-4">
      <div class="flex items-center justify-between gap-3"><h2 class="text-lg font-semibold">本地历史商品</h2><a :href="historyExport" class="text-sm text-blue-600" download>导出历史 JSON</a></div>
      <form class="app-surface grid gap-3 p-4 lg:grid-cols-[1fr_180px_170px_auto]" @submit.prevent="search()">
        <Input v-model="query" aria-label="本地关键词搜索" placeholder="搜索标题、商品 ID；多个词用空格分隔" />
        <select v-model="keyword" aria-label="历史 tag" class="min-w-0 rounded-md border bg-white p-2 text-sm">
          <option value="">全部 tag</option><option v-for="tag in results.keywords" :key="tag" :value="tag">{{ tag }}</option>
        </select>
        <select v-model="status" aria-label="商品状态" class="rounded-md border bg-white p-2 text-sm">
          <option value="">全部状态</option><option v-for="(label,key) in names" :key="key" :value="key">{{ label }}</option>
        </select>
        <Button type="submit" variant="outline">本地搜索</Button>
      </form>
      <p class="text-xs text-slate-500">共 {{ results.total }} 件。自动已卖出仅依据当前详情明确证据；旧列表未出现、下架或失败都不会自动算作售出。</p>
      <div class="grid gap-4 xl:grid-cols-2">
        <article v-for="item in results.items" :key="item.keyword+':'+item.item_id" class="app-surface flex flex-col gap-3 p-5">
          <div class="flex items-start justify-between gap-3">
            <a :href="safeLink(item.link)" target="_blank" rel="noopener noreferrer" class="min-w-0 break-words font-medium text-slate-900 hover:text-blue-600">{{ item.title }}</a>
            <span class="shrink-0 rounded-md px-2 py-1 text-xs" :class="item.status==='sold'?'bg-violet-50 text-violet-700':item.status==='missing'?'bg-amber-50 text-amber-700':'bg-slate-100 text-slate-600'">{{ names[item.status] }}</span>
          </div>
          <div class="flex flex-wrap gap-x-6 gap-y-2">
            <p class="text-sm text-slate-600">历史挂牌价 <strong class="text-lg text-slate-900">{{ price(item.price) }}</strong></p>
            <p v-if="item.checked_price!=null" class="text-sm text-slate-600">本次可见挂牌价 {{ price(item.checked_price) }}</p>
            <p v-if="item.status==='sold'" class="text-sm text-violet-700">成交价（手动） <strong>{{ item.sold_price===null?'未提供':price(item.sold_price) }}</strong></p>
          </div>
          <p class="text-xs text-slate-500">{{ item.keyword }} · ID {{ item.item_id }} · 最后读取 {{ time(item.last_seen) }}</p>
          <p v-if="item.last_checked" class="text-xs text-slate-500">核验时间 {{ time(item.last_checked) }} · {{ item.check_source==='detail_api'?'详情接口':'详情页面' }} · {{ item.check_evidence || '无明确状态证据' }}</p>
          <p v-if="item.status==='sold'" class="text-xs text-violet-700">{{ item.sold_source==='manual'?'手动确认已卖出':'当前详情明确证据确认已卖出' }} · {{ time(item.sold_at) }}</p>
          <p v-if="item.status==='sold' && item.check_status && item.check_status!=='sold'" class="text-xs text-amber-700">本次核验：{{ names[item.check_status==='failed'?'check_failed':item.check_status] }}；保留此前售出确认。</p>
          <div class="mt-auto">
            <Button v-if="item.status!=='sold'" size="sm" variant="outline" @click="editing=item;soldPrice=''">确认已售出 / 标 sold</Button>
            <Button v-else size="sm" variant="outline" :disabled="busy" @click="action(async()=>{await api.markSurveySold(item,false,null);await search(false)})">撤销售出标记</Button>
          </div>
        </article>
      </div>
      <p v-if="!results.items.length" class="py-8 text-center text-sm text-slate-500">没有匹配的本地记录。可更换关键词，或先积累本地历史商品 JSON / JSONL。</p>
      <div class="flex items-center justify-center gap-4">
        <Button variant="outline" :disabled="page<=1" @click="page--;search(false)">上一页</Button>
        <span class="text-sm">{{ page }} / {{ Math.max(1,Math.ceil(results.total/results.limit)) }}</span>
        <Button variant="outline" :disabled="page*results.limit>=results.total" @click="page++;search(false)">下一页</Button>
      </div>
    </section>
    <div v-if="editing" class="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/30 p-4" role="dialog" aria-modal="true" aria-labelledby="sold-title">
      <form class="w-full max-w-md space-y-4 rounded-xl bg-white p-6 shadow-xl" @submit.prevent="confirmSold">
        <h2 id="sold-title" class="text-lg font-semibold">手动确认已售出</h2>
        <p class="text-sm">{{ editing.title }}</p>
        <p class="text-xs text-slate-500">仅在你已确认售出时保存。成交价可留空；不会把最后标价自动当成成交价。</p>
        <Label for="sold-price">成交价（元，可选）</Label>
        <Input id="sold-price" v-model="soldPrice" type="number" min="0" step="0.01" placeholder="未知则留空" />
        <div class="flex justify-end gap-3"><Button type="button" variant="outline" @click="editing=null">取消</Button><Button type="submit" :disabled="busy">确认已售出</Button></div>
      </form>
    </div>
  </div>
</template>
