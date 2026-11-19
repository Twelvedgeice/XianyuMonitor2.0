import { readonly, ref } from 'vue'

const storageKey = 'xianyu-monitor.appearance'
const appearances = ['journal', 'industrial'] as const
type Appearance = typeof appearances[number]

const appearance = ref<Appearance>('journal')

function applyAppearance(value: Appearance) {
  appearance.value = value
  document.documentElement.dataset.appearance = value
  document.querySelector('meta[name="theme-color"]')?.setAttribute(
    'content', value === 'journal' ? '#242120' : '#151c26',
  )
}

export function initializeAppearance() {
  let initial: Appearance = 'journal'
  try {
    if (localStorage.getItem(storageKey) === 'industrial') initial = 'industrial'
  } catch { /* Storage may be unavailable in private browsing. */ }
  applyAppearance(initial)
  window.addEventListener('storage', (event) => {
    if (event.key === storageKey || event.key === null) {
      applyAppearance(event.newValue === 'industrial' ? 'industrial' : 'journal')
    }
  })
}

function selectAppearance(value: Appearance) {
  applyAppearance(value)
  try {
    localStorage.setItem(storageKey, value)
  } catch { /* The selected appearance still applies to this tab. */ }
}

export function useAppearance() {
  return { appearance: readonly(appearance), appearances, selectAppearance }
}
