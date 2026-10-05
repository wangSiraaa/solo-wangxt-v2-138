<template>
  <div class="app">
    <header>
      <h1>土方挖填量计算系统</h1>
      <span class="sub">限定 TIN（SciPy + Shapely）· 挖填分别积分 · 断面/网格对比 · 不下钻不计量认定</span>
    </header>

    <div class="toolbar">
      <label>算例
        <select v-model="caseKey" @change="loadCase">
          <option v-for="c in cases" :key="c.key" :value="c.key">{{ c.name }}</option>
        </select>
      </label>
      <label>网格边长 <input type="number" v-model.number="opts.grid_size" min="1" /> m</label>
      <label>断面间距 <input type="number" v-model.number="opts.section_spacing" min="1" /> m</label>
      <label>显示
        <select v-model="surface">
          <option value="ground">原地面曲面</option>
          <option value="design">设计地面曲面</option>
          <option value="diff">挖填差值面</option>
        </select>
      </label>
      <label class="ck"><input type="checkbox" v-model="showWire" /> TIN 网</label>
      <label class="ck"><input type="checkbox" v-model="showPoints" /> 测点</label>
      <button @click="run" :disabled="loading">{{ loading ? '计算中…' : '计算挖填量' }}</button>
      <button class="ghost" @click="showUpload = !showUpload">导入XYZ点</button>
      <span class="backend">存储：{{ backend }}</span>
    </div>

    <div v-if="showUpload" class="upload">
      <h3>导入高程点（XYZ/CSV：每行 x,y,z[,编码]，逗号或空白分隔）</h3>
      <div class="uprow">
        <label>原地面 <input type="file" @change="f => pickFile(f, 'ground')" accept=".xyz,.csv,.txt" /></label>
        <label>设计面 <input type="file" @change="f => pickFile(f, 'design')" accept=".xyz,.csv,.txt" /></label>
        <label>源坐标系EPSG <input v-model="upCrs.src" placeholder="如 EPSG:32650" style="width:120px" /></label>
        <label>目标EPSG <input v-model="upCrs.dst" placeholder="如 EPSG:4547" style="width:120px" /></label>
        <button @click="runCustom" :disabled="!uploads.ground || !uploads.design">用导入点计算</button>
        <span class="muted">{{ uploadMsg }}</span>
      </div>
      <p class="muted">高程基准不做数学猜测：两组数据高程基准不同时，请先做水准联测改算后再导入。</p>
    </div>

    <div v-if="err" class="error">{{ err }}</div>

    <div class="layout" v-if="result">
      <div class="left">
        <div class="viewer-wrap">
          <ThreeScene :result="result" :surface="surface" :show-wire="showWire"
                      :show-points="showPoints" :z-scale="zScale" @pick="picked = $event" />
          <div class="legend3d">
            <i class="cut"></i>挖方区 <i class="fill"></i>填方区
            <i class="orange"></i>对照曲面线框
            <i class="gray"></i>孔洞边界 <i class="violet"></i>缺测范围
            <label>竖向放大 <input type="range" min="1" max="40" v-model.number="zScale" /></label>
          </div>
        </div>
        <SectionChart :sections="result.sections" />
      </div>

      <div class="right">
        <div class="cards">
          <div class="card cut"><b>挖方</b><span>{{ fmt(t.cut) }}</span><i>m³</i></div>
          <div class="card fill"><b>填方</b><span>{{ fmt(t.fill) }}</span><i>m³</i></div>
          <div class="card"><b>净量(仅参考)</b><span :class="{warn: t.net}">{{ fmt(t.net) }}</span><i>m³</i></div>
          <div class="card"><b>计算面积</b><span>{{ fmt(t.area) }}</span><i>m²</i></div>
          <div class="card"><b>挖区/填区面积</b>
            <span>{{ fmt(t.area_cut) }} / {{ fmt(t.area_fill) }}</span><i>m²</i></div>
          <div class="card"><b>最大挖深/填高</b>
            <span>{{ fmt(t.max_depth_cut) }} / {{ fmt(t.max_depth_fill) }}</span><i>m</i></div>
        </div>
        <p class="hint">挖方与填方分别积分；净量列只作平衡参考，
          不得用净体积抵消掩盖大量同时挖填。</p>

        <h3>三种口径并列（不得用净量合并挖填）</h3>
        <table class="grid">
          <thead><tr><th>方法</th><th>挖方 m³</th><th>填方 m³</th><th>净量(参考)</th><th>相对TIN挖差</th><th>相对TIN填差</th></tr></thead>
          <tbody>
            <tr class="main"><td>TIN 精确积分</td><td>{{ fmt(t.cut, 2) }}</td><td>{{ fmt(t.fill, 2) }}</td>
              <td>{{ fmt(t.net, 2) }}</td><td>基准</td><td>基准</td></tr>
            <tr v-for="g in result.grid_compare" :key="'g'+g.size">
              <td>角点法 {{ g.size }}m</td><td>{{ fmt(g.cut, 2) }}</td><td>{{ fmt(g.fill, 2) }}</td>
              <td>{{ fmt(g.net, 2) }}</td>
              <td :class="diffCls(g.rel_cut_pct)">{{ fmt(g.rel_cut_pct, 2) }}%</td>
              <td :class="diffCls(g.rel_fill_pct)">{{ fmt(g.rel_fill_pct, 2) }}%</td></tr>
            <tr v-if="sv.n">
              <td>断面法({{ result.sections.length }}条×间距)</td>
              <td>{{ fmt(sv.cut, 2) }}</td><td>{{ fmt(sv.fill, 2) }}</td>
              <td>{{ fmt(sv.cut - sv.fill, 2) }}</td>
              <td>{{ fmt(100 * (sv.cut - t.cut) / (t.cut || 1), 2) }}%</td>
              <td>{{ fmt(100 * (sv.fill - t.fill) / (t.fill || 1), 2) }}%</td></tr>
          </tbody>
        </table>
        <p class="hint">断面线间距 {{ opts.section_spacing }} m；断面法只在线间线性过渡，
          端部与孔洞处理较粗，适合规则地形复核，精确量以 TIN 分片积分为准。</p>

        <h3>数据检查（{{ result.issues.length }}）</h3>
        <ul class="issues">
          <li v-for="(q, i) in result.issues" :key="i" :class="q.severity">
            [{{ label(q.severity) }}] {{ q.message }}</li>
          <li v-if="!result.issues.length" class="ok">未发现重复点、退化片或越界点。</li>
        </ul>
        <p v-if="result.uncovered_area > 0.5" class="warn2">
          有 {{ fmt(result.uncovered_area) }} m² 原地面片落在设计面数据覆盖外，未参与计算（不外推）。</p>

        <h3>三角片下钻（共 {{ result.facets.length }} 片，可从汇总追到片）</h3>
        <input class="filter" placeholder="筛选：挖/填 关键词，如 cut / fill"
               v-model="facetFilter" />
        <div class="facets">
          <table>
            <thead><tr><th>#</th><th>面积</th><th>挖m³</th><th>填m³</th><th>三点挖填深dz(m)</th><th>原地面片</th></tr></thead>
            <tbody>
              <tr v-for="f in filteredFacets.slice(0, 200)" :key="f.facet_id"
                  :class="{sel: picked && picked.facet_id === f.facet_id}"
                  @click="picked = f">
                <td>{{ f.facet_id }}</td>
                <td>{{ fmt(f.area, 1) }}</td>
                <td class="cut-t">{{ fmt(f.cut, 2) }}</td>
                <td class="fill-t">{{ fmt(f.fill, 2) }}</td>
                <td>[{{ f.dz.map(v => fmt(v, 2)).join(', ') }}]</td>
                <td>{{ f.source_ground_tri.join('/') }}</td>
              </tr>
            </tbody>
          </table>
          <div v-if="filteredFacets.length > 200" class="muted">
            仅显示前 200 片，请用筛选缩小（合计仍以全部片积分）。</div>
        </div>

        <div v-if="picked" class="facet-detail">
          <h4>三角片 #{{ picked.facet_id }} 明细 <button @click="picked=null">×</button></h4>
          <table>
            <tr><th>顶点(x,y)</th><th>原地面z</th><th>设计z</th><th>dz</th></tr>
            <tr v-for="(v, i) in picked.vertices" :key="i">
              <td>{{ fmt(v[0], 2) }}, {{ fmt(v[1], 2) }}</td>
              <td>{{ fmt(picked.z_ground[i], 3) }}</td>
              <td>{{ fmt(picked.z_design[i], 3) }}</td>
              <td :class="picked.dz[i] >= 0 ? 'cut-t' : 'fill-t'">
                {{ fmt(picked.dz[i], 3) }}</td>
            </tr>
          </table>
          <p>片面积 {{ fmt(picked.area, 3) }} m² ·
            该片挖 {{ fmt(picked.cut, 3) }} m³ · 填 {{ fmt(picked.fill, 3) }} m³</p>
        </div>

        <div class="disclaimer">⚠ {{ result.disclaimer }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api, fmt } from './api'
