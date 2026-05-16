<script setup>
import { ref, onMounted, onBeforeUnmount, reactive } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls'

const containerRef = ref(null)
const labelsRef = ref(null)

const emit = defineEmits(['update-stations', 'update-kpi'])

const tooltip = reactive({
  visible: false,
  x: 0, y: 0,
  orderId: '', partType: '', stName: ''
})

let scene, camera, renderer, controls, clock
let simData = [], activeBoxes = new Map()
const stations = []

let isPlaying = false, currentTime = 0, maxTime = 100
// 🌟 默认速度改为 4X，让你能清晰看到 45秒 的加工过程，而不是瞬间飞过
const playbackSpeed = ref(4) 
let lastTime = 0

const setSpeed = (speed) => { playbackSpeed.value = speed }

defineExpose({
  loadAndPlay(playbook, activeCount = 16) {
    if (stations.length > 0) updateStationPowerState(activeCount)
    parsePlaybook(playbook)
    isPlaying = true
    clock.start()
  },
  togglePlay() {
    isPlaying = !isPlaying
    return isPlaying
  },
  setSpeed
})

const updateStationPowerState = (activeCount) => {
  stations.forEach((s, i) => {
    s.isPoweredOff = i >= activeCount 
    if (s.isPoweredOff) {
      s.worker.visible = false
      s.desk.material.color.setHex(0x334155) 
      s.screen.material.color.setHex(0x1e293b)
      s.screen.material.emissiveIntensity = 0 
      s.light.material.color.setHex(0x1e293b)
      s.light.material.emissive.setHex(0x000000) 
      s.labelDom.style.color = '#475569'
      s.labelDom.style.borderColor = '#475569'
      s.labelDom.style.background = 'rgba(10, 15, 25, 0.9)'
      s.labelDom.innerText = `S${(i+1).toString().padStart(2, '0')} (休眠)`
    } else {
      s.worker.visible = true
      s.desk.material.color.setHex(0xF8FAFC)
      s.screen.material.color.setHex(0x00E5FF)
      s.screen.material.emissiveIntensity = 0.1
      s.light.material.color.setHex(0x00ffcc)
      s.light.material.emissive.setHex(0x00aa88)
      s.labelDom.style.color = '#00E5FF'
      s.labelDom.style.borderColor = '#00E5FF'
      s.labelDom.style.background = 'rgba(10, 25, 45, 0.9)'
      s.labelDom.innerText = `S${(i+1).toString().padStart(2, '0')}`
    }
  })
}

let orderStats = { total: 0, map: {} }

