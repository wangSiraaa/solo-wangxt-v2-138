<template>
  <div ref="container">
    <div class="legend" v-if="result">
      <div><span class="dot" :style="{ background: '#d4574a' }"></span>挖方（原地面高于设计面）</div>
      <div><span class="dot" :style="{ background: '#3b7dd8' }"></span>填方（原地面低于设计面）</div>
      <div><span class="dot" :style="{ background: '#555e70' }"></span>缺测/未覆盖</div>
      <div style="margin-top:6px">
        <label style="color:var(--muted)">
          <input type="checkbox" :checked="showDesign" @change="toggleDesign"
                 style="width:auto;vertical-align:-2px" /> 设计面
        </label>
        &nbsp;
        <label style="color:var(--muted)">
          <input type="checkbox" :checked="showSolid" @change="toggleSolid"
                 style="width:auto;vertical-align:-2px" /> 挖填体（半透明）
        </label>
      </div>
      <div style="margin-top:6px;color:var(--muted)">
        垂向放大
        <input type="range" min="1" max="10" step="1" :value="ve"
               @input="setVe" style="width:90px;vertical-align:-4px" />
        ×{{ ve }}
      </div>
    </div>
    <div v-if="hover" class="tooltip" :style="{ left: hover.x + 14 + 'px', top: hover.y + 12 + 'px' }">
      <div><b>地面三角片 #{{ hover.tri }}</b></div>
      <div>面积 {{ hover.area.toFixed(2) }} m²</div>
      <div :style="{ color: hover.cut > 0 ? '#f0a39b' : '#9cc4f5' }">
        挖 {{ hover.cut.toFixed(2) }} m³ ／ 填 {{ hover.fill.toFixed(2) }} m³
      </div>
      <div class="muted">点击在下方查看该三角片对应积分单元</div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'

const props = defineProps({
  result: { type: Object, default: null },
})
const emit = defineEmits(['select-tri'])

const container = ref(null)
const hover = ref(null)
const showDesign = ref(true)
const showSolid = ref(true)
const ve = ref(3)

let renderer, scene, camera, controls, raf, raycaster, pointer
let groupGround, groupDesign, groupSolid, groupExtra, designMesh, solidMesh
let triMeta = []
const selected = { mesh: null }

const CUT = new THREE.Color('#d4574a')
const FILL = new THREE.Color('#3b7dd8')
const NEUTRAL = new THREE.Color('#6b7280')
const GAP = new THREE.Color('#555e70')

function triStats(result) {
  // 按 ground_tri 汇总积分单元的挖填量与面积
  const m = new Map()
  for (const c of result.cells) {
    const e = m.get(c.ground_tri) || { cut: 0, fill: 0, area: 0 }
    e.cut += c.cut_m3; e.fill += c.fill_m3; e.area += c.area_m2
    m.set(c.ground_tri, e)
  }
  return m
}