import ThreeScene from './components/ThreeScene.vue'
import SectionChart from './components/SectionChart.vue'

const cases = ref([])
const caseKey = ref('plane')
const result = ref(null)
const loading = ref(false)
const err = ref('')
const backend = ref('…')
const surface = ref('ground')
const showWire = ref(true)
const showPoints = ref(true)
const zScale = ref(10)
const picked = ref(null)
const facetFilter = ref('')
const showUpload = ref(false)
const uploads = reactive({ ground: null, design: null })
const upCrs = reactive({ src: '', dst: '' })
const uploadMsg = ref('')
const opts = reactive({ grid_size: 20, section_spacing: 50 })

const t = computed(() => result.value.totals)
const sv = computed(() => result.value.section_volume || {})

const filteredFacets = computed(() => {
  const fs = result.value?.facets ?? []
  const q = facetFilter.value.trim().toLowerCase()
  if (!q) return fs
  if (q === 'cut') return fs.filter(f => f.cut > 1e-9)
  if (q === 'fill') return fs.filter(f => f.fill > 1e-9)
  return fs
})

function diffCls(v) { return Math.abs(v) > 10 ? 'baddiff' : '' }
function label(s) { return { error: '错误', warning: '警告', info: '提示' }[s] || s }

async function loadCase() {
  err.value = ''
  try { await run() } catch (e) { err.value = e.message }
}

