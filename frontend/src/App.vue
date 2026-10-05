<template>
  <div class="app">
    <header>
      <h1>场地挖填量 TIN 计算系统</h1>
      <span class="pill">SciPy Delaunay · Shapely 限定边界 · TIN 精确积分</span>
      <span class="disclaimer">
        ⚠ 软件算例结果，仅供设计与方案比选；正式工程量以现场实测、
        监理与造价计量认定为准。
      </span>
    </header>

    <div class="main">
      <!-- ============ 左侧栏 ============ -->
      <aside class="sidebar">
        <div class="card">
          <h3>1 · 选择算例</h3>
          <div class="row">
            <select v-model="caseKey" @change="onCaseChange">
              <option v-for="c in cases" :key="c.key" :value="c.key">
                {{ c.name }}
              </option>
            </select>
            <button class="primary" style="max-width:110px"
                    :disabled="loading" @click="run">
              {{ loading ? '计算中…' : '计算' }}
            </button>
          </div>
          <p class="muted" style="margin:8px 0 0" v-if="caseMeta">
            {{ caseMeta.expected_note ||
               `手算理论值：挖 ${caseMeta.expected?.cut_volume_m3} m³，` +
               `填 ${caseMeta.expected?.fill_volume_m3} m³` }}
          </p>
        </div>

        <template v-if="result">
          <div class="card">
            <h3>2 · 挖填汇总（挖、填分别积分）</h3>
            <div class="kpi">
              <div class="box cut">
                <div class="label">挖方量</div>
                <div class="num">{{ fmt(v.cut_volume_m3) }}</div>
                <div class="unit">m³</div>
              </div>
              <div class="box fill">
                <div class="label">填方量</div>
                <div class="num">{{ fmt(v.fill_volume_m3) }}</div>
                <div class="unit">m³</div>
              </div>
            </div>
            <div class="grid2" style="margin-top:10px">
              <span class="k">净体积（仅参考）</span>
              <span>{{ fmt(v.net_volume_m3) }} m³</span>
              <span class="k">总搬运量 挖+填</span>
              <span><b>{{ fmt(v.gross_movement_m3) }}</b> m³</span>
              <span class="k">已评价面积</span>
              <span>{{ fmt(v.area_evaluated_m2) }} m²</span>
              <span class="k">未评价（不外推）</span>
              <span :style="{color: v.area_not_evaluated_m2 > 0 ? 'var(--warn)' : undefined}">
                {{ fmt(v.area_not_evaluated_m2) }} m²
              </span>
            </div>
            <p class="muted" style="margin:8px 0 0">
              净体积为 {{ fmt(v.net_volume_m3) }} m³ 不代表无工程量——同时存在的
              挖 {{ fmt(v.cut_volume_m3) }} m³ 与填 {{ fmt(v.fill_volume_m3) }} m³
              必须分别计列。
            </p>
          </div>

          <div class="card">
            <h3>3 · 数据质量与三角网问题清单</h3>
            <template v-for="role in ['ground','design']" :key="role">
              <template v-if="result.quality[role]">
                <p class="muted" style="margin:6px 0">
                  {{ role === 'ground' ? '原地面' : '设计面' }}：
                  有效 {{ result.quality[role].summary.used_for_tin }}
                  /{{ result.quality[role].summary.total }} 点
                  <span class="tag" :class="issues(role).length ? 'bad':'ok'">
                    {{ issues(role).length ? issues(role).length + ' 个问题':'通过' }}
                  </span>
                </p>
                <div v-for="(q, i) in issues(role)" :key="role+i" class="issue">
                  <span class="t">{{ typeName(q.type) }}</span>{{ q.message }}
                </div>
              </template>
            </template>
            <p class="muted" style="margin:6px 0" v-for="(n,i) in result.tin.ground.boundary_notes" :key="'n'+i">
              • {{ n }}
            </p>
            <p class="muted" style="margin:6px 0">
              退化三角片 {{ result.tin.ground.degraded.length }} 个，
              被拒绝三角片：
              <span v-for="r in result.tin.ground.rejected" :key="r.reason">
                {{ r.reason.replaceAll('_',' ') }} {{ r.count }}；
              </span>
              内部缺测面积
              <b :style="{color: result.tin.ground.interior_gap_area_m2>0?'var(--warn)':undefined}">
                {{ result.tin.ground.interior_gap_area_m2 }} m²</b>。
            </p>
          </div>

          <div class="card">
            <h3>4 · 网格精度对比</h3>
            <table>
              <thead><tr>
                <th>方法</th><th>挖 m³</th><th>填 m³</th><th>对 TIN 偏差</th>
              </tr></thead>
              <tbody>
                <tr>
                  <td><b>TIN 精确</b></td>
                  <td>{{ fmt(v.cut_volume_m3) }}</td>
                  <td>{{ fmt(v.fill_volume_m3) }}</td><td>—</td>
                </tr>
                <tr v-for="g in result.grid_compare" :key="g.method">
                  <td>{{ g.method }}</td>
                  <td>{{ fmt(g.cut_volume_m3) }}</td>
                  <td>{{ fmt(g.fill_volume_m3) }}</td>
                  <td :style="{color: Math.abs(g.cut_volume_m3 - v.cut_volume_m3)>0.01 ? 'var(--warn)':'var(--ok)'}">
                    {{ (g.cut_volume_m3 + g.fill_volume_m3
                        - v.cut_volume_m3 - v.fill_volume_m3).toFixed(1) }} m³
                  </td>
                </tr>
              </tbody>
            </table>
            <p class="muted" style="margin:6px 0 0">
              网格越细越趋近 TIN 精确值；粗网格在零线/边界处有 stair-step 误差，
              可据此评估计量精度对网格步长的敏感性。
            </p>
          </div>

          <div class="card" v-if="result.scheme_id || result.expected">
            <h3>基准与方案</h3>
            <div class="grid2">
              <span class="k">平面基准</span><span>EPSG:{{ result.crs.epsg }}（米）</span>
              <span class="k">高程基准</span><span>{{ result.crs.vertical_datum }}</span>
              <span class="k">方案编号</span>
              <span>{{ result.scheme_id ? '#' + result.scheme_id : '未入库' }}</span>
            </div>
            <p class="muted" style="margin:6px 0" v-for="(n,i) in result.datum_notes" :key="i">
              • {{ n }}
            </p>
          </div>
        </template>
      </aside>

      <!-- ============ 右侧视图 ============ -->
      <section class="view">
        <div class="tabs">
          <button :class="{ active: tab==='3d' }" @click="tab='3d'">三维曲面</button>
          <button :class="{ active: tab==='sec' }" @click="tab='sec'">断面</button>
          <button :class="{ active: tab==='drill' }" @click="tab='drill'">
            三角片/积分单元下钻
          </button>
          <button :class="{ active: tab==='schemes' }" @click="tab='schemes'; loadSchemes()">
            已存方案
          </button>
        </div>
        <div class="canvas-wrap">
          <ThreeScene v-if="tab==='3d' && result" :result="result"
                      @select-tri="selectTri" />
          <div v-else-if="tab==='3d'" class="muted" style="padding:30px">
            请先在左侧选择算例并点击“计算”。
          </div>

          <div v-if="tab==='sec'" style="position:absolute;inset:0;overflow:auto;padding:16px">
            <SectionChart v-if="result" :sections="result.sections" />
            <p v-else class="muted">请先计算方案。</p>
          </div>

          <div v-if="tab==='drill'" style="position:absolute;inset:0;overflow:auto;padding:16px">
            <DrillTable v-if="result" :result="result"
                        :selected-tri="selectedTri"
                        @select="selectTri" @clear="selectedTri=null" />
          </div>

          <div v-if="tab==='schemes'" style="position:absolute;inset:0;overflow:auto;padding:16px">
            <table>
              <thead><tr>
                <th>#</th><th>方案名</th><th>时间</th><th>挖 m³</th>
                <th>填 m³</th><th>净 m³</th><th>存储</th>
              </tr></thead>
              <tbody>
                <tr v-for="s in schemes" :key="s.id" style="cursor:pointer"
                    @click="openScheme(s.id)">
                  <td>{{ s.id }}</td><td style="text-align:left">{{ s.name }}</td>
                  <td>{{ s.created_at }}</td>
                  <td>{{ fmt(s.volume.cut_volume_m3) }}</td>
                  <td>{{ fmt(s.volume.fill_volume_m3) }}</td>
                  <td>{{ fmt(s.volume.net_volume_m3) }}</td>
                  <td><span class="pill">{{ s.backend }}</span></td>
                </tr>
              </tbody>
            </table>
            <p class="muted" style="margin-top:10px">
              配置 DATABASE_URL（postgresql://…）并在库中 CREATE EXTENSION postgis
              后自动切换到 PostgreSQL/PostGIS 存储；当前为无数据库时的 JSON 落盘模式。
            </p>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { api } from './api'