function buildScene() {
  disposeScene()
  const r = props.result
  if (!r || !container.value) return

  const width = container.value.clientWidth
  const height = container.value.clientHeight
  scene = new THREE.Scene()
  scene.background = new THREE.Color('#0f1420')
  camera = new THREE.PerspectiveCamera(50, width / height, 0.5, 20000)
  renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.setSize(width, height)
  container.value.appendChild(renderer.domElement)
  controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  raycaster = new THREE.Raycaster()
  pointer = new THREE.Vector2()

  groupGround = new THREE.Group()
  groupDesign = new THREE.Group()
  groupSolid = new THREE.Group()
  groupExtra = new THREE.Group()
  scene.add(groupGround, groupDesign, groupSolid, groupExtra)

  const zscale = ve.value
  const g = r.tin.ground
  const stats = triStats(r)
  triMeta = []

  const center = g.triangles?.length ? g.triangles[0].vertices[0] : [0, 0, 0]
  let cx = 0, cy = 0, cz = 0
  g.points.forEach((p, i) => { cx += p[0]; cy += p[1]; cz += p[2] })
  cx /= g.points.length; cy /= g.points.length; cz /= g.points.length
  const P = ([x, y, z]) => new THREE.Vector3(x - cx, (z - cz) * zscale, y - cy)

  const maxAbs = Math.max(0.1, ...r.cells.map(c => Math.abs(c.mean_diff_m)))

  // ---- 原地面 TIN（非索引三角片，平面着色） ----
  const pos = [], col = []
  g.triangles.forEach((t, k) => {
    const st = stats.get(k) || { cut: 0, fill: 0, area: 0 }
    let base
    if (st.cut > st.fill) base = CUT.clone().lerp(new THREE.Color('#3a201d'), 0.55)
    else if (st.fill > 0) base = FILL.clone().lerp(new THREE.Color('#16243c'), 0.55)
    else base = NEUTRAL
    const intensity = Math.min(1, Math.max(st.cut, st.fill) /
      Math.max(0.1, (st.area || 1) * maxAbs))
    const c = base.clone().lerp(st.cut > st.fill ? CUT : FILL,
      st.cut + st.fill > 0 ? 0.4 + 0.6 * intensity : 0)
    for (const v of t.vertices) {
      const q = P(v); pos.push(q.x, q.y, q.z); col.push(c.r, c.g, c.b)
    }
    triMeta.push({ tri: k, area: st.area, cut: st.cut, fill: st.fill })
  })
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  geo.setAttribute('color', new THREE.Float32BufferAttribute(col, 3))
  geo.computeVertexNormals()
  const mesh = new THREE.Mesh(
    geo,
    new THREE.MeshStandardMaterial({
      vertexColors: true, flatShading: true,
      transparent: true, opacity: 0.92, side: THREE.DoubleSide,
    }))
  groupGround.add(mesh)
  const wire = new THREE.LineSegments(
    new THREE.WireframeGeometry(geo),
    new THREE.LineBasicMaterial({ color: 0x222a3a, transparent: true, opacity: 0.6 }))
  groupGround.add(wire)
  mesh.userData.isGround = true
  selected.mesh = mesh

  // ---- 设计面 ----
  if (r.design_mesh && r.design_mesh.triangles.length) {
    const dp = []
    for (const tri of r.design_mesh.triangles)
      for (const v of tri) { const q = P(v); dp.push(q.x, q.y, q.z) }
    const dgeo = new THREE.BufferGeometry()
    dgeo.setAttribute('position', new THREE.Float32BufferAttribute(dp, 3))
    dgeo.computeVertexNormals()
    designMesh = new THREE.Mesh(
      dgeo, new THREE.MeshStandardMaterial({
        color: 0x8fa3c7, transparent: true, opacity: 0.35,
        side: THREE.DoubleSide, depthWrite: false,
      }))
    const dline = new THREE.LineSegments(
      new THREE.WireframeGeometry(dgeo),
      new THREE.LineBasicMaterial({ color: 0x6f86b0, transparent: true, opacity: 0.5 }))
    groupDesign.add(designMesh, dline)
  }

  // ---- 挖填体（原地面与设计面间棱柱，仅平面设计面：拓扑一致） ----
  if (r.design_mesh.kind === 'plane') {
    const sp = [], sc = []
    g.triangles.forEach((t, k) => {
      const dt = r.design_mesh.triangles[k]
      const st = stats.get(k) || { cut: 0, fill: 0 }
      const sign = st.cut >= st.fill
      const cc = sign ? CUT : FILL
      const gp = t.vertices.map(P)
      const dq = dt.map(P)
      const quad = (i, j) => {
        for (const v of [gp[i], gp[j], dq[j], gp[i], dq[j], dq[i]])
          sp.push(v.x, v.y, v.z), sc.push(cc.r, cc.g, cc.b)
      }
      quad(0, 1); quad(1, 2); quad(2, 0)
    })
    const sgeo = new THREE.BufferGeometry()
    sgeo.setAttribute('position', new THREE.Float32BufferAttribute(sp, 3))
    sgeo.setAttribute('color', new THREE.Float32BufferAttribute(sc, 3))
    solidMesh = new THREE.Mesh(
      sgeo, new THREE.MeshBasicMaterial({
        vertexColors: true, transparent: true, opacity: 0.18,
        side: THREE.DoubleSide, depthWrite: false,
      }))
    groupSolid.add(solidMesh)
  }
  groupDesign.visible = showDesign.value
  groupSolid.visible = showSolid.value

  // ---- 边界（外边界 + 孔洞）与未覆盖区 ----
  addBoundary(r, P)
  addUncovered(r, P)
  addPoints(g, P)

  // 光照
  scene.add(new THREE.AmbientLight(0xffffff, 0.75))
  const dir = new THREE.DirectionalLight(0xffffff, 1.1)
  dir.position.set(1, 2, 1); scene.add(dir)

  const b = r.boundary.bounds
  const span = Math.max(b.maxx - b.minx, b.maxy - b.miny, 1)
  camera.position.set(1.1 * span, 0.9 * span, 1.1 * span)
  controls.target.set(0, 0, 0)
  controls.update()

  renderer.domElement.addEventListener('pointermove', onMove)
  renderer.domElement.addEventListener('click', onClick)

  const loop = () => {
    raf = requestAnimationFrame(loop)
    controls.update()
    renderer.render(scene, camera)
  }
  loop()
}

