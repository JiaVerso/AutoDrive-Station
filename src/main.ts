import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import App from './App.vue'
import './styles/global.scss'

const app = createApp(App)

// 全局错误兜底：吞掉组件渲染/生命周期中未捕获的异常，
// 避免单次报错导致整个前端“卡死 / 白屏”。
app.config.errorHandler = (err, _instance, info) => {
  console.error('[Global ErrorHandler]', info, err)
}

app.use(createPinia())
app.use(ElementPlus)
app.mount('#app')
