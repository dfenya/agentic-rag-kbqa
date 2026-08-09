<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { getSettings, updateSettings, getModels } from '@/api/client'

// 深色模式：切换时实时预览，保存时才持久化，离开未保存则恢复
const isDark = inject<Ref<boolean>>('isDark', ref(false))
const darkMode = ref(isDark.value)
const loading = ref(false)
const models = ref<{ name: string; size: number }[]>([])

// 实时预览：切换开关时立即改变 html.dark class（不触发 useDark 持久化）
watch(darkMode, (val) => {
  document.documentElement.classList.toggle('dark', val)
})

// 离开页面未保存时，恢复到已持久化的真实状态
onUnmounted(() => {
  document.documentElement.classList.toggle('dark', isDark.value)
  darkMode.value = isDark.value
})

const llm = reactive({
  ollama_base_url: 'http://localhost:11434',
  model: '',
  temperature: 0,
})

const rag = reactive({
  top_k: 5,
  score_threshold: 0.7,
})

const memory = reactive({
  enabled: true,
  top_k: 5,
})

onMounted(async () => {
  loading.value = true
  try {
    const s = await getSettings()
    if (s.llm) Object.assign(llm, s.llm)
    if (s.rag) Object.assign(rag, s.rag)
    if (s.memory) Object.assign(memory, s.memory)
    models.value = await getModels()
  } catch (e) {
    console.error('Failed to load settings:', e)
  } finally {
    loading.value = false
  }
})

async function handleSave() {
  loading.value = true
  try {
    // 保存时同步给 useDark，触发持久化（localStorage）
    isDark.value = darkMode.value
    await updateSettings({
      llm: { ...llm },
      rag: { ...rag },
      memory: { ...memory },
    })
    ElMessage.success('设置已保存 · 下次对话即刻生效')
  } catch {
    ElMessage.error('保存失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="settings-view">
    <div class="page-top">
      <h2>⚙️ 系统设置</h2>
      <p class="sub">配置模型、检索参数与界面偏好</p>
    </div>

    <div v-loading="loading">
      <div class="cards">
        <!-- 大模型 -->
        <el-card shadow="never" class="card">
          <template #header>🤖 模型</template>
          <el-form label-position="top" size="default">
            <el-form-item label="Ollama 服务地址">
              <el-input v-model="llm.ollama_base_url" />
            </el-form-item>
            <el-form-item label="对话模型">
              <el-select v-model="llm.model" filterable placeholder="选择模型" style="width:100%">
                <el-option
                  v-for="m in models"
                  :key="m.name"
                  :label="m.name"
                  :value="m.name"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="Temperature">
              <el-slider v-model="llm.temperature" :min="0" :max="1" :step="0.1" />
            </el-form-item>
          </el-form>
        </el-card>

        <!-- RAG 检索 -->
        <el-card shadow="never" class="card">
          <template #header>🔍 检索</template>
          <el-form label-position="top" size="default">
            <el-form-item label="返回条目数 (top-k)">
              <el-input-number v-model="rag.top_k" :min="1" :max="20" style="width:100%" />
            </el-form-item>
            <el-form-item label="相似度阈值">
              <el-slider v-model="rag.score_threshold" :min="0" :max="1" :step="0.05" />
              <span class="hint">{{ rag.score_threshold.toFixed(2) }}</span>
            </el-form-item>
          </el-form>
        </el-card>

        <!-- 记忆 -->
        <el-card shadow="never" class="card">
          <template #header>🧠 记忆</template>
          <el-form label-position="top" size="default">
            <el-form-item label="启用长期记忆">
              <el-switch v-model="memory.enabled" />
            </el-form-item>
            <el-form-item label="记忆召回数">
              <el-input-number v-model="memory.top_k" :min="1" :max="10" style="width:100%" />
            </el-form-item>
          </el-form>
        </el-card>

        <!-- 界面主题 -->
        <el-card shadow="never" class="card">
          <template #header>🎨 界面</template>
          <el-form label-position="top" size="default">
            <el-form-item label="深色模式">
              <el-switch v-model="darkMode" />
            </el-form-item>
          </el-form>
        </el-card>
      </div>

      <el-button type="primary" :loading="loading" class="save-btn" @click="handleSave">
        保存设置
      </el-button>

      <el-alert type="info" :closable="false" style="margin-bottom: 32px">
        <template #title>生效说明</template>
        <ul style="margin:4px 0;padding-left:18px;font-size:13px;line-height:1.8">
          <li><b>模型 / Temperature / Ollama 地址</b>：下次对话生效（每次请求实时读取）</li>
          <li><b>检索 top-k / 相似度阈值</b>：下次对话生效</li>
          <li><b>长期记忆开关 / 召回数</b>：下次对话生效</li>
          <li><b>深色模式</b>：即时切换预览，保存后持久化</li>
          <li><b>上下文窗口大小 (num_ctx)</b>：需修改 <code>.env.dev</code> 后<b>重启后端服务</b>（<code>python run.py</code>）</li>
        </ul>
      </el-alert>
    </div>
  </div>
</template>

<style scoped>
.settings-view { height: 100%; padding: 24px 32px; overflow-y: auto; }
.page-top { margin-bottom: 24px; }
.page-top h2 {
  margin: 0 0 4px; font-size: 20px; font-weight: 700;
  background: var(--grad-primary);
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent;
}
.sub { margin: 0; color: var(--el-text-color-secondary); font-size: 13px; }

.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}

/* 卡片：hover 微动效 + 层次感阴影 */
.card {
  border-radius: var(--radius-md);
  transition: all .25s ease;
}
.card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-lg);
  border-color: var(--el-color-primary);
}

.hint { font-size: 12px; color: var(--el-text-color-secondary); }

/* 保存按钮：主题阴影 + hover 上浮 */
.save-btn {
  margin-bottom: 32px;
  box-shadow: var(--shadow-primary);
  transition: all .25s ease;
}
.save-btn:hover {
  transform: translateY(-1px);
  box-shadow: var(--shadow-primary-hover);
}
</style>
