<script setup lang="ts">
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { useRouter } from 'vue-router'
import { loginUser, registerUser } from '@/api/client'

const router = useRouter()
const formRef = ref<FormInstance>()
const isRegister = ref(false)
const loading = ref(false)

const form = reactive({ username: '', password: '' })

const rules: FormRules = {
  username: [
    { required: true, message: '请输入手机号', trigger: 'blur' },
    { pattern: /^1[3-9]\d{9}$/, message: '手机号格式不正确', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码不少于 6 位', trigger: 'blur' },
  ],
}

async function submit() {
  if (!formRef.value) return
  await formRef.value.validate().catch(() => {})
  const valid = await formRef.value.validate().then(() => true).catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    const fn = isRegister.value ? registerUser : loginUser
    const res = await fn(form.username, form.password)
    localStorage.setItem('token', res.access_token)
    localStorage.setItem('user', JSON.stringify({ id: res.user_id, username: res.username }))
    ElMessage.success(isRegister.value ? '注册成功' : '登录成功')
    router.replace('/')
  } catch (e: any) {
    if (e?.response?.status === 401 && !isRegister.value) {
      ElMessage({ message: '账号不存在或密码错误，请重试或前往注册', type: 'error', duration: 4000 })
    } else if (e?.response?.status === 409) {
      ElMessage.error('该手机号已注册')
    } else {
      ElMessage.error(e?.response?.data?.detail || '网络错误，请稍后重试')
    }
  } finally {
    loading.value = false
  }
}

function toggleMode() {
  isRegister.value = !isRegister.value
  formRef.value?.resetFields()
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-card">
      <h2>{{ isRegister ? '注册' : '登录' }}</h2>

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @keyup.enter="submit">
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="手机号" size="large" maxlength="11" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input v-model="form.password" type="password" placeholder="密码" size="large" show-password />
        </el-form-item>
      </el-form>

      <el-button type="primary" size="large" :loading="loading" style="width: 100%; margin-bottom: 12px" @click="submit">
        {{ isRegister ? '注册' : '登录' }}
      </el-button>
      <el-button text size="default" style="width: 100%" @click="toggleMode">
        {{ isRegister ? '已有账号？登录' : '没有账号？注册' }}
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.auth-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--el-bg-color-page);
}
.auth-card {
  width: 380px;
  padding: 32px;
  border-radius: 12px;
  background: var(--el-bg-color);
  box-shadow: var(--shadow-md);
}
.auth-card h2 {
  margin: 0 0 20px;
  text-align: center;
  font-size: 20px;
}
</style>
