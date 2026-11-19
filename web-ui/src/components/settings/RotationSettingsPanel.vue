<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import type { RotationSettings } from '@/api/settings'

const props = defineProps<{
  settings: RotationSettings
  isReady: boolean
  isSaving: boolean
}>()
const { t } = useI18n()
const cooldownHours = computed({
  get: () => props.settings.ACCOUNT_BLACKLIST_TTL === undefined ? '' : props.settings.ACCOUNT_BLACKLIST_TTL / 3600,
  set: (value: string | number) => {
    props.settings.ACCOUNT_BLACKLIST_TTL = value === '' ? NaN : Number(value) * 3600
  },
})
const accountPolicyValid = computed(() => {
  const attempts = props.settings.ACCOUNT_ROTATION_RETRY_LIMIT
  const seconds = props.settings.ACCOUNT_BLACKLIST_TTL
  return Number.isInteger(attempts) && Number(attempts) >= 1 &&
    Number.isInteger(seconds) && Number(seconds) >= 0
})

const emit = defineEmits<{
  (e: 'save'): void
}>()
</script>

<template>
  <Card class="app-surface overflow-hidden border-none">
    <CardHeader>
      <CardTitle>{{ t('rotation.title') }}</CardTitle>
      <CardDescription>{{ settings.ACCOUNT_FAILOVER_MANAGED ? '统一管理账号异常切换；代理池仍独立配置。' : t('rotation.description') }}</CardDescription>
    </CardHeader>
    <CardContent v-if="isReady" class="grid gap-6 lg:grid-cols-2">
      <section class="app-surface-subtle p-5">
        <div class="mb-5 flex items-center justify-between">
          <div>
            <h3 class="font-semibold text-slate-900">{{ t('rotation.account.title') }}</h3>
            <p class="text-sm text-slate-500">{{ settings.ACCOUNT_FAILOVER_MANAGED ? '当前账号正常就继续使用，采集失败达到上限后切换。' : t('rotation.account.description') }}</p>
          </div>
          <span v-if="settings.ACCOUNT_FAILOVER_MANAGED" class="ml-3 shrink-0 text-sm text-emerald-700">已启用</span>
          <Switch v-else v-model:checked="settings.ACCOUNT_ROTATION_ENABLED" />
        </div>

        <div class="grid gap-4">
          <div class="grid gap-2">
            <Label>{{ t('rotation.account.stateDir') }}</Label>
            <Input v-model="settings.ACCOUNT_STATE_DIR" placeholder="state" />
          </div>
          <div class="grid gap-2">
            <Label>{{ t('rotation.mode') }}</Label>
            <p v-if="settings.ACCOUNT_FAILOVER_MANAGED" class="text-sm text-slate-700">异常时切换 · 保留当前账号及冷却记录</p>
            <Select v-else v-model="settings.ACCOUNT_ROTATION_MODE">
              <SelectTrigger>
                <SelectValue :placeholder="t('rotation.modePlaceholder')" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="per_task">{{ t('rotation.perTask') }}</SelectItem>
                <SelectItem value="on_failure">{{ t('rotation.onFailure') }}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div class="grid gap-4 sm:grid-cols-2">
            <div class="grid gap-2">
              <Label for="account-attempts">{{ settings.ACCOUNT_FAILOVER_MANAGED ? '总尝试次数（含首次）' : t('rotation.retryLimit') }}</Label>
              <Input id="account-attempts" v-model.number="settings.ACCOUNT_ROTATION_RETRY_LIMIT" type="number" min="1" step="1" />
              <p v-if="settings.ACCOUNT_FAILOVER_MANAGED" class="text-xs text-slate-500">填 2 表示同一轮首次失败后再试 1 次；超时、验证、搜索和筛选等采集异常共用次数上限。连续失败后冷却并切换；手动取消不计数。</p>
            </div>
            <div class="grid gap-2">
              <Label for="account-cooldown">{{ settings.ACCOUNT_FAILOVER_MANAGED ? '冷却时间（小时）' : t('rotation.blacklistTtl') }}</Label>
              <Input v-if="settings.ACCOUNT_FAILOVER_MANAGED" id="account-cooldown" v-model="cooldownHours" type="number" min="0" step="0.5" />
              <Input v-else id="account-cooldown" v-model.number="settings.ACCOUNT_BLACKLIST_TTL" type="number" min="0" />
              <p v-if="settings.ACCOUNT_FAILOVER_MANAGED" class="text-xs text-slate-500">到期恢复候选资格，不强制切回。填 0 表示不等待。</p>
            </div>
          </div>
          <div v-if="settings.ACCOUNT_FAILOVER_MANAGED" class="space-y-2 text-xs leading-5 text-slate-500">
            <p>全局应用于三个账号。保存后从下一轮检查生效；已有冷却截止时间不变，新的限制事件采用新时长。</p>
            <p>备用账号不主动探测。受限、切换及新账号运行正常时继续发送 Bark。任务检查频率不受影响。</p>
            <p v-if="!accountPolicyValid" class="text-red-600">请输入至少 1 次的整数，以及不小于 0 的有效冷却时间。</p>
          </div>
        </div>
      </section>

      <section class="app-surface-subtle p-5">
        <div class="mb-5 flex items-center justify-between">
          <div>
            <h3 class="font-semibold text-slate-900">{{ t('rotation.proxy.title') }}</h3>
            <p class="text-sm text-slate-500">{{ t('rotation.proxy.description') }}</p>
          </div>
          <Switch v-model:checked="settings.PROXY_ROTATION_ENABLED" />
        </div>

        <div class="grid gap-4">
          <div class="grid gap-2">
            <Label>{{ t('rotation.mode') }}</Label>
            <Select v-model="settings.PROXY_ROTATION_MODE">
              <SelectTrigger>
                <SelectValue :placeholder="t('rotation.modePlaceholder')" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="per_task">{{ t('rotation.perTask') }}</SelectItem>
                <SelectItem value="on_failure">{{ t('rotation.onFailure') }}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div class="grid gap-2">
            <Label>{{ t('rotation.proxy.pool') }}</Label>
            <Textarea
              v-model="settings.PROXY_POOL"
              class="min-h-[120px]"
              placeholder="http://127.0.0.1:7890,socks5://127.0.0.1:1080"
            />
          </div>
          <div class="grid grid-cols-2 gap-4">
            <div class="grid gap-2">
              <Label>{{ t('rotation.retryLimit') }}</Label>
              <Input v-model.number="settings.PROXY_ROTATION_RETRY_LIMIT" type="number" min="1" />
            </div>
            <div class="grid gap-2">
              <Label>{{ t('rotation.blacklistTtl') }}</Label>
              <Input v-model.number="settings.PROXY_BLACKLIST_TTL" type="number" min="0" />
            </div>
          </div>
        </div>
      </section>
    </CardContent>
    <CardContent v-else class="py-8 text-sm text-gray-500">
      {{ t('rotation.loading') }}
    </CardContent>
    <CardFooter v-if="isReady" class="flex justify-end gap-2">
      <Button @click="emit('save')" :disabled="isSaving || (settings.ACCOUNT_FAILOVER_MANAGED && !accountPolicyValid)">{{ t('rotation.save') }}</Button>
    </CardFooter>
  </Card>
</template>
