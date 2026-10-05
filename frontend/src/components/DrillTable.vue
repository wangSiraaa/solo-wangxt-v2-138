<template>
  <div>
    <div class="muted" style="margin-bottom:8px">
      从汇总量逐级下钻：点击三维地面三角片或下表行，可看到该三角片对应的全部
      积分单元（与设计三角片相交、按零线分割后的最小体积块）。
    </div>

    <div v-if="selectedTri != null" class="card" style="background:var(--bg)">
      <h3>
        地面三角片 #{{ selectedTri }} 的积分单元
        <span style="float:right;cursor:pointer;color:var(--muted)"
              @click="$emit('clear')">✕ 关闭</span>
      </h3>
      <table>
        <thead><tr>
          <th>单元</th><th>设计片</th><th>面积 m²</th>
          <th>挖 m³</th><th>填 m³</th><th>均高差 m</th>
        </tr></thead>
        <tbody>
          <tr v-for="c in cellsOfTri" :key="c.cell_id">
            <td>#{{ c.cell_id }}</td>
            <td>{{ c.design_tri === -1 ? '平面' : '#' + c.design_tri }}</td>
            <td>{{ c.area_m2 }}</td>
            <td><span class="tag cut">{{ c.cut_m3 }}</span></td>
            <td><span class="tag fill">{{ c.fill_m3 }}</span></td>
            <td>{{ c.mean_diff_m }}</td>
          </tr>
          <tr v-if="!cellsOfTri.length"><td colspan="6" class="muted">
            该三角片无积分单元（可能位于未覆盖区）。</td></tr>
        </tbody>
      </table>
    </div>

    <h3 style="color:var(--muted);font-size:12px;margin:10px 0 6px">
      三角片汇总（按挖填量排序，共 {{ rows.length }} 片）
    </h3>
    <div class="scrollbox">
      <table class="clickable-list">
        <thead><tr>
          <th>三角片</th><th>面积 m²</th><th>挖 m³</th><th>填 m³</th>
        </tr></thead>
        <tbody>
          <tr v-for="r in rows" :key="r.tri"
              :class="{ sel: r.tri === selectedTri }"
              @click="$emit('select', r.tri)">
            <td>#{{ r.tri }}</td>
            <td>{{ r.area.toFixed(2) }}</td>
            <td>{{ r.cut.toFixed(2) }}</td>
            <td>{{ r.fill.toFixed(2) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  result: Object,
  selectedTri: { type: Number, default: null },
})

const rows = computed(() => {
  const m = new Map()
  for (const c of props.result.cells) {
    const e = m.get(c.ground_tri) || { tri: c.ground_tri, cut: 0, fill: 0, area: 0 }
    e.cut += c.cut_m3; e.fill += c.fill_m3; e.area += c.area_m2
    m.set(c.ground_tri, e)
  }
  return [...m.values()].sort((a, b) =>
    (b.cut + b.fill) - (a.cut + a.fill))
})

const cellsOfTri = computed(() =>
  props.result.cells.filter(c => c.ground_tri === props.selectedTri))
</script>