import ThreeScene from './components/ThreeScene.vue'
import SectionChart from './components/SectionChart.vue'
import DrillTable from './components/DrillTable.vue'

const cases = ref([])
const caseKey = ref('slope')
const caseMeta = ref(null)
const result = ref(null)
const loading = ref(false)
const tab = ref('3d')
const selectedTri = ref(null)
const schemes = ref([])
const error = ref('')

const v = computed(() => result.value?.volume || {})
const fmt = x => (x == null ? '—' : Number(x).toLocaleString('zh-CN',
  { minimumFractionDigits: 1, maximumFractionDigits: 1 }))

const TYPE_NAMES = {
  duplicate_xyz: '完全重复点', z_conflict: '高程冲突',
  nonfinite: '非法值', outside_boundary: '边界外点',
}
const typeName = t => TYPE_NAMES[t] || t
const issues = role => result.value?.quality[role]?.issues || []

async function loadCases() {
  cases.value = await api.cases()
  await onCaseChange()
}

async function onCaseChange() {
  caseMeta.value = cases.value.find(c => c.key === caseKey.value)
}

async function run() {
  loading.value = true; error.value = ''
  selectedTri.value = null
  try {
    result.value = await api.computeCase(caseKey.value)
  } catch (e) {
    alert('计算失败：' + e.message)
  } finally {
    loading.value = false
  }
}

function selectTri(k) {
  selectedTri.value = k
  tab.value = 'drill'
}

async function loadSchemes() {
  schemes.value = await api.schemes()
}

async function openScheme(id) {
  const row = await api.scheme(id)
  result.value = row.result
  caseKey.value = ''
  caseMeta.value = null
  tab.value = '3d'
}

onMounted(loadCases)
</script>
