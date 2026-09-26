<template>
  <section class="page" data-module="yard">
    <header class="page-head">
      <div>
        <h2>堆场管理管理</h2>
        <p class="page-desc">维护箱区，围绕箱区编号、箱区名称、堆放层数、可用箱位做登记、筛选与状态流转；容量上限 = 堆放层数 × 可用箱位。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="toggleCreate">登记箱区</button>
        <button class="btn" type="button" @click="exportRows">导出堆场管理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <section v-if="missingYards.length" class="missing-panel">
      <strong>箱位数据缺失（{{ missingYards.length }} 个箱区）</strong>
      <p>以下箱区未维护堆放层数或可用箱位，无法判定容量上限，堆存单确认进场会被拦截，请尽快补全资料：</p>
      <ul>
        <li v-for="row in missingYards" :key="String(row.id)">{{ row.箱区编号 }} · {{ row.箱区名称 }}</li>
      </ul>
    </section>

    <form v-if="showCreate" class="filter-bar create-panel" @submit.prevent="submitCreate">
      <label v-for="field in createFields" :key="field.name" class="filter-item">
        <span>{{ field.name }}<em v-if="field.required"> *</em></span>
        <input v-model="createForm[field.name]" :placeholder="field.placeholder" />
      </label>
      <button class="btn primary" type="submit">保存箱区</button>
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
          <td
            v-for="column in columns"
            :key="column"
            :class="column === '容量提示' ? capacityClass(row) : ''"
          >
            {{ row[column] ?? '—' }}
          </td>
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
          <td :colspan="columns.length + 1" class="empty-state">暂无堆场管理数据，可先登记箱区</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条堆场管理记录</span>
      <span v-if="okMessage" class="ok-text">{{ okMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/yard'
const columns = ["箱区编号", "箱区名称", "堆放层数", "可用箱位", "已用箱位", "容量上限", "所属堆场", "责任人", "箱区状态", "容量提示"]
const actions = ["启用箱区", "封闭箱区", "腾空箱区"]
const createFields = [
  { name: '箱区编号', required: true, placeholder: '如 YARD-0006' },
  { name: '箱区名称', required: true, placeholder: '如 出口重箱三区' },
  { name: '堆放层数', required: true, placeholder: '非负整数，参与容量上限计算' },
  { name: '可用箱位', required: false, placeholder: '非负整数，参与容量上限计算' },
  { name: '所属堆场', required: false, placeholder: '选填' },
  { name: '责任人', required: false, placeholder: '选填' },
]
const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const okMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const stats = ref([
  { label: '在用箱区', value: 0 },
  { label: '接近满载箱区', value: 0 },
  { label: '已封闭箱区', value: 0 },
  { label: '箱位数据缺失', value: 0 },
])
const missingYards = ref<Row[]>([])
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

function capacityClass(row: Row) {
  const note = String(row['容量提示'] ?? '')
  if (note.startsWith('已超堆')) return 'error-text'
  if (note) return 'warn-text'
  return ''
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
    okMessage.value = await readMessage(response, '箱区登记失败，请稍后重试')
    createForm.value = {}
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '箱区登记失败'
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
    okMessage.value = await readMessage(response, '堆场管理动作未生效，请稍后重试')
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '堆场管理操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams(filters.value as Record<string, string>)
  params.set('size', '200')
  try {
    const [listResp, statsResp, missingResp] = await Promise.all([
      request(`${ENDPOINT}?${params.toString()}`),
      request(`${ENDPOINT}?size=200`),
      request(`${ENDPOINT}/missing-capacity`),
    ])
    if (!listResp.ok) {
      throw new Error('箱区列表读取失败')
    }
    const payload = await listResp.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length

    if (statsResp.ok) {
      const all = (await statsResp.json()).items ?? []
      stats.value = [
        { label: '在用箱区', value: all.filter((r: Row) => r.status === '正常堆放' || r.status === '接近满载').length },
        { label: '接近满载箱区', value: all.filter((r: Row) => r.status === '接近满载').length },
        { label: '已封闭箱区', value: all.filter((r: Row) => r.status === '已封闭').length },
        { label: '箱位数据缺失', value: all.filter((r: Row) => r['容量提示'] === '箱位数据缺失').length },
      ]
    }
    if (missingResp.ok) {
      missingYards.value = (await missingResp.json()).items ?? []
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '堆场管理列表读取失败'
  }
}

onMounted(reload)
</script>
