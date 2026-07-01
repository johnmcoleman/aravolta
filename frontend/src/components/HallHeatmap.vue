<script setup lang="ts">
import type { ZoneStat } from '../api'

// Facility-at-a-glance: one tile per hall, coloured by its share of racks in
// alert (green -> red). Always shows every hall; click a tile to filter.
defineProps<{ stats: ZoneStat[]; selected: string | null }>()
const emit = defineEmits<{ select: [string] }>()

function color(s: ZoneStat): string {
  const share = s.total ? s.alerts / s.total : 0
  const t = Math.min(share / 0.25, 1) // 0 = none, 1 = >=25% of the hall in alert
  const hue = 140 - 140 * t // 140° green -> 0° red
  return `hsl(${hue}, 55%, 20%)`
}
</script>

<template>
  <div class="heatmap" v-if="stats.length">
    <button
      v-for="s in stats"
      :key="s.zone"
      class="tile"
      :class="{ sel: selected === s.zone }"
      :style="{ background: color(s) }"
      @click="emit('select', s.zone)"
    >
      <div class="z">{{ s.zone }}</div>
      <div class="a">{{ s.alerts }} <span>in alert</span></div>
      <div class="t">
        {{ s.avgTemperature == null ? '—' : Math.round(s.avgTemperature) + ' °C' }} · {{ s.total }} racks
      </div>
    </button>
  </div>
</template>

<style scoped>
.heatmap {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 10px;
}
.tile {
  text-align: left;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 14px;
  color: var(--text);
  cursor: pointer;
  font: inherit;
  transition: outline-color 0.15s;
}
.tile.sel {
  outline: 2px solid #e5e5e5;
}
.z {
  font-weight: 600;
}
.a {
  font-size: 22px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  margin-top: 4px;
}
.a span {
  font-size: 12px;
  font-weight: 400;
  color: var(--text-muted);
}
.t {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 2px;
}
@media (max-width: 900px) {
  .heatmap {
    grid-template-columns: repeat(3, 1fr);
  }
}
</style>
