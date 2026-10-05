<template>
  <div class="sec">
    <div class="sec-head">
      <select v-model="idx" @change="draw">
        <option v-for="(s, i) in sections" :key="i" :value="i">{{ s.name }}</option>
      </select>
      <span class="muted">断面挖方面积 {{ fmt(sec.cut_area, 2) }} m² ·
        填方面积 {{ fmt(sec.fill_area, 2) }} m² · 桩长 {{ fmt(sec.length, 1) }} m</span>
    </div>
    <canvas ref="cv" width="900" height="260"></canvas>
    <div class="legend">
      <i class="cut"></i>挖（原地面＞设计）
      <i class="fill"></i>填
      <i class="gline"></i>原地面线
      <i class="dline"></i>设计线
      <span class="muted">（虚线表示缺测不连线、不外推）</span>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { fmt } from '../api'

const props = defineProps({ sections: { type: Array, required: true } })
const cv = ref(null)
const idx = ref(0)
const sec = computed(() => props.sections[idx.value] ?? {
  s: [], z_ground: [], z_design: [], cut_area: 0, fill_area: 0, length: 0 })

function draw() {
  const c = cv.value
  if (!c) return
  const ctx = c.getContext('2d')
  const W = c.width, H = c.height, M = 46
  ctx.clearRect(0, 0, W, H)
  const s = sec.value
  if (!s.s?.length) {
    ctx.fillStyle = '#888'; ctx.font = '14px sans-serif'
    ctx.fillText('无断面数据', W / 2 - 40, H / 2)
    return
  }
  const zg = s.z_ground, zd = s.z_design, ss = s.s
  const zv = [...zg, ...zd].filter(v => v !== null)
  const zmin = Math.min(...zv) - 0.5, zmax = Math.max(...zv) + 0.5
  const X = v => M + (v / ss[ss.length - 1]) * (W - 2 * M)
  const Y = v => H - M - ((v - zmin) / (zmax - zmin)) * (H - 2 * M)

  // 网格/轴
  ctx.strokeStyle = '#e3e6e8'; ctx.lineWidth = 1
  for (let i = 0; i <= 5; i++) {
    const x = M + i * (W - 2 * M) / 5
    ctx.beginPath(); ctx.moveTo(x, M - 8); ctx.lineTo(x, H - M); ctx.stroke()
    ctx.fillStyle = '#999'; ctx.font = '11px sans-serif'
    ctx.fillText((ss[ss.length - 1] * i / 5).toFixed(0) + 'm', x - 12, H - M + 16)
  }
  for (let i = 0; i <= 4; i++) {
    const z = zmin + (zmax - zmin) * i / 4
    ctx.beginPath(); ctx.moveTo(M, Y(z)); ctx.lineTo(W - M, Y(z)); ctx.stroke()
    ctx.fillStyle = '#999'; ctx.fillText(z.toFixed(1), 6, Y(z) + 4)
  }

  // 挖填色块：按相邻采样点梯形
  for (let i = 0; i < ss.length - 1; i++) {
    if (zg[i] === null || zg[i + 1] === null || zd[i] === null || zd[i + 1] === null) continue
    const x0 = X(ss[i]), x1 = X(ss[i + 1])
    ctx.beginPath()
    ctx.moveTo(x0, Y(zg[i])); ctx.lineTo(x1, Y(zg[i + 1]))
    ctx.lineTo(x1, Y(zd[i + 1])); ctx.lineTo(x0, Y(zd[i])); ctx.closePath()
    ctx.fillStyle = 'rgba(192,57,43,0.18)'
    // 两条线交叉时简化为按平均差着色（精确以 TIN 积分量为准）
    const mean = (zg[i] + zg[i + 1] - zd[i] - zd[i + 1]) / 2
    ctx.fillStyle = mean >= 0 ? 'rgba(192,57,43,0.18)' : 'rgba(36,113,163,0.18)'
    ctx.fill()
  }

  const line = (arr, color, dash) => {
    ctx.beginPath(); ctx.lineWidth = 2
    ctx.setLineDash(dash ? [6, 5] : [])
    ctx.strokeStyle = color
    let pen = false
    arr.forEach((z, i) => {
      if (z === null) { pen = false; return }
      const x = X(ss[i]), y = Y(z)
      pen ? ctx.lineTo(x, y) : ctx.moveTo(x, y)
      pen = true
    })
    ctx.stroke(); ctx.setLineDash([])
  }
  line(zg, '#111', false)
  line(zd, '#e67e22', false)
}

onMounted(draw)
watch(() => props.sections, () => { idx.value = 0; draw() })
</script>

<style scoped>
.sec { border: 1px solid #e0e3e5; border-radius: 8px; padding: 8px 10px; background: #fff; }
.sec-head { display: flex; gap: 14px; align-items: center; margin-bottom: 4px; }
.muted { color: #888; font-size: 12px; }
.legend { display: flex; gap: 8px; align-items: center; font-size: 12px; color: #555; flex-wrap: wrap; }
.legend i { width: 16px; height: 4px; display: inline-block; border-radius: 2px; }
.legend .cut { background: #c0392b; } .legend .fill { background: #2471a3; }
.legend .gline { background: #111; } .legend .dline { background: #e67e22; }
canvas { width: 100%; height: 260px; }
</style>
