<template>
  <div ref="container" class="viewer"></div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as THREE from 'three'

const props = defineProps({
  result: { type: Object, required: true },
  surface: { type: String, default: 'ground' }, // ground | design | diff
  showWire: { type: Boolean, default: true },
  showPoints: { type: Boolean, default: true },
  zScale: { type: Number, default: 8 }
})
const emit = defineEmits(['pick'])

const container = ref(null)
let renderer, scene, camera, raf, raycaster, pointer
let rebuilt = { sig: null }
const meshes = []

const CUT = new THREE.Color(0xc0392b)    // 挖-红
const FILL = new THREE.Color(0x2471a3)   // 填-蓝
const ZERO = new THREE.Color(0xb8b8b8)

function dzColor(dz, maxD) {
  const t = Math.min(Math.abs(dz) / Math.max(maxD, 1e-6), 1)
  const c = dz > 0 ? CUT.clone() : FILL.clone()
  if (Math.abs(dz) < 1e-6) return ZERO.clone()
  return c.lerp(new THREE.Color(0xffffff), 0.25 * (1 - t))
}

function centerOf(result) {
  const xs = result.points.map(p => p.x)
  const ys = result.points.map(p => p.y)
  const cx = (Math.min(...xs) + Math.max(...xs)) / 2
  const cy = (Math.min(...ys) + Math.max(...ys)) / 2
  return [cx, cy]
}

function build() {
  const result = props.result
  if (!result) return
  for (const m of meshes) {
    scene.remove(m.obj)
    m.obj.geometry?.dispose?.()
  }
  meshes.length = 0

  const [cx, cy] = centerOf(result)
  const zs = props.surface === 'diff'
    ? result.facets.flatMap(f => [...f.z_ground, ...f.z_design])
    : result.points.map(p => p.z)
  const zc = (Math.min(...zs) + Math.max(...zs)) / 2
  const maxD = Math.max(result.totals.max_depth_cut, result.totals.max_depth_fill, 0.01)
  const k = props.zScale
  const P = (x, y, z) => new THREE.Vector3(x - cx, (z - zc) * k, y - cy)

  // ---- 叠加三角片：按挖填着色 ----
  const facets = result.facets
  const positions = new Float32Array(facets.length * 3 * 3)
  const colors = new Float32Array(facets.length * 3 * 3)
  const pick = []
  let o = 0
  facets.forEach((f, fi) => {
    const zv = props.surface === 'design' ? f.z_design : f.z_ground
    const mdz = f.dz.reduce((a, b) => a + b, 0) / 3
    for (let i = 0; i < 3; i++) {
      const v = P(f.vertices[i][0], f.vertices[i][1], zv[i])
      positions[o] = v.x; positions[o + 1] = v.y; positions[o + 2] = v.z
      const c = props.surface === 'diff'
        ? dzColor(mdz, maxD)
        : dzColor(f.dz[i], maxD)
      colors[o] = c.r; colors[o + 1] = c.g; colors[o + 2] = c.b
      o += 3
    }
    pick.push(fi)
  })
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  g.setAttribute('color', new THREE.BufferAttribute(colors, 3))
  g.computeVertexNormals()
  const mesh = new THREE.Mesh(
    g, new THREE.MeshStandardMaterial({ vertexColors: true, side: THREE.DoubleSide,
      transparent: true, opacity: props.surface === 'diff' ? 0.92 : 0.85,
      polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 }))
  mesh.userData.pick = pick
  scene.add(mesh)
  meshes.push({ obj: mesh })

  if (props.showWire) {
    const w = new THREE.LineSegments(
      new THREE.WireframeGeometry(g),
      new THREE.LineBasicMaterial({ color: 0x222222, transparent: true, opacity: 0.35 }))
    scene.add(w); meshes.push({ obj: w })
  }

  // ---- 另一曲面的对照线框 ----
  const otherZ = props.surface === 'design' ? 'z_ground' : 'z_design'
  const opos = new Float32Array(facets.length * 3 * 3)
  o = 0
  for (const f of facets) {
    for (let i = 0; i < 3; i++) {
      const v = P(f.vertices[i][0], f.vertices[i][1], f[otherZ][i])
      opos[o] = v.x; opos[o + 1] = v.y; opos[o + 2] = v.z; o += 3
    }
  }
  const og2 = new THREE.BufferGeometry()
  og2.setAttribute('position', new THREE.BufferAttribute(opos, 3))
  const other = new THREE.LineSegments(
    new THREE.WireframeGeometry(og2),
    new THREE.LineBasicMaterial({ color: 0xe67e22, transparent: true, opacity: 0.5 }))
  scene.add(other); meshes.push({ obj: other })

  // ---- 原始高程点 ----
  if (props.showPoints) {
    const gp = result.points.filter(p => p.surface === 'ground')
    const dp = result.points.filter(p => p.surface === 'design')
    for (const [arr, col, r] of [[gp, 0x1b1b1b, 0.5], [dp, 0xe67e22, 0.7]]) {
      const pg = new THREE.BufferGeometry()
      pg.setAttribute('position', new THREE.Float32BufferAttribute(
        arr.flatMap(p => [p.x - cx, (p.z - zc) * k, p.y - cy]), 3))
      const pm = new THREE.Points(pg, new THREE.PointsMaterial(
        { color: col, size: r, sizeAttenuation: true }))
      scene.add(pm); meshes.push({ obj: pm })
    }
  }

  // ---- 边界 / 孔洞 / 缺测环 ----
  const rings = []
  if (result.boundary) {
    result.boundary.forEach(r => rings.push([r.coords, 0x111111]))
  }
  result.holes?.forEach(h => rings.push([h, 0x7f8c8d]))
  result.no_data?.forEach(h => rings.push([h, 0x8e44ad]))
  for (const [ring, col] of rings) {
    const pts = ring.map(([x, y]) => P(x, y, zc))
    pts.push(pts[0].clone())
    const lg = new THREE.BufferGeometry().setFromPoints(pts)
    const line = new THREE.Line(lg, new THREE.LineBasicMaterial({ color: col, linewidth: 2 }))
    scene.add(line); meshes.push({ obj: line })
    // 孔洞/缺测半透明贴面（放到地面高度提示范围）
    if (col !== 0x111111 && ring.length >= 3) {
      const pg = new THREE.BufferGeometry()
      const vv = ring.flatMap(([x, y]) => [x - cx, (zc - zc) * k + 0.05, y - cy])
      pg.setAttribute('position', new THREE.Float32BufferAttribute(vv, 3))
      pg.setIndex(ring.slice(1, -1).map((_, i) => [0, i + 1, i + 2]).flat())
      const pm = new THREE.Mesh(pg, new THREE.MeshBasicMaterial({
        color: col, transparent: true, opacity: 0.18, side: THREE.DoubleSide }))
      scene.add(pm); meshes.push({ obj: pm })
    }
  }

  rebuilt.sig = JSON.stringify([facets.length, props.surface, props.showWire,
    props.showPoints, props.zScale])
}