// ==========================================
// 🌟 终极修复：带有“时空逆向推演”的解析大脑
// ==========================================
const parsePlaybook = (playbook) => {
  if (!playbook || !playbook.timeline || playbook.timeline.length === 0) return
  
  // 🌟 修复 1：将字符串中间的空格换成 'T'，解决 Safari/部分浏览器解析报 NaN 导致全盘崩溃的 Bug
  const parseDate = (dStr) => new Date(dStr.replace(' ', 'T')).getTime()

  const timeArray = playbook.timeline.map(t => parseDate(t.spawn_time || t.start_time))
  const baseTime = Math.min(...timeArray)

  const START_X = -90
  const BELT_SPEED = 2.0

  simData = playbook.timeline.map((item, index) => {
    let spawnSec = (parseDate(item.spawn_time || item.start_time) - baseTime) / 1000
    const startSec = (parseDate(item.start_time) - baseTime) / 1000
    const endSec = (parseDate(item.end_time) - baseTime) / 1000
    
    const stIdx = item.target_station - 1 
    const eX = START_X + 10 + stIdx * 10.0 
    const distIn = Math.abs(eX - START_X)
    const distOut = Math.abs(eX - (START_X - 10))
    
    // 🌟 修复 2：如果后端没传真正的 spawn_time (两时间重合)，我们用纯物理距离逆向把真实发车时间推算出来！
    // 这样箱子就会提前发车，正好在 startSec 时刻完美滑入机床落刀！
    const t_trans = (distIn / BELT_SPEED) + (10.5 / BELT_SPEED)
    if (spawnSec >= startSec - 1.0) {
        spawnSec = startSec - t_trans
    }

    const spawnTime = spawnSec
    const branchTime = spawnTime + (distIn / BELT_SPEED) 
    const returnMainTime = endSec 
    const timeUpBranch = 10.5 / BELT_SPEED
    const returnBranchEndTime = returnMainTime + timeUpBranch
    const exitTime = returnBranchEndTime + (distOut / BELT_SPEED)

    let rawId = item.box_id || item.part_id || item.id || ''
    let uniqueBoxId = rawId.includes('-P') ? rawId : `${item.order_id || 'ORD'}-P${(index + 1).toString().padStart(3, '0')}`

    return {
      box_id: uniqueBoxId,
      order_id: item.order_id || '未知订单',
      stIdx: stIdx,
      timeline: { 
        spawn: spawnTime, branch: branchTime, start: startSec, 
        return_main: returnMainTime, return_branch_end: returnBranchEndTime, exit: exitTime 
      }
    }
  })

  // 幽灵箱子清理
  const newBoxIds = new Set(simData.map(d => d.box_id))
  activeBoxes.forEach((b, id) => {
    if (!newBoxIds.has(id)) {
      scene.remove(b.mesh)
      if (b.label && b.label.parentNode) b.label.parentNode.removeChild(b.label)
      activeBoxes.delete(id)
    }
  })

  // 重置 KPI 统计
  orderStats.map = {}
  simData.forEach(d => {
    const orderId = d.order_id
    if(!orderStats.map[orderId]) { orderStats.map[orderId] = { totalBoxes: 0, boxesFinished: 0 } }
    orderStats.map[orderId].totalBoxes++
  })
  orderStats.total = Object.keys(orderStats.map).length

  maxTime = Math.max(...simData.map(d => d.timeline.exit)) + 2.0
  currentTime = 0
  lastTime = 0
}

const stringToColor = (str) => {
  let hash = 0
  for (let i = 0; i < str.length; i++) hash = str.charCodeAt(i) + ((hash << 5) - hash)
  return new THREE.Color(`hsl(${Math.abs(hash) % 360}, 85%, 60%)`)
}

const createWarningTexture = () => {
  const canvas = document.createElement('canvas')
  canvas.width = 256; canvas.height = 256
  const ctx = canvas.getContext('2d')
  ctx.fillStyle = '#FFB800'; ctx.fillRect(0, 0, 256, 256)
  ctx.fillStyle = '#111111'
  for(let i = -256; i < 512; i += 40) { 
    ctx.beginPath(); ctx.moveTo(i, 0); ctx.lineTo(i+20, 0); ctx.lineTo(i+256+20, 256); ctx.lineTo(i+256, 256); ctx.fill() 
  }
  const tex = new THREE.CanvasTexture(canvas)
  tex.wrapS = THREE.RepeatWrapping; tex.wrapT = THREE.RepeatWrapping; tex.repeat.set(1, 2)
  return tex
}