function addBoundary(r, P) {
  const gj = r.boundary.geojson
  const polys = gj.type === 'MultiPolygon' ? gj.coordinates : [gj.coordinates]
  const z = (x, y) => {
    // 边界线放在可见高度（场景整体去中心后取 0 平面略上）
    return -0.01
  }
  const pts = []
  for (const poly of polys) {
    for (const ring of poly) {
      for (let i = 0; i < ring.length; i++) {
        const a = P([ring[i][0], ring[i][1], 0]); a.y = 0.02
        const bpt = P([ring[(i + 1) % ring.length][0], ring[(i + 1) % ring.length][1], 0]); bpt.y = 0.02
        pts.push(a, bpt)
      }
    }
  }
  const geo = new THREE.BufferGeometry().setFromPoints(pts)
  groupExtra.add(new THREE.LineSegments(
    geo, new THREE.LineBasicMaterial({ color: 0xffd66b })))
}

function addUncovered(r, P) {
  const gj = r.tin.ground.uncovered_geojson
  if (!gj || gj.type === 'GeometryCollection') return
  const polys = []
  if (gj.type === 'Polygon') polys.push(gj.coordinates)
  else if (gj.type === 'MultiPolygon') polys.push(...gj.coordinates)
  const pos = []
  for (const [ring] of polys) {
    const verts = ring.slice(0, -1).map(([x, y]) => { const q = P([x, y, 0]); q.y = 0.05; return q })
    for (let i = 1; i < verts.length - 1; i++)
      for (const v of [verts[0], verts[i], verts[i + 1]]) pos.push(v.x, v.y, v.z)
  }
  if (!pos.length) return
  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  const m = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({
    color: GAP, transparent: true, opacity: 0.85, side: THREE.DoubleSide,
    depthWrite: false,
  }))
  groupExtra.add(m)
}

function addPoints(g, P) {
  const measured = [], injected = []
  g.points.forEach((p, i) => {
    const q = P(p); (g.injected_points[i] ? injected : measured).push(q)
  })
  for (const [arr, color, size] of
    [[measured, 0xffffff, 1.4], [injected, 0xff9d4d, 1.4]]) {
    if (!arr.length) continue
    const geo = new THREE.BufferGeometry().setFromPoints(arr)
    groupExtra.add(new THREE.Points(geo, new THREE.PointsMaterial({
      color, size, sizeAttenuation: true,
    })))
  }
}

function onMove(e) {
  if (!selected.mesh) return
  const rect = renderer.domElement.getBoundingClientRect()
  pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1
  pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1
  raycaster.setFromCamera(pointer, camera)
  const hits = raycaster.intersectObject(selected.mesh, false)
  if (hits.length) {
    const face = Math.floor(hits[0].faceIndex)
    const m = triMeta[face]
    hover.value = { ...m, x: e.clientX - rect.left, y: e.clientY - rect.top }
    renderer.domElement.style.cursor = 'pointer'
  } else {
    hover.value = null
    renderer.domElement.style.cursor = 'default'
  }
}

function onClick() {
  if (hover.value) emit('select-tri', hover.value.tri)
}

function disposeScene() {
  cancelAnimationFrame(raf)
  hover.value = null
  if (!renderer) return
  renderer.domElement.removeEventListener('pointermove', onMove)
  renderer.domElement.removeEventListener('click', onClick)
  renderer.dispose()
  renderer.domElement.remove()
  scene?.traverse(o => {
    o.geometry?.dispose()
    if (o.material) (Array.isArray(o.material) ? o.material : [o.material])
      .forEach(m => m.dispose())
  })
  renderer = scene = camera = controls = null
  groupGround = groupDesign = groupSolid = groupExtra = null
  designMesh = solidMesh = null
}

function toggleDesign(e) { showDesign.value = e.target.checked; if (groupDesign) groupDesign.visible = showDesign.value }
function toggleSolid(e) { showSolid.value = e.target.checked; if (groupSolid) groupSolid.visible = showSolid.value }
function setVe(e) { ve.value = +e.target.value; buildScene() }

const onResize = () => { if (renderer && container.value) {
  renderer.setSize(container.value.clientWidth, container.value.clientHeight)
  camera.aspect = container.value.clientWidth / container.value.clientHeight
  camera.updateProjectionMatrix()
}}

watch(() => props.result, buildScene)
onMounted(() => { buildScene(); window.addEventListener('resize', onResize) })
onBeforeUnmount(() => { window.removeEventListener('resize', onResize); disposeScene() })
</script>
