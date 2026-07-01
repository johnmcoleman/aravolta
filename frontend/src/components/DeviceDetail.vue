<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue'
import Dialog from 'primevue/dialog'
import Tag from 'primevue/tag'
import { getMetrics, getLive, type Device, type Reading } from '../api'

const POLL_MS = 15000 // brief: live updates every 15s (polling)
const WINDOW_S = 60 // brief: last 60 seconds
const AVG_MS = 10000 // brief: 10-second rolling average

const props = defineProps<{ device: Device | null }>()
const emit = defineEmits<{ close: [] }>()

// Alert limits are PER-DEVICE, delivered by the API (from the devices table) —
// not hardcoded. They drive the chart's limit lines and the headline colouring.
const powerLimit = computed(() => props.device?.powerLimit ?? 1000)
const tempLimit = computed(() => props.device?.tempLimit ?? 85)
const powerHot = computed(() => (live.value?.power ?? 0) > powerLimit.value)
const tempHot = computed(() => (live.value?.temperature ?? 0) > tempLimit.value)

const points = ref<Reading[]>([])
const live = ref<Reading | null>(null)
const loading = ref(false)
let timer: number | undefined

async function load(id: string) {
  loading.value = true
  try {
    // Re-fetch the whole 60s window each tick: the server query already drops
    // points older than 60s, so the chart "scrolls" without us managing it.
    // Fetch independently so a missing /live (a never-reported device) can't
    // blank the history, and vice-versa.
    const [hist, latest] = await Promise.all([
      getMetrics(id, WINDOW_S).catch(() => [] as Reading[]),
      getLive(id).catch(() => null),
    ])
    points.value = hist
    live.value = latest
  } finally {
    loading.value = false
  }
}

function stop() {
  if (timer) {
    clearInterval(timer)
    timer = undefined
  }
}

watch(
  () => props.device,
  (d) => {
    stop()
    points.value = []
    live.value = null
    if (d) {
      load(d.deviceId)
      timer = window.setInterval(() => load(d.deviceId), POLL_MS)
    }
  },
)
onUnmounted(stop)

// Rolling average over a trailing window. points are oldest-first.
function rollingAvg(key: 'power' | 'temperature'): [number, number][] {
  const out: [number, number][] = []
  for (let i = 0; i < points.value.length; i++) {
    const t = new Date(points.value[i].timestamp).getTime()
    let sum = 0
    let n = 0
    for (let j = i; j >= 0; j--) {
      const tj = new Date(points.value[j].timestamp).getTime()
      if (t - tj > AVG_MS) break
      sum += points.value[j][key]
      n++
    }
    out.push([t, sum / n])
  }
  return out
}

const series = (key: 'power' | 'temperature'): [number, number][] =>
  points.value.map((p) => [new Date(p.timestamp).getTime(), p[key]])

// A dashed horizontal control limit = the "alerting" on the chart itself.
// Always shown; muted grey when in-spec, red only when currently breaching.
const limitLine = (
  value: number, text: string, breaching: boolean,
  position: 'insideStartTop' | 'insideEndTop' = 'insideStartTop',
) => ({
  silent: true,
  symbol: 'none',
  lineStyle: { color: breaching ? '#ef4444' : '#71717a', type: 'dashed' as const, width: 1 },
  label: { color: breaching ? '#ef4444' : '#a1a1aa', formatter: text, position },
  data: [{ yAxis: value }],
})

