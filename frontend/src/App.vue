<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { listDevices, getSummary, type Device, type Summary, type DeviceQuery } from './api'
import SummaryCards from './components/SummaryCards.vue'
import HallHeatmap from './components/HallHeatmap.vue'
import DeviceTable from './components/DeviceTable.vue'
import DeviceDetail from './components/DeviceDetail.vue'
import InputText from 'primevue/inputtext'
import SelectButton from 'primevue/selectbutton'
import Select from 'primevue/select'

const devices = ref<Device[]>([]) // current page only
const total = ref(0)
const summary = ref<Summary | null>(null)
const error = ref('')

// Server-side paging + sort state.
const first = ref(0)
const rows = ref(25)
const sortField = ref('deviceId')
const sortOrder = ref(1) // 1 asc, -1 desc

// Filters (applied server-side).
const search = ref('')
const zoneFilter = ref<string | null>(null)
const statusFilter = ref<'all' | 'online' | 'offline' | 'alert'>('all')

const selected = ref<Device | null>(null)

const statusOptions = [
  { label: 'All', value: 'all' },
  { label: 'Online', value: 'online' },
  { label: 'Offline', value: 'offline' },
  { label: 'Alert', value: 'alert' },
]

function query(): DeviceQuery {
  return {
    limit: rows.value,
    offset: first.value,
    q: search.value.trim() || undefined,
    zone: zoneFilter.value,
    status: statusFilter.value,
    sort: sortField.value,
    order: sortOrder.value === -1 ? 'desc' : 'asc',
  }
}

async function fetchPage() {
  try {
    const res = await listDevices(query())
    devices.value = res.devices
    total.value = res.total
    error.value = ''
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : 'failed to load'
  }
}

async function fetchSummary() {
  try {
    // Scope the cards by the same q + zone as the table (status is a drill-down).
    summary.value = await getSummary({ q: search.value.trim() || undefined, zone: zoneFilter.value })
  } catch {
    /* summary is best-effort; the page fetch surfaces API errors */
  }
}

function refresh() {
  fetchPage()
  fetchSummary()
}

function onPage(e: { first: number; rows: number }) {
  first.value = e.first
  rows.value = e.rows
  fetchPage()
}
function onSort(e: { sortField: string; sortOrder: number }) {
  sortField.value = e.sortField
  sortOrder.value = e.sortOrder
  first.value = 0 // new sort -> back to first page
  fetchPage()
}
function onHall(zone: string) {
  zoneFilter.value = zoneFilter.value === zone ? null : zone // click again to clear
}

// Changing a filter returns to the first page. Debounce the text search so we
// don't hit the API on every keystroke.
let searchTimer: number | undefined
watch(search, () => {
  clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    first.value = 0
    fetchPage()
    fetchSummary() // search scopes the summary too
  }, 250)
})
watch(zoneFilter, () => {
  first.value = 0
  fetchPage()
  fetchSummary() // zone scopes the summary too
})
watch(statusFilter, () => {
  first.value = 0
  fetchPage() // status is a drill-down — it does NOT scope the summary
})

let poll: number
onMounted(() => {
  refresh()
  poll = window.setInterval(refresh, 5000) // keep the current page + summary live
})
onUnmounted(() => clearInterval(poll))
</script>

<template>
  <div class="layout">
    <header class="topbar">
      <div class="brand">⚡ Aravolta <span>Telemetry</span></div>
      <div class="health" :class="{ err: error }">
        {{ error ? 'API error: ' + error : 'live · refreshing every 5s' }}
      </div>
    </header>

    <main>
      <SummaryCards :summary="summary" />

      <HallHeatmap :stats="summary?.zoneStats ?? []" :selected="zoneFilter" @select="onHall" />

      <section class="controls">
        <InputText v-model="search" placeholder="Search rack, label, or zone…" class="search" />
        <Select
          v-model="zoneFilter"
          :options="summary?.zones ?? []"
          placeholder="All zones"
          showClear
          class="loc"
        />
        <SelectButton
          v-model="statusFilter"
          :options="statusOptions"
          optionLabel="label"
          optionValue="value"
          :allowEmpty="false"
        />
      </section>

      <DeviceTable
        :devices="devices"
        :total="total"
        :rows="rows"
        :first="first"
        :sortField="sortField"
        :sortOrder="sortOrder"
        @select="selected = $event"
        @page="onPage"
        @sort="onSort"
      />
    </main>

    <DeviceDetail :device="selected" @close="selected = null" />
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  flex-direction: column;
  min-height: 100%;
}
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 22px;
  border-bottom: 1px solid var(--border);
}
.brand {
  font-size: 18px;
  font-weight: 600;
}
.brand span {
  color: var(--text-muted);
  font-weight: 400;
}
.health {
  font-size: 12px;
  color: #4ade80;
}
.health.err {
  color: #f87171;
}
main {
  width: 100%;
  max-width: 1200px;
  margin: 0 auto;
  padding: 18px 22px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.controls {
  display: flex;
  gap: 12px;
  align-items: center;
}
.search {
  flex: 0 0 320px;
}
.loc {
  flex: 0 0 190px;
}
</style>