const init3D = () => {
  scene = new THREE.Scene()
  scene.background = new THREE.Color(0x08121C)
  clock = new THREE.Clock()

  const width = containerRef.value.clientWidth
  const height = containerRef.value.clientHeight

  camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000)
  camera.position.set(-20, 90, 140)
  camera.lookAt(20, 0, 0)

  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" })
  renderer.setSize(width, height)
  renderer.shadowMap.enabled = true
  renderer.shadowMap.type = THREE.PCFSoftShadowMap
  containerRef.value.appendChild(renderer.domElement)

  controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.maxPolarAngle = Math.PI / 2.05

  scene.add(new THREE.AmbientLight(0xffffff, 0.8))
  scene.add(new THREE.HemisphereLight(0xffffff, 0x445577, 0.6))
  const dirLight = new THREE.DirectionalLight(0xffffff, 1.2)
  dirLight.position.set(30, 80, 40)
  dirLight.castShadow = true
  dirLight.shadow.mapSize.width = 2048
  dirLight.shadow.mapSize.height = 2048
  scene.add(dirLight)
  
  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(350, 200), 
    new THREE.MeshStandardMaterial({ color: 0x0A1525, roughness: 0.15, metalness: 0.8 })
  )
  floor.rotation.x = -Math.PI / 2; floor.position.y = -0.1; floor.receiveShadow = true
  scene.add(floor)
  scene.add(new THREE.GridHelper(300, 100, 0x1E3A5F, 0x112233))

  const START_X = -90; const BELT_LEN = 180; const SPACING = 10.0; const SURFACE_LOWER = 0.3; const SURFACE_UPPER = 3.5

  const whGroup = new THREE.Group()
  const whX = START_X - 8
  const whFrameMat = new THREE.MeshStandardMaterial({color: 0xE8F0FE, roughness: 0.2, metalness: 0.2})
  const frameBottom = new THREE.Mesh(new THREE.BoxGeometry(16, 2, 14), whFrameMat); frameBottom.position.set(whX, 1, 0); whGroup.add(frameBottom)
  const frameTop = new THREE.Mesh(new THREE.BoxGeometry(16, 2, 14), whFrameMat); frameTop.position.set(whX, 13, 0); whGroup.add(frameTop)
  const frameBack = new THREE.Mesh(new THREE.BoxGeometry(2, 10, 14), whFrameMat); frameBack.position.set(whX - 7, 7, 0); whGroup.add(frameBack)
  const frameSide = new THREE.Mesh(new THREE.BoxGeometry(16, 10, 2), whFrameMat); frameSide.position.set(whX, 7, -6); whGroup.add(frameSide)
  const glassMat = new THREE.MeshPhysicalMaterial({ color: 0x88CCFF, transparent: true, opacity: 0.25, metalness: 0.9, roughness: 0.05, transmission: 0.8, side: THREE.DoubleSide })
  const glass = new THREE.Mesh(new THREE.BoxGeometry(14.2, 10, 12.2), glassMat); glass.position.set(whX + 1, 7, 1); whGroup.add(glass)
  const rackMat = new THREE.MeshStandardMaterial({color: 0xFF5500, metalness: 0.8, roughness:0.2})
  for(let r = -3; r <= 5; r += 4) { for(let c = whX - 4; c <= whX + 4; c += 4) { const rack = new THREE.Mesh(new THREE.BoxGeometry(2.5, 9, 1.2), rackMat); rack.position.set(c, 6.5, r); whGroup.add(rack) } }
  const tunnelMat = new THREE.MeshStandardMaterial({map: createWarningTexture()}); const holeMat = new THREE.MeshBasicMaterial({color: 0x000000})
  const lowTun = new THREE.Mesh(new THREE.BoxGeometry(3, 2.2, 2.5), tunnelMat); lowTun.position.set(START_X - 1.5, SURFACE_LOWER + 1.1, 0); whGroup.add(lowTun)
  const lowHole = new THREE.Mesh(new THREE.BoxGeometry(3.1, 2.0, 2.0), holeMat); lowHole.position.set(START_X - 1.5, SURFACE_LOWER + 1.1, 0); whGroup.add(lowHole)
  const upTun = new THREE.Mesh(new THREE.BoxGeometry(3, 2.2, 2.5), tunnelMat); upTun.position.set(START_X - 1.5, SURFACE_UPPER + 1.1, 0); whGroup.add(upTun)
  const upHole = new THREE.Mesh(new THREE.BoxGeometry(3.1, 2.0, 2.0), holeMat); upHole.position.set(START_X - 1.5, SURFACE_UPPER + 1.1, 0); whGroup.add(upHole)
  scene.add(whGroup)

  const createBeltCore = (len, color, y, z, hideFrontRail=false) => { 
    const group = new THREE.Group()
    const track = new THREE.Mesh(new THREE.BoxGeometry(len, 0.1, 1.2), new THREE.MeshStandardMaterial({ color: color }))
    track.position.set(0, y - 0.05, z); track.receiveShadow = true; group.add(track)
    const rMat = new THREE.MeshStandardMaterial({ color: 0xA0B2C6, metalness: 0.7 })
    if (!hideFrontRail) { const rF = new THREE.Mesh(new THREE.BoxGeometry(len, 0.2, 0.05), rMat); rF.position.set(0, y + 0.05, z + 0.6); group.add(rF) }
    const rB = new THREE.Mesh(new THREE.BoxGeometry(len, 0.2, 0.05), rMat); rB.position.set(0, y + 0.05, z - 0.6); group.add(rB)
    return group
  }

  scene.add(createBeltCore(BELT_LEN, 0x111827, SURFACE_LOWER, 0, true)); scene.add(createBeltCore(BELT_LEN, 0x111827, SURFACE_UPPER, 0, true))
  const pMat = new THREE.MeshStandardMaterial({ color: 0x475569, metalness: 0.6 })
  for(let i = START_X + 5; i < START_X + BELT_LEN - 10; i += 12) {
    const p1 = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, SURFACE_UPPER), pMat); p1.position.set(i, SURFACE_UPPER/2, 0.65); p1.castShadow=true; scene.add(p1)
    const p2 = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, SURFACE_UPPER), pMat); p2.position.set(i, SURFACE_UPPER/2, -0.65); p2.castShadow=true; scene.add(p2)
  }

  for (let i = 0; i < 16; i++) {
    const x = START_X + 10 + i * SPACING
    
    const branchLen = 9.3; const branchBelt = createBeltCore(branchLen, 0x1E293B, SURFACE_LOWER, 0, false)
    branchBelt.rotation.y = Math.PI / 2; branchBelt.position.set(x, 0, 0.6 + branchLen / 2); scene.add(branchBelt)
    
    const dY = SURFACE_UPPER - SURFACE_LOWER; const dZ = 10.5 - 0.6
    const rLen = Math.sqrt(dY*dY + dZ*dZ); const rAngle = Math.atan2(dY, dZ)
    const rampGroup = new THREE.Group()
    rampGroup.position.set(x, SURFACE_LOWER + dY/2, 0.6 + dZ/2); rampGroup.rotation.x = rAngle
    const rampMesh = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.1, rLen), new THREE.MeshStandardMaterial({color: 0x1E293B}))
    rampMesh.position.set(0, -0.05, 0); rampMesh.castShadow = true; rampMesh.receiveShadow = true; rampGroup.add(rampMesh)
    const rrMat = new THREE.MeshStandardMaterial({color: 0xFF6B00, metalness:0.4})
    const rrF = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.2, rLen), rrMat); rrF.position.set(0.6, 0.05, 0); rampGroup.add(rrF)
    const rrB = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.2, rLen), rrMat); rrB.position.set(-0.6, 0.05, 0); rampGroup.add(rrB)
    scene.add(rampGroup)

    const deskMat = new THREE.MeshStandardMaterial({color: 0xF8FAFC, metalness:0.3})
    const desk = new THREE.Mesh(new THREE.BoxGeometry(2.0, 0.2, 1.2), deskMat)
    desk.position.set(x, SURFACE_LOWER - 0.1, 10.5); desk.castShadow = true; desk.receiveShadow = true; scene.add(desk)
    
    const screen = new THREE.Mesh(new THREE.PlaneGeometry(1.5, 0.8), new THREE.MeshStandardMaterial({color: 0x00E5FF, emissive: 0x00E5FF, emissiveIntensity: 0.1, transparent: true, opacity: 0.8, side: THREE.DoubleSide}))
    screen.position.set(x, 0.8, 11.2); screen.rotation.x = -Math.PI / 8; scene.add(screen)
    const light = new THREE.Mesh(new THREE.SphereGeometry(0.15), new THREE.MeshStandardMaterial({color: 0x00ffcc, emissive: 0x00aa88}))
    light.position.set(x - 1.0, 1.4, 11.2); scene.add(light)
    const laser = new THREE.Mesh(new THREE.PlaneGeometry(1.2, 0.05), new THREE.MeshBasicMaterial({color: 0x00FF00, transparent: true, opacity: 0.8, side: THREE.DoubleSide}))
    laser.position.set(x, SURFACE_LOWER + 0.5, 10.5); laser.visible = false; scene.add(laser)

    const worker = new THREE.Group()
    const mSkin = new THREE.MeshStandardMaterial({color: 0xFFB800}); const mCloth = new THREE.MeshStandardMaterial({color: 0x1E3A8A}); const mVest = new THREE.MeshStandardMaterial({color: 0x10B981})
    const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, 0.4), mCloth); leg.position.set(x-0.15, 0.2, 11.6); worker.add(leg)
    const leg2 = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, 0.4), mCloth); leg2.position.set(x+0.15, 0.2, 11.6); worker.add(leg2)
    const torso = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.6, 0.3), mVest); torso.position.set(x, 0.7, 11.6); worker.add(torso)
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.15), mSkin); head.position.set(x, 1.15, 11.6); worker.add(head)
    const hat = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.18, 0.1), new THREE.MeshStandardMaterial({color: 0xFF0000})); hat.position.set(x, 1.25, 11.6); worker.add(hat)
    const armG = new THREE.CylinderGeometry(0.06, 0.06, 0.5)
    const armL = new THREE.Mesh(armG, mVest); armL.position.set(x-0.3, 0.8, 11.3); armL.rotation.x = -Math.PI/3; armL.rotation.z = -Math.PI/8; worker.add(armL)
    const armR = new THREE.Mesh(armG, mVest); armR.position.set(x+0.3, 0.8, 11.3); armR.rotation.x = -Math.PI/3; armR.rotation.z = Math.PI/8; worker.add(armR)
    worker.castShadow = true; scene.add(worker)

    const stLabel = document.createElement('div'); stLabel.className = 'station-label'
    stLabel.innerText = `S${(i+1).toString().padStart(2, '0')}`; labelsRef.value.appendChild(stLabel)
    stations.push({ id: i, x: x, screen: screen, laser: laser, light: light, labelDom: stLabel, desk: desk, worker: worker, isPoweredOff: false })
  }

  const raycaster = new THREE.Raycaster(); const mouse = new THREE.Vector2()
  containerRef.value.addEventListener('mousemove', (event) => {
    const rect = containerRef.value.getBoundingClientRect()
    mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1
    mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1

    const boxMeshes = Array.from(activeBoxes.values()).map(b => b.mesh)
    raycaster.setFromCamera(mouse, camera)
    const intersects = raycaster.intersectObjects(boxMeshes)

    if (intersects.length > 0) {
      const boxObj = intersects[0].object; const data = boxObj.userData
      const parts = data.id.split('-P')
      
      tooltip.orderId = parts[0]
      tooltip.partType = 'Type-P' + (parts[1] || '未知')
      tooltip.stName = `S${(data.station + 1).toString().padStart(2, '0')} 号工位`
      tooltip.x = event.clientX + 15
      tooltip.y = event.clientY + 15
      tooltip.visible = true
      document.body.style.cursor = 'pointer'
    } else {
      tooltip.visible = false; document.body.style.cursor = 'default'
    }
  })

  const animate = () => {
    requestAnimationFrame(animate)
    controls.update()

    stations.forEach(s => { 
      const pos = new THREE.Vector3(s.x, 3.5, 10.5); pos.project(camera)
      s.labelDom.style.left = `${(pos.x * .5 + .5) * width}px`
      s.labelDom.style.top = `${(pos.y * -.5 + .5) * height}px`
    })

    if (isPlaying && simData.length > 0) {
      const dt = clock.getDelta() * playbackSpeed.value
      currentTime += dt
      if (currentTime > maxTime) currentTime = maxTime

      const isScrubbing = Math.abs(currentTime - lastTime - dt) > 0.5
      let finishedCount = 0, activeCount = 0
      let currentOrderProgress = JSON.parse(JSON.stringify(orderStats.map))
      
      // 先计算出每一帧各个站台的状态
      let stStatusCount = Array(16).fill(0).map((_, i) => ({ active: false, buffer: 0, isOff: stations[i].isPoweredOff }))

      simData.forEach(boxData => {
        const t = currentTime, tl = boxData.timeline, stIdx = boxData.stIdx, eX = stations[stIdx].x
        const orderId = boxData.order_id

        if (t >= tl.exit) { finishedCount++; currentOrderProgress[orderId].boxesFinished++ } else if (t >= tl.spawn) { activeCount++ }
        
        // 排队区逻辑
        if (t >= tl.branch && t < tl.start) stStatusCount[stIdx].buffer++
        
        // 核心加工区逻辑
        if (t >= tl.start && t < tl.return_main) {
          stStatusCount[stIdx].active = true
        }

        // 箱子动画位移
        if (t >= tl.spawn && t <= tl.exit) {
          let boxObj = activeBoxes.get(boxData.box_id)
          if (!boxObj) {
            const shortName = boxData.box_id.split('-P').pop()
            const mesh = new THREE.Mesh(
              new THREE.BoxGeometry(0.5, 0.5, 0.5), 
              new THREE.MeshStandardMaterial({ color: stringToColor(boxData.box_id), roughness: 0.2, metalness: 0.4 })
            )
            mesh.castShadow = true; mesh.receiveShadow = true; mesh.userData = { id: boxData.box_id, station: stIdx }
            scene.add(mesh)
            
            const label = document.createElement('div'); label.className = 'box-label'; label.innerText = 'P' + shortName
            labelsRef.value.appendChild(label)

            boxObj = { mesh: mesh, label: label, currentZ: 0 }; activeBoxes.set(boxData.box_id, boxObj)
          }

          let targetX, targetY, targetZ
          if (t < tl.branch) { 
            targetX = START_X + (eX - START_X) * ((t - tl.spawn) / (tl.branch - tl.spawn))
            targetY = SURFACE_LOWER + 0.25; targetZ = 0; boxObj.currentZ = 0
          } else if (t < tl.return_main) {
            targetX = eX; targetY = SURFACE_LOWER + 0.25
            
            let limitZ
            if (t < tl.start) {
                let boxesAhead = 0
                for(let i=0; i<simData.length; i++) { 
                    if (simData[i].stIdx === stIdx && simData[i].box_id !== boxData.box_id && simData[i].timeline.branch < tl.branch && t < simData[i].timeline.return_main) boxesAhead++ 
                }
                limitZ = boxesAhead === 0 ? 10.5 : 9.5 - (boxesAhead - 1) * 0.7 
            } else { limitZ = 10.5 } 

            const realBranchSpeed = 10.5 / 9.5 
            if (isScrubbing) { boxObj.currentZ = Math.min((t - tl.branch) * realBranchSpeed, limitZ) } 
            else { 
                if (boxObj.currentZ < limitZ) { boxObj.currentZ += dt * realBranchSpeed; if (boxObj.currentZ > limitZ) boxObj.currentZ = limitZ } 
                else if (boxObj.currentZ > limitZ + 0.1) { boxObj.currentZ = limitZ } 
            }
            targetZ = boxObj.currentZ
          } else if (t < tl.return_branch_end) { 
            let p = (t - tl.return_main) / (tl.return_branch_end - tl.return_main)
            targetX = eX; targetY = (SURFACE_LOWER + 0.25) + (SURFACE_UPPER - SURFACE_LOWER) * p; targetZ = 10.5 * (1 - p); boxObj.currentZ = targetZ
          } else {
            targetX = eX - (eX - (START_X - 10)) * ((t - tl.return_branch_end) / (tl.exit - tl.return_branch_end)); targetY = SURFACE_UPPER + 0.25; targetZ = 0; boxObj.currentZ = targetZ
          }
          
          boxObj.mesh.position.set(targetX, targetY, targetZ); boxObj.label.style.display = 'block'
          const screenPos = boxObj.mesh.position.clone(); screenPos.y += 0.5; screenPos.project(camera)
          boxObj.label.style.left = `${(screenPos.x * .5 + .5) * width}px`
          boxObj.label.style.top = `${(screenPos.y * -.5 + .5) * height}px`
        } else {
          let b = activeBoxes.get(boxData.box_id)
          if (b) { scene.remove(b.mesh); if (b.label.parentNode) b.label.parentNode.removeChild(b.label); activeBoxes.delete(boxData.box_id) }
        }
      })
      
      // 🌟 修复 3：统一渲染材质，彻底消灭色彩覆写Bug，让塞博青色呼吸灯稳定常亮！
      stations.forEach((s, i) => {
        if (s.isPoweredOff) return
        if (stStatusCount[i].active) {
          s.screen.material.emissiveIntensity = 1.0
          s.laser.visible = true
          s.laser.position.z = 10.5 + Math.sin(t * 10) * 0.35
          s.light.material.color.setHex(0x00E5FF)
          s.light.material.emissive.setHex(0x00E5FF)
        } else {
          s.screen.material.emissiveIntensity = 0.1
          s.laser.visible = false
          s.light.material.color.setHex(0x00ffcc)
          s.light.material.emissive.setHex(0x00aa88)
        }
      })

      // 实时回传给 App.vue 用于渲染 16宫格面板
      const stationEmitData = stStatusCount.map((s, i) => ({
        id: i, isOff: stations[i].isPoweredOff, active: s.active, buffer: s.buffer
      }))
      emit('update-stations', stationEmitData)

      // 实时回传全局 KPI
      let completedOrdersCount = 0
      Object.values(currentOrderProgress).forEach(order => { if (order.boxesFinished === order.totalBoxes) completedOrdersCount++ })
      const pct = (finishedCount / simData.length * 100) || 0
      emit('update-kpi', {
        ordersDone: completedOrdersCount, ordersTotal: orderStats.total, boxesDone: finishedCount,
        boxesActive: activeBoxes.size, boxesTotal: simData.length, progressPct: pct, currentTime: currentTime, maxTime: maxTime
      })

      lastTime = currentTime
    }
    renderer.render(scene, camera)
  }
  animate()
}

