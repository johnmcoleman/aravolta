<script setup lang="ts">
import DataTable, {
  type DataTableRowClickEvent,
  type DataTablePageEvent,
  type DataTableSortEvent,
} from 'primevue/datatable'
import Column from 'primevue/column'
import Tag from 'primevue/tag'
import type { Device } from '../api'

// Controlled, server-side ("lazy") table: the parent owns paging/sort state and
// fetches each page from the API. We only ever render one page of rows.
defineProps<{
  devices: Device[]
  total: number
  rows: number
  first: number
  sortField: string
  sortOrder: number
}>()
const emit = defineEmits<{
  select: [Device]
  page: [{ first: number; rows: number }]
  sort: [{ sortField: string; sortOrder: number }]
}>()

const onRowClick = (e: DataTableRowClickEvent) => emit('select', e.data as Device)
const onPage = (e: DataTablePageEvent) => emit('page', { first: e.first, rows: e.rows })
const onSort = (e: DataTableSortEvent) =>
  emit('sort', { sortField: (e.sortField as string) || 'deviceId', sortOrder: e.sortOrder || 1 })
const rowClass = (d: Device) => (d.alert ? 'alert-row' : '')

const round = (n: number) => Math.round(n)
function ago(iso: string | null | undefined) {
  if (!iso) return '—'
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
  return s < 60 ? `${s}s ago` : `${Math.round(s / 60)}m ago`
}
</script>

<template>
  <DataTable
    :value="devices"
    dataKey="deviceId"
    lazy
    paginator
    :totalRecords="total"
    :rows="rows"
    :first="first"
    :sortField="sortField"
    :sortOrder="sortOrder"
    :rowsPerPageOptions="[10, 25, 50, 100]"
    removableSort
    :rowClass="rowClass"
    @row-click="onRowClick"
    @page="onPage"
    @sort="onSort"
    paginatorTemplate="CurrentPageReport FirstPageLink PrevPageLink NextPageLink LastPageLink RowsPerPageDropdown"
    currentPageReportTemplate="{first}–{last} of {totalRecords} racks"
    class="device-table"
  >
    <Column field="deviceId" header="Rack" sortable>
      <template #body="{ data }">
        <div class="dev">
          <span class="id">{{ data.deviceId }}</span>
          <span class="label" v-if="data.label">{{ data.label }}</span>
        </div>
      </template>
    </Column>
    <Column field="location" header="Zone" sortable>
      <template #body="{ data }">{{ data.location ?? '—' }}</template>
    </Column>
    <Column field="alert" header="Status" sortable>
      <template #body="{ data }">
        <Tag
          :severity="data.alert ? 'danger' : data.online ? 'success' : 'secondary'"
          :value="data.alert ? 'ALERT' : data.online ? 'online' : 'offline'"
        />
        <span v-if="data.alert" class="reasons">{{ data.alertReasons.join(', ') }}</span>
      </template>
    </Column>
    <Column field="latest.power" header="Power" sortable>
      <template #body="{ data }">
        <span class="num">{{ data.latest ? round(data.latest.power) + ' W' : '—' }}</span>
      </template>
    </Column>
    <Column field="latest.temperature" header="Temp" sortable>
      <template #body="{ data }">
        <span class="num">{{ data.latest ? round(data.latest.temperature) + ' °C' : '—' }}</span>
      </template>
    </Column>
    <Column field="latest.timestamp" header="Last seen" sortable>
      <template #body="{ data }">{{ ago(data.latest?.timestamp) }}</template>
    </Column>
  </DataTable>
</template>

<style scoped>
.dev {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}
.id {
  font-family: ui-monospace, Menlo, Consolas, monospace;
}
.label {
  color: var(--text-muted);
  font-size: 12px;
}
.num {
  font-variant-numeric: tabular-nums;
}
.reasons {
  margin-left: 8px;
  color: #f87171;
  font-size: 12px;
}
/* highlight alert rows and make every row feel clickable */
.device-table :deep(tbody tr) {
  cursor: pointer;
}
.device-table :deep(tbody tr.alert-row) {
  background: rgba(185, 28, 28, 0.12);
}
</style>
