<template>
  <section class="page" data-module="yard">
    <header class="page-head">
      <div>
        <h2>堆场管理管理</h2>
        <p class="page-desc">维护箱区，围绕箱区编号、箱区名称、堆放层数、可用箱位做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记箱区</button>
        <button class="btn" type="button" @click="exportRows">导出堆场管理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div v-if="missingBlocks.length" class="notice-bar">
      <strong>箱位数据缺失（{{ missingBlocks.length }} 个箱区）：</strong>
      <span v-for="block in missingBlocks" :key="String(block.id)" class="notice-tag">
        {{ block['箱区编号'] }} {{ block['箱区名称'] }}
      </span>
      <span class="notice-tip">以上箱区缺少堆放层数或可用箱位，无法判定容量上限，补全资料前不能接收堆存单。</span>
    </div>

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
          <td v-for="column in columns" :key="column">{{ displayCell(row, column) }}</td>
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
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>

const ENDPOINT = '/api/yard'
const columns = ["箱区编号", "箱区名称", "堆放层数", "可用箱位", "已用箱位", "容量上限", "占用率", "可继续堆放", "所属堆场", "责任人", "箱区状态"]
const actions = ["启用箱区", "封闭箱区", "腾空箱区"]
const statuses = ["待启用", "正常堆放", "接近满载", "已封闭"]
const stats = [{"label": "在用箱区", "value": 0}, {"label": "接近满载箱区", "value": 0}, {"label": "可用箱位总数", "value": 0}]

const rows = ref<Row[]>([])
const missingBlocks = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

function displayCell(row: Row, column: string) {
  const value = row[column]
  if (value === null || value === undefined || value === '') return '—'
  if (column === '可继续堆放') return value ? '可堆放' : '不可堆放'
  if (column === '占用率') return `${value}%`
  return value
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '箱区登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? payload.detail ?? '堆场管理动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '堆场管理操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const [response, missingResponse] = await Promise.all([
      request(`${ENDPOINT}?${query}`),
      request(`${ENDPOINT}?slot_missing=true&size=200`),
    ])
    if (!response.ok) {
      throw new Error('箱区列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (missingResponse.ok) {
      const missingPayload = await missingResponse.json()
      missingBlocks.value = missingPayload.items ?? []
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '堆场管理列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.notice-bar {
  background: #fffaeb;
  border: 1px solid #fedf89;
  border-radius: 8px;
  padding: 8px 12px;
  margin-bottom: 12px;
  font-size: 13px;
  color: #93370d;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.notice-tag {
  background: #fff;
  border: 1px solid #fedf89;
  border-radius: 4px;
  padding: 1px 6px;
}
.notice-tip {
  color: var(--muted);
  font-size: 12px;
}
</style>