function onPick(e) {
  const rect = renderer.domElement.getBoundingClientRect()
  pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1
  pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1
  raycaster.setFromCamera(pointer, camera)
  const hit = raycaster.intersectObjects(meshes.map(m => m.obj), false)
  if (!hit.length) return
  const m = hit[0].object
  if (!m.userData.pick) return
  // 非索引几何体每个三角片占 3 个顶点，face.a 即首顶点序号
  const fi = m.userData.pick[Math.floor(hit[0].face.a / 3)]
  emit('pick', props.result.facets[fi])
}

let dragging = false
function initControls() {
  const dom = renderer.domElement
  const spherical = new THREE.Spherical(170, Math.PI / 2.4, 0.6)
  const target = new THREE.Vector3(0, 4, 0)
  function upd() {
    camera.position.setFromSpherical(spherical).add(target)
    camera.lookAt(target)
  }
  upd()
  let last = null
  dom.addEventListener('pointerdown', e => { dragging = true; last = [e.clientX, e.clientY] })
  window.addEventListener('pointerup', () => { dragging = false; last = null })
  window.addEventListener('pointermove', e => {
    if (!dragging || !last) return
    const dx = e.clientX - last[0], dy = e.clientY - last[1]
    last = [e.clientX, e.clientY]
    spherical.theta -= dx * 0.008
    spherical.phi = Math.min(Math.PI - 0.1, Math.max(0.1, spherical.phi - dy * 0.008))
    upd()
  })
  dom.addEventListener('wheel', e => {
    e.preventDefault()
    spherical.radius = Math.min(600, Math.max(30, spherical.radius * (1 + Math.sign(e.deltaY) * 0.1)))
    upd()
  }, { passive: false })
  dom.addEventListener('click', onPick)
}

onMounted(() => {
  const el = container.value
  scene = new THREE.Scene()
  scene.background = new THREE.Color(0xf2f4f5)
  camera = new THREE.PerspectiveCamera(50, el.clientWidth / el.clientHeight, 0.1, 5000)
  renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setSize(el.clientWidth, el.clientHeight)
  el.appendChild(renderer.domElement)
  scene.add(new THREE.AmbientLight(0xffffff, 0.75))
  const sun = new THREE.DirectionalLight(0xffffff, 1.6)
  sun.position.set(80, 160, 60); scene.add(sun)
  raycaster = new THREE.Raycaster()
  pointer = new THREE.Vector2()
  initControls()
  build()
  const loop = () => { raf = requestAnimationFrame(loop); renderer.render(scene, camera) }
  loop()
  window.addEventListener('resize', () => {
    camera.aspect = el.clientWidth / el.clientHeight
    camera.updateProjectionMatrix()
    renderer.setSize(el.clientWidth, el.clientHeight)
  })
})

watch(() => [props.result, props.surface, props.showWire, props.showPoints, props.zScale],
  () => build(), { deep: false })

onBeforeUnmount(() => { cancelAnimationFrame(raf); renderer?.dispose() })
</script>

<style scoped>
.viewer { width: 100%; height: 100%; min-height: 420px; }
</style>
