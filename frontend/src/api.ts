// Typed client for the backend. All calls go through the Vite proxy (/api ->
// FastAPI), so the UI always consumes the real API — never hardcoded data.

export interface Reading {
  power: number
  temperature: number
  timestamp: string
}

export interface Device {
  deviceId: string
  label: string | null
  location: string | null
  powerLimit: number
  tempLimit: number
  online: boolean
  alert: boolean
  alertReasons: string[]
  latest: Reading | null
}

export interface DevicePage {
  total: number
  devices: Device[]
}

export interface ZoneStat {
  zone: string
  total: number
  alerts: number
  avgTemperature: number | null
}

export interface Summary {
  total: number
  online: number
  offline: number
  alerts: number
  avgPower: number | null
  avgTemperature: number | null
  zones: string[]
  zoneStats: ZoneStat[]
}

export interface DeviceQuery {
  limit: number
  offset: number
  q?: string
  zone?: string | null
  status?: string
  sort?: string
  order?: 'asc' | 'desc'
}

async function getJSON<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

/** One page of the fleet, filtered/sorted server-side. Returns {total, devices}
 *  so the browser only ever holds a page — this scales to very large fleets. */
export const listDevices = (query: DeviceQuery) => {
  const p = new URLSearchParams()
  p.set('limit', String(query.limit))
  p.set('offset', String(query.offset))
  if (query.q) p.set('q', query.q)
  if (query.zone) p.set('zone', query.zone)
  if (query.status && query.status !== 'all') p.set('status', query.status)
  if (query.sort) p.set('sort', query.sort)
  if (query.order) p.set('order', query.order)
  return getJSON<DevicePage>(`/api/devices?${p.toString()}`)
}

/** Fleet aggregates computed server-side, scoped by the same q/zone filters as
 *  the table (powers the summary cards + the global zones list). */
export const getSummary = (query?: { q?: string; zone?: string | null }) => {
  const p = new URLSearchParams()
  if (query?.q) p.set('q', query.q)
  if (query?.zone) p.set('zone', query.zone)
  const qs = p.toString()
  return getJSON<Summary>(`/api/summary${qs ? '?' + qs : ''}`)
}

/** Latest reading for one device (cache-served). Powers the live headline. */
export const getLive = (id: string) =>
  getJSON<Reading>(`/api/devices/${encodeURIComponent(id)}/live`)

/** Time-window history for the chart; defaults to the last 60 seconds. */
export const getMetrics = (id: string, seconds = 60) =>
  getJSON<Reading[]>(`/api/devices/${encodeURIComponent(id)}/metrics?seconds=${seconds}`)