const handleResize = () => {
  if (camera && renderer && containerRef.value) {
    camera.aspect = containerRef.value.clientWidth / containerRef.value.clientHeight
    camera.updateProjectionMatrix()
    renderer.setSize(containerRef.value.clientWidth, containerRef.value.clientHeight)
  }
}

onMounted(() => {
  init3D()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  if (renderer) renderer.dispose()
})
</script>

<template>
  <div class="factory-container" ref="containerRef">
    <div class="labels-layer" ref="labelsRef"></div>
    
    <div v-if="tooltip.visible" id="tooltip" :style="{ left: tooltip.x + 'px', top: tooltip.y + 'px' }">
      <div style="border-bottom:1px solid #00E5FF; margin-bottom:10px; padding-bottom:6px; font-size:14px; text-shadow: 0 0 5px #00E5FF;">
        <strong>📦 物理物料箱</strong>
      </div>
      <div class="tooltip-row"><span class="tooltip-label">归属订单</span> <span class="tooltip-value highlight-text">{{ tooltip.orderId }}</span></div>
      <div class="tooltip-row"><span class="tooltip-label">零件型号</span> <span class="tooltip-value">{{ tooltip.partType }}</span></div>
      <div class="tooltip-row" style="margin-top:8px; border-top:1px dashed #3A5A7A; padding-top:8px;"><span class="tooltip-label">目标站台</span> <span class="tooltip-value" style="color:#00FF00;">🎯 {{ tooltip.stName }}</span></div>
    </div>

    <div v-if="isPlaying" class="time-overlay">
      数字孪生时间轴: {{ currentTime.toFixed(1) }} s
    </div>

    <div v-if="isPlaying" class="speed-controls">
      <span class="speed-label">推演倍速:</span>
      <button :class="{ active: playbackSpeed === 1 }" @click="setSpeed(1)">1X</button>
      <button :class="{ active: playbackSpeed === 4 }" @click="setSpeed(4)">4X</button>
      <button :class="{ active: playbackSpeed === 16 }" @click="setSpeed(16)">16X</button>
      <button :class="{ active: playbackSpeed === 32 }" @click="setSpeed(32)">32X</button>
      <button :class="{ active: playbackSpeed === 64 }" @click="setSpeed(64)">64X</button>
    </div>
  </div>