const option = computed(() => ({
  backgroundColor: 'transparent',
  animation: false,
  grid: { left: 52, right: 56, top: 38, bottom: 28 },
  tooltip: { trigger: 'axis' },
  legend: { top: 4, textStyle: { color: '#a1a1aa' } },
  xAxis: {
    type: 'time',
    axisLabel: { color: '#a1a1aa' },
    axisLine: { lineStyle: { color: '#3f3f46' } },
  },
  yAxis: [
    {
      type: 'value',
      name: 'Power (W)',
      nameTextStyle: { color: '#a1a1aa' },
      axisLabel: { color: '#a1a1aa' },
      splitLine: { lineStyle: { color: '#27272a' } },
      // Always keep the limit line in view, even when the data is well below it.
      max: (v: { max: number }) => Math.ceil(Math.max(v.max, powerLimit.value) * 1.08),
    },
    {
      type: 'value',
      name: 'Temp (°C)',
      nameTextStyle: { color: '#a1a1aa' },
      axisLabel: { color: '#a1a1aa' },
      splitLine: { show: false },
      max: (v: { max: number }) => Math.ceil(Math.max(v.max, tempLimit.value) * 1.08),
    },
  ],
  series: [
    { name: 'Power', type: 'line', showSymbol: false, yAxisIndex: 0,
      lineStyle: { width: 2, color: '#60a5fa' }, itemStyle: { color: '#60a5fa' },
      data: series('power'),
      markLine: limitLine(powerLimit.value, `${Math.round(powerLimit.value)} W limit`, powerHot.value) },
    { name: 'Power · 10s avg', type: 'line', showSymbol: false, yAxisIndex: 0,
      lineStyle: { width: 1.5, type: 'dashed', color: '#3b82f6' }, itemStyle: { color: '#3b82f6' }, data: rollingAvg('power') },
    { name: 'Temperature', type: 'line', showSymbol: false, yAxisIndex: 1,
      lineStyle: { width: 2, color: '#f59e0b' }, itemStyle: { color: '#f59e0b' },
      data: series('temperature'),
      markLine: limitLine(tempLimit.value, `${Math.round(tempLimit.value)} °C limit`, tempHot.value, 'insideEndTop') },
    { name: 'Temp · 10s avg', type: 'line', showSymbol: false, yAxisIndex: 1,
      lineStyle: { width: 1.5, type: 'dashed', color: '#d97706' }, itemStyle: { color: '#d97706' }, data: rollingAvg('temperature') },
  ],
}))
</script>

<template>
  <Dialog
    :visible="!!device"
    modal
    dismissableMask
    :style="{ width: 'min(920px, 94vw)' }"
    @update:visible="(v: boolean) => { if (!v) emit('close') }"
  >
    <template #header>
      <div class="hdr" v-if="device">
        <span class="id">{{ device.deviceId }}</span>
        <span class="label">{{ device.label }} · {{ device.location }}</span>
        <Tag v-if="device.alert" severity="danger" value="ALERT" />
      </div>
    </template>

    <div class="readouts" v-if="live">
      <div class="ro">
        <div class="k">Power</div>
        <div class="v" :class="{ hot: powerHot }">{{ Math.round(live.power) }} W</div>
      </div>
      <div class="ro">
        <div class="k">Temperature</div>
        <div class="v" :class="{ hot: tempHot }">{{ Math.round(live.temperature) }} °C</div>
      </div>
      <div class="ro muted">
        <div class="k">Updated</div>
        <div class="v small">{{ new Date(live.timestamp).toLocaleTimeString() }}</div>
      </div>
      <div class="live"><span class="dot" /> LIVE</div>
    </div>

    <div v-if="loading && !points.length" class="state">Loading telemetry…</div>
    <div v-else-if="!points.length" class="state">No telemetry in the last {{ WINDOW_S }}s for this device.</div>
    <v-chart v-else class="chart" :option="option" autoresize />

    <div class="caption" v-if="points.length">
      Last {{ WINDOW_S }}s · polls every {{ POLL_MS / 1000 }}s · dashed = 10s avg · flat line = alert limit (red when breached)
    </div>
  </Dialog>
</template>

<style scoped>
.hdr {
  display: flex;
  align-items: baseline;
  gap: 12px;
}
.hdr .id {
  font-family: ui-monospace, Menlo, Consolas, monospace;
  font-size: 18px;
}
.hdr .label {
  color: var(--text-muted);
  font-size: 13px;
}
.readouts {
  display: flex;
  align-items: center;
  gap: 28px;
  margin-bottom: 8px;
}
.ro .k {
  color: var(--text-muted);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.ro .v {
  font-size: 26px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.ro .v.small {
  font-size: 16px;
  font-weight: 500;
}
.ro .v.hot {
  color: #f87171;
}
.live {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 6px;
  color: #4ade80;
  font-size: 12px;
  letter-spacing: 0.08em;
}
.live .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #4ade80;
  animation: pulse 1.6s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.25; }
}
.chart {
  height: 360px;
  width: 100%;
}
.state {
  height: 360px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
}
.caption {
  color: var(--text-muted);
  font-size: 12px;
  margin-top: 6px;
}
</style>