async function run() {
  loading.value = true; err.value = ''
  try {
    const project = await api.caseData(caseKey.value)
    const r = await api.compute(project, {
      grid_size: opts.grid_size,
      section_spacing: opts.section_spacing
    })
    result.value = r.result
    picked.value = null
  } catch (e) { err.value = e.message } finally { loading.value = false }
}

async function pickFile(ev, surface) {
  const file = ev.target.files[0]
  if (!file) return
  err.value = ''
  try {
    const r = await api.uploadXyz(file, surface, upCrs.src || null, upCrs.dst || null)
    uploads[surface] = r.points
    uploadMsg.value = `原地面 ${uploads.ground?.length ?? 0} 点 / 设计面 ${uploads.design?.length ?? 0} 点`
  } catch (e) { err.value = e.message }
}

async function runCustom() {
  loading.value = true; err.value = ''
  try {
    const project = {
      name: '导入点计算（统一基准需用户确认）',
      points: [...(uploads.ground || []), ...(uploads.design || [])],
      datum: { horizontal_crs: upCrs.dst || null, vertical_datum: '需确认', units: 'm' }
    }
    const r = await api.compute(project, {
      grid_size: opts.grid_size,
      section_spacing: opts.section_spacing
    })
    result.value = r.result
    picked.value = null
  } catch (e) { err.value = e.message } finally { loading.value = false }
}

onMounted(async () => {
  cases.value = await api.cases()
  const h = await api.health()
  backend.value = h.storage_backend
  await run()
})
</script>