</template>

<style scoped>
.factory-container { width: 100%; height: 100%; position: relative; border-radius: 12px; overflow: hidden; box-shadow: inset 0 0 50px rgba(0, 229, 255, 0.1); border: 1px solid rgba(0, 229, 255, 0.2); }
.labels-layer { position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; }
:deep(.box-label) { position: absolute; color: #fff; background: rgba(0, 0, 0, 0.9); padding: 3px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; border: 1px solid #00E5FF; transform: translate(-50%, -100%); display: none; z-index: 50; pointer-events: none; }
:deep(.station-label) { position: absolute; color: #00E5FF; background: rgba(10, 25, 45, 0.9); padding: 3px 10px; border-radius: 5px; font-size: 14px; font-weight: 900; border: 1px solid #00E5FF; transform: translate(-50%, -50%); z-index: 40; pointer-events: none; }
#tooltip { position: fixed; background: rgba(15, 25, 45, 0.95); color: #fff; padding: 15px; border-radius: 8px; font-size: 13px; border: 1px solid #00E5FF; pointer-events: none; z-index: 200; backdrop-filter: blur(8px); box-shadow: 0 10px 30px rgba(0,229,255,0.2); min-width: 200px; }
.tooltip-row { margin-bottom: 6px; display: flex; justify-content: space-between; }
.tooltip-label { color: #A0B2C6; font-weight: bold; }
.tooltip-value { font-weight: 900; color: #FFFFFF; }
.highlight-text { color: #FFB800; }
.time-overlay { position: absolute; top: 20px; left: 20px; color: #00E5FF; font-family: monospace; font-size: 18px; font-weight: bold; background: rgba(10, 25, 45, 0.8); padding: 10px 20px; border-radius: 8px; border: 1px solid #00E5FF; z-index: 10; }
.speed-controls { position: absolute; top: 20px; right: 20px; background: rgba(10, 25, 45, 0.8); padding: 8px 12px; border-radius: 8px; border: 1px solid #00E5FF; z-index: 10; display: flex; align-items: center; gap: 8px; backdrop-filter: blur(4px); }
.speed-label { color: #A0B2C6; font-size: 14px; font-weight: bold; margin-right: 4px; }
.speed-controls button { background: transparent; border: 1px solid #1E3A5F; color: #A0B2C6; padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 12px; font-weight: bold; transition: all 0.3s; }
.speed-controls button:hover { border-color: #00E5FF; color: #fff; }
.speed-controls button.active { background: #00E5FF; color: #000; border-color: #00E5FF; box-shadow: 0 0 10px rgba(0, 229, 255, 0.6); }
</style>