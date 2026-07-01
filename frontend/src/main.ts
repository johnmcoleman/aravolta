import { createApp } from 'vue'
import './style.css'
import App from './App.vue'

import PrimeVue from 'primevue/config'
import Aura from '@primevue/themes/aura'

// ECharts: import only the pieces we use (tree-shaken) and register them once.
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, MarkLineComponent } from 'echarts/components'
import VChart from 'vue-echarts'

// MarkLineComponent is required for the chart's alert-threshold lines.
use([CanvasRenderer, LineChart, GridComponent, TooltipComponent, LegendComponent, MarkLineComponent])

const app = createApp(App)
// Styled mode with the Aura preset; `.dark` on <html> activates dark tokens.
app.use(PrimeVue, { theme: { preset: Aura, options: { darkModeSelector: '.dark' } } })
app.component('VChart', VChart)
app.mount('#app')
