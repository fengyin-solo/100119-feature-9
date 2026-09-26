<template>
  <section class="page" data-module="yardstore">
    <header class="page-head">
      <div>
        <h2>堆存记录管理</h2>
        <p class="page-desc">维护堆存单，围绕堆存单号、关联箱号、箱区编号、贝位号做登记、筛选与状态流转；已封闭箱区不再接收堆存单，确认进场按箱区容量上限校验。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="toggleCreate">登记堆存单</button>
        <button class="btn" type="button" @click="exportRows">导出堆存记录清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form v-if="showCreate" class="filter-bar create-panel" @submit.prevent="submitCreate">
      <label v-for="field in createFields" :key="field.name" class="filter-item">
        <span>{{ field.name }}<em v-if="field.required"> *</em></span>
        <input v-model="createForm[field.name]" :placeholder="field.placeholder" />
      </label>
      <button class="btn primary" type="submit">保存堆存单</button>
      <button class="btn ghost" type="button" @click="toggleCreate">取消</button>
    </form>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无堆存记录数据，可先登记堆存单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条堆存记录记录</span>
      <span v-if="okMessage" class="ok-text">{{ okMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/yardstore'
const columns = ["堆存单号", "关联箱号", "箱区编号", "贝位号", "堆存开始", "堆存结束", "堆存天数", "堆存状态"]
const actions = ["确认进场", "确认提离", "撤销堆存"]
const createFields = [
  { name: '堆存单号', required: true, placeholder: '如 YS-0100' },
  { name: '关联箱号', required: true, placeholder: '如 TEMU7700036' },
  { name: '箱区编号', required: true, placeholder: '需为未封闭且已登记的箱区' },
  { name: '贝位号', required: false, placeholder: '选填' },
]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const okMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const stats = ref([
  { label: '堆存中箱量', value: 0 },
  { label: '待进场箱量', value: 0 },
  { label: '待提离箱量', value: 0 },
])
const showCreate = ref(false)
const createForm = ref<Record<string, string>>({})

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function toggleCreate() {
  showCreate.value = !showCreate.value
}

async function readMessage(response: Response, fallback: string) {
  const result = (await response.json()) as { ok?: boolean; message?: string }
  if (!response.ok || result.ok === false) {
    throw new Error(result.message ?? fallback)
  }
  return result.message ?? fallback
}

async function submitCreate() {
  errorMessage.value = ''
  okMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createForm.value }),
    })
    okMessage.value = await readMessage(response, '堆存单登记失败，请稍后重试')
    createForm.value = {}
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '堆存单登记失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  okMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    okMessage.value = await readMessage(response, '堆存记录动作未生效，请稍后重试')
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '堆存记录操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams(filters.value as Record<string, string>)
  params.set('size', '200')
  try {
    const [listResp, statsResp] = await Promise.all([
      request(`${ENDPOINT}?${params.toString()}`),
      request(`${ENDPOINT}?size=200`),
    ])
    if (!listResp.ok) {
      throw new Error('堆存单列表读取失败')
    }
    const payload = await listResp.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (statsResp.ok) {
      const all = (await statsResp.json()).items ?? []
      stats.value = [
        { label: '堆存中箱量', value: all.filter((r: Row) => r.status === '堆存中').length },
        { label: '待进场箱量', value: all.filter((r: Row) => r.status === '待进场').length },
        { label: '待提离箱量', value: all.filter((r: Row) => r.status === '待提离').length },
      ]
    }
  } catch (catchError) {
    errorMessage.value = catchError instanceof Error ? catchError.message : '堆存记录列表读取失败'
  }
}

onMounted(reload)
</script>
