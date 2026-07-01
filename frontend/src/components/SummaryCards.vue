<script setup lang="ts">
import type { Summary } from '../api'

// Aggregates are computed server-side (GET /api/summary), so the cards are
// correct for the whole fleet without shipping every device to the browser.
defineProps<{ summary: Summary | null }>()

const fmt = (v: number | null | undefined, unit: string) =>
  v == null ? '—' : `${Math.round(v)}${unit}`
</script>

<template>
  <div class="cards">
    <div class="card">
      <div class="label">Racks</div>
      <div class="value">{{ summary?.total ?? '—' }}</div>
      <div class="sub">{{ summary?.online ?? 0 }} online · {{ summary?.offline ?? 0 }} offline</div>
    </div>
    <div class="card" :class="{ danger: (summary?.alerts ?? 0) > 0 }">
      <div class="label">In alert</div>
      <div class="value">{{ summary?.alerts ?? '—' }}</div>
      <div class="sub">power / temperature thresholds</div>
    </div>
    <div class="card">
      <div class="label">Avg power</div>
      <div class="value">{{ fmt(summary?.avgPower, ' W') }}</div>
      <div class="sub">across reporting racks</div>
    </div>
    <div class="card">
      <div class="label">Avg temperature</div>
      <div class="value">{{ fmt(summary?.avgTemperature, ' °C') }}</div>
      <div class="sub">across reporting racks</div>
    </div>
  </div>
</template>

<style scoped>
.cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.card {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px 18px;
}
.card.danger {
  border-color: #b91c1c;
}
.label {
  color: var(--text-muted);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.value {
  font-size: 30px;
  font-weight: 600;
  margin: 6px 0 2px;
  font-variant-numeric: tabular-nums;
}
.card.danger .value {
  color: #f87171;
}
.sub {
  color: var(--text-muted);
  font-size: 12px;
}
@media (max-width: 900px) {
  .cards {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
