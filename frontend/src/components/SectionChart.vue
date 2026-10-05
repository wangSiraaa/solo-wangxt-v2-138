<template>
  <div>
    <div class="section-select" v-if="sections.length">
      <select v-model="idx">
        <option v-for="(s, i) in sections" :key="i" :value="i">{{ s.name }}</option>
      </select>
    </div>
    <canvas ref="cv" :height="360" style="width:100%;background:#0f1420"></canvas>
    <div v-if="sec" class="grid2" style="margin-top:8px">
      <span class="k">断面挖方面积</span><span><span class="tag cut">{{ sec.cut_area_m2 }} m²</span></span>
      <span class="k">断面填方面积</span><span><span class="tag fill">{{ sec.fill_area_m2 }} m²</span></span>
      <span class="k">双侧有效桩号</span><span>{{ sec.valid_range_m[0] }}–{{ sec.valid_range_m[1] }} m</span>
    </div>
    <div v-for="(w, i) in sec?.warnings || []" :key="i" class="issue" style="margin-top:8px">
      <span class="t">提示</span>{{ w }}
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'

const props = defineProps({ sections: { type: Array, default: () => [] } })
const cv = ref(null)
const idx = ref(0)
const sec = ref(null)

function draw() {
  const canvas = cv.value
  if (!canvas) return
  const s = props.sections[idx.value]
  sec.value = s
  const dpr = Math.min(window.devicePixelRatio, 2)
  const W = canvas.clientWidth || 800
  const H = 360
  canvas.width = W * dpr; canvas.height = H * dpr
  const ctx = canvas.getContext('2d')
  ctx.scale(dpr, dpr)
  ctx.clearRect(0, 0, W, H)
  if (!s) {
    ctx.fillStyle = '#93a0b8'; ctx.font = '13px sans-serif'
    ctx.fillText('该方案未定义断面线。', 20, 30)
    return
  }

  const pad = { l: 56, r: 18, t: 18, b: 34 }
  const n = s.stations.length
  const xAt = i => pad.l + (s.stations[i] / s.stations[n - 1]) * (W - pad.l - pad.r)
  const zvals = []
  for (let i = 0; i < n; i++) {
    if (s.ground_z[i] != null) zvals.push(s.ground_z[i])
    if (s.design_z[i] != null) zvals.push(s.design_z[i])
  }
  let zmin = Math.min(...zvals), zmax = Math.max(...zvals)
  if (zmax - zmin < 1e-6) { zmin -= 1; zmax += 1 }
  const padz = (zmax - zmin) * 0.12
  zmin -= padz; zmax += padz
  const yAt = z => H - pad.b - ((z - zmin) / (zmax - zmin)) * (H - pad.t - pad.b)

  // 网格与坐标轴
  ctx.strokeStyle = '#232d42'; ctx.lineWidth = 1
  ctx.fillStyle = '#93a0b8'; ctx.font = '11px sans-serif'
  for (let g = 0; g <= 4; g++) {
    const y = pad.t + g * (H - pad.t - pad.b) / 4
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke()
    const z = zmax - g * (zmax - zmin) / 4
    ctx.fillText(z.toFixed(2) + ' m', 8, y + 3)
  }
  for (let g = 0; g <= 5; g++) {
    const st = s.stations[n - 1] * g / 5
    const x = pad.l + g * (W - pad.l - pad.r) / 5
    ctx.fillText(st.toFixed(0), x - 10, H - pad.b + 16)
  }

  // 挖填区域填充（两线之间），缺测段断开
  for (let i = 1; i < n; i++) {
    if (s.ground_z[i - 1] == null || s.design_z[i - 1] == null ||
        s.ground_z[i] == null || s.design_z[i] == null) continue
    const x0 = xAt(i - 1), x1 = xAt(i)
    const g0 = yAt(s.ground_z[i - 1]), g1 = yAt(s.ground_z[i])
    const d0 = yAt(s.design_z[i - 1]), d1 = yAt(s.design_z[i])
    const cut = (s.ground_z[i - 1] - s.design_z[i - 1]) +
                (s.ground_z[i] - s.design_z[i]) > 0
    ctx.fillStyle = cut ? 'rgba(212,87,74,.30)' : 'rgba(59,125,216,.30)'
    ctx.beginPath()
    ctx.moveTo(x0, g0); ctx.lineTo(x1, g1); ctx.lineTo(x1, d1); ctx.lineTo(x0, d0)
    ctx.closePath(); ctx.fill()
  }

  const line = (arr, color, dash = []) => {
    ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.setLineDash(dash)
    ctx.beginPath()
    let pen = false
    for (let i = 0; i < n; i++) {
      if (arr[i] == null) { pen = false; continue }
      const x = xAt(i), y = yAt(arr[i])
      pen ? ctx.lineTo(x, y) : ctx.moveTo(x, y)
      pen = true
    }
    ctx.stroke(); ctx.setLineDash([])
  }
  line(s.ground_z, '#e6ebf5')
  line(s.design_z, '#ffd66b', [7, 5])

  // 缺测段顶部标注
  for (let i = 0; i < n; i++) {
    if (s.ground_z[i] == null) {
      ctx.fillStyle = 'rgba(85,94,112,.25)'
      const x = xAt(i)
      ctx.fillRect(x - 2, pad.t, 4, H - pad.t - pad.b)
    }
  }

  // 图例
  ctx.font = '12px sans-serif'
  ctx.fillStyle = '#e6ebf5'; ctx.fillText('━ 原地面', W - 170, pad.t + 4)
  ctx.fillStyle = '#ffd66b'; ctx.fillText('┅ 设计面', W - 96, pad.t + 4)
}

watch(idx, draw)
watch(() => props.sections, () => { idx.value = 0; draw() })
onMounted(draw)
</script>
