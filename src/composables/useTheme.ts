import { ref, onMounted } from 'vue'

const STORAGE_KEY = 'user-theme'

// 全局单例：保证整站共享同一主题状态
const isDark = ref(false)

function applyTheme(theme: 'light' | 'dark') {
  document.documentElement.className = theme
  isDark.value = theme === 'dark'
}

function initTheme() {
  const saved = (localStorage.getItem(STORAGE_KEY) as 'light' | 'dark' | null) || 'light'
  applyTheme(saved)
}

function toggleTheme() {
  const next = isDark.value ? 'light' : 'dark'
  applyTheme(next)
  localStorage.setItem(STORAGE_KEY, next)
}

export function useTheme() {
  onMounted(() => {
    // 仅首次挂载时同步（单例已被 App 初始化过则跳过重复写）
    if (!document.documentElement.classList.contains('light') &&
        !document.documentElement.classList.contains('dark')) {
      initTheme()
    }
  })

  return { isDark, toggleTheme, initTheme }
}
