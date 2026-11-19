import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import { i18n } from './i18n'
import { initializeAppearance } from './composables/useAppearance'
import './assets/main.css'

initializeAppearance()
const app = createApp(App)

app.use(router)
app.use(i18n)

app.mount('#app')
