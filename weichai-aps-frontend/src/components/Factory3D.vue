<script setup>
import { ref, onMounted, onBeforeUnmount, reactive } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls'

const containerRef = ref(null)
const labelsContainerRef = ref(null)
const stationsContainerRef = ref(null)

const emit = defineEmits(['update-stations', 'update-kpi'])

// ==========================================
// 🌟 1:1 还原 HTML V9 物理测绘参数
// ==========================================
const BOX_S = 0.5; 
const SURFACE_LOWER = 0.3; 
const SURFACE_UPPER = 3.5; 
const Y_LOWER = SURFACE_LOWER + BOX_S / 2; 
const Y_UPPER = SURFACE_UPPER + BOX_S / 2; 
const START_X = -90; 

const currentConfig = {
  num_stations: 16,
  belt_speed: 0.7, 
  station_positions: [41, 45, 47, 50, 52, 56, 59, 62, 70, 74, 76, 79, 83, 86, 88, 92],
  branch_in_length: 9.552,
  branch_out_length: 10.395
};
const branchLen = currentConfig.branch_in_length;
const branchOutLen = currentConfig.branch_out_length;

let scene, camera, renderer, controls, clock;
let animationId = null;

const isPlaying = ref(false)
const playbackSpeed = ref(5) 
const currentTimeStr = ref('0.0')
const timeSliderVal = ref(0)

let simData = [];
const activeBoxes = new Map();
const stations = [];
let currentSimTime = 0;
let maxTime = 100;
let lastTime = 0;
let orderStats = { total: 0, completed: 0, map: {} };

const kpiData = reactive({
  ordersDone: 0, ordersTotal: 0,
  boxesDone: 0, boxesActive: 0, boxesTotal: 0,
  progressPct: 0, currentTime: 0, maxTime: 0
})

const tooltipParams = reactive({
  visible: false,
  x: 0, y: 0,
  orderId: '', partType: '', stName: ''
})

function togglePlay() {
  if (simData.length === 0) return;
  isPlaying.value = !isPlaying.value;
  if (isPlaying.value) clock.start();
  else clock.stop();
}

function setSpeed(speed) {
  playbackSpeed.value = Number(speed);
}

defineExpose({
  loadAndPlay(playbook) {
    parsePlaybook(playbook);
    isPlaying.value = true;
    clock.start();
  },
  togglePlay,
  setSpeed
})

function createWarningTexture() {
  const canvas = document.createElement('canvas'); canvas.width = 256; canvas.height = 256; const ctx = canvas.getContext('2d'); ctx.fillStyle = '#FFB800'; ctx.fillRect(0,0,256,256); ctx.fillStyle = '#111111';
  for(let i = -256; i < 512; i += 40) { ctx.beginPath(); ctx.moveTo(i, 0); ctx.lineTo(i+20, 0); ctx.lineTo(i+256+20, 256); ctx.lineTo(i+256, 256); ctx.fill(); }
  const tex = new THREE.CanvasTexture(canvas); tex.wrapS = THREE.RepeatWrapping; tex.wrapT = THREE.RepeatWrapping; tex.repeat.set(1, 2); return tex;
}
function stringToColor(str) { 
  let hash = 0; for (let i = 0; i < str.length; i++) hash = str.charCodeAt(i) + ((hash << 5) - hash); 
  return new THREE.Color(`hsl(${Math.abs(hash) % 360}, 85%, 60%)`); 
}
function lerp(s, e, p) { return s + (e - s) * Math.max(0, Math.min(1, p)); }

function createBeltCore(len, color, y, z, hideFrontRail=false, centerX=0) { 
  const group = new THREE.Group(); 
  const track = new THREE.Mesh(new THREE.BoxGeometry(len, 0.1, 1.2), new THREE.MeshStandardMaterial({ color: color })); 
  track.position.set(centerX, y - 0.05, z); track.receiveShadow = true; group.add(track); 
  const rMat = new THREE.MeshStandardMaterial({ color: 0xA0B2C6, metalness: 0.7 }); 
  if (!hideFrontRail) { const rF = new THREE.Mesh(new THREE.BoxGeometry(len, 0.2, 0.05), rMat); rF.position.set(centerX, y + 0.05, z + 0.6); group.add(rF); } 
  const rB = new THREE.Mesh(new THREE.BoxGeometry(len, 0.2, 0.05), rMat); rB.position.set(centerX, y + 0.05, z - 0.6); group.add(rB); 
  return group; 
}

const initScene = () => {
  clock = new THREE.Clock();
  scene = new THREE.Scene(); scene.background = new THREE.Color(0x08121C);
  
  camera = new THREE.PerspectiveCamera(45, containerRef.value.clientWidth / containerRef.value.clientHeight, 0.1, 1000); 
  camera.position.set(-20, 90, 140); camera.lookAt(20, 0, 0);

  renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance", alpha: true }); 
  renderer.setSize(containerRef.value.clientWidth, containerRef.value.clientHeight); 
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap; 
  containerRef.value.appendChild(renderer.domElement);

  controls = new OrbitControls(camera, renderer.domElement); 
  controls.enableDamping = true; controls.maxPolarAngle = Math.PI / 2.05;

  scene.add(new THREE.AmbientLight(0xffffff, 0.8)); scene.add(new THREE.HemisphereLight(0xffffff, 0x445577, 0.6));
  const dirLight = new THREE.DirectionalLight(0xffffff, 1.2); dirLight.position.set(30, 80, 40); dirLight.castShadow = true; dirLight.shadow.mapSize.width = 2048; dirLight.shadow.mapSize.height = 2048; scene.add(dirLight);

  const floor = new THREE.Mesh(new THREE.PlaneGeometry(450, 200), new THREE.MeshStandardMaterial({ color: 0x0A1525, roughness: 0.15, metalness: 0.8 })); 
  floor.rotation.x = -Math.PI / 2; floor.position.y = -0.1; floor.receiveShadow = true; scene.add(floor); 
  scene.add(new THREE.GridHelper(300, 100, 0x1E3A5F, 0x112233));

  const factoryGroup = new THREE.Group();
  scene.add(factoryGroup);

  const posArray = currentConfig.station_positions;
  const maxDist = Math.max(...posArray);
  const BELT_LEN = maxDist + 20; 
  const centerX = START_X + BELT_LEN / 2;

  const whGroup = new THREE.Group(); 
  const whX = START_X - 8; const whFrameMat = new THREE.MeshStandardMaterial({color: 0xE8F0FE, roughness: 0.2, metalness: 0.2});
  const frameBottom = new THREE.Mesh(new THREE.BoxGeometry(16, 2, 14), whFrameMat); frameBottom.position.set(whX, 1, 0); whGroup.add(frameBottom); 
  const frameTop = new THREE.Mesh(new THREE.BoxGeometry(16, 2, 14), whFrameMat); frameTop.position.set(whX, 13, 0); whGroup.add(frameTop); 
  const frameBack = new THREE.Mesh(new THREE.BoxGeometry(2, 10, 14), whFrameMat); frameBack.position.set(whX - 7, 7, 0); whGroup.add(frameBack); 
  const frameSide = new THREE.Mesh(new THREE.BoxGeometry(16, 10, 2), whFrameMat); frameSide.position.set(whX, 7, -6); whGroup.add(frameSide);
  const glassMat = new THREE.MeshPhysicalMaterial({ color: 0x88CCFF, transparent: true, opacity: 0.25, metalness: 0.9, roughness: 0.05, transmission: 0.8, side: THREE.DoubleSide }); 
  const glass = new THREE.Mesh(new THREE.BoxGeometry(14.2, 10, 12.2), glassMat); glass.position.set(whX + 1, 7, 1); whGroup.add(glass);
  const rackMat = new THREE.MeshStandardMaterial({color: 0xFF5500, metalness: 0.8, roughness:0.2}); 
  for(let r = -3; r <= 5; r += 4) { for(let c = whX - 4; c <= whX + 4; c += 4) { const rack = new THREE.Mesh(new THREE.BoxGeometry(2.5, 9, 1.2), rackMat); rack.position.set(c, 6.5, r); whGroup.add(rack); } }
  const tunnelMat = new THREE.MeshStandardMaterial({map: createWarningTexture()}); const holeMat = new THREE.MeshBasicMaterial({color: 0x000000});
  const lowTun = new THREE.Mesh(new THREE.BoxGeometry(3, 2.2, 2.5), tunnelMat); lowTun.position.set(START_X - 1.5, SURFACE_LOWER + 1.1, 0); whGroup.add(lowTun); 
  const lowHole = new THREE.Mesh(new THREE.BoxGeometry(3.1, 2.0, 2.0), holeMat); lowHole.position.set(START_X - 1.5, SURFACE_LOWER + 1.1, 0); whGroup.add(lowHole); 
  const upTun = new THREE.Mesh(new THREE.BoxGeometry(3, 2.2, 2.5), tunnelMat); upTun.position.set(START_X - 1.5, SURFACE_UPPER + 1.1, 0); whGroup.add(upTun); 
  const upHole = new THREE.Mesh(new THREE.BoxGeometry(3.1, 2.0, 2.0), holeMat); upHole.position.set(START_X - 1.5, SURFACE_UPPER + 1.1, 0); whGroup.add(upHole);
  factoryGroup.add(whGroup);

  factoryGroup.add(createBeltCore(BELT_LEN, 0x111827, SURFACE_LOWER, 0, true, centerX)); 
  factoryGroup.add(createBeltCore(BELT_LEN, 0x111827, SURFACE_UPPER, 0, true, centerX));
  const pMat = new THREE.MeshStandardMaterial({ color: 0x475569, metalness: 0.6 }); 
  for(let i = START_X + 5; i < START_X + BELT_LEN - 10; i += 12) { 
    const p1 = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, SURFACE_UPPER), pMat); p1.position.set(i, SURFACE_UPPER/2, 0.65); p1.castShadow=true; factoryGroup.add(p1); 
    const p2 = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, SURFACE_UPPER), pMat); p2.position.set(i, SURFACE_UPPER/2, -0.65); p2.castShadow=true; factoryGroup.add(p2); 
  }

  for (let i = 0; i < currentConfig.num_stations; i++) {
    const x = START_X + posArray[i]; 
    const branchBelt = createBeltCore(branchLen, 0x1E293B, SURFACE_LOWER, 0, false, 0); 
    branchBelt.rotation.y = Math.PI / 2; branchBelt.position.set(x, 0, 0.6 + branchLen / 2); factoryGroup.add(branchBelt);
    
    const dY = SURFACE_UPPER - SURFACE_LOWER; const dZ = branchOutLen; const rLen = Math.sqrt(dY*dY + dZ*dZ); const rAngle = Math.atan2(dY, dZ); 
    const rampGroup = new THREE.Group(); rampGroup.position.set(x, SURFACE_LOWER + dY/2, 0.6 + dZ/2); rampGroup.rotation.x = rAngle; 
    const rampMesh = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.1, rLen), new THREE.MeshStandardMaterial({color: 0x1E293B})); rampMesh.position.set(0, -0.05, 0); rampMesh.castShadow = true; rampMesh.receiveShadow = true; rampGroup.add(rampMesh); 
    const rrMat = new THREE.MeshStandardMaterial({color: 0xFF6B00, metalness:0.4}); 
    const rrF = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.2, rLen), rrMat); rrF.position.set(0.6, 0.05, 0); rampGroup.add(rrF); 
    const rrB = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.2, rLen), rrMat); rrB.position.set(-0.6, 0.05, 0); rampGroup.add(rrB); factoryGroup.add(rampGroup);
    
    const deskMat = new THREE.MeshStandardMaterial({color: 0xF8FAFC, metalness:0.3});
    const desk = new THREE.Mesh(new THREE.BoxGeometry(2.0, 0.2, 1.2), deskMat); desk.position.set(x, SURFACE_LOWER - 0.1, branchLen + 1.2); desk.castShadow = true; desk.receiveShadow = true; factoryGroup.add(desk); 
    
    const screen = new THREE.Mesh(new THREE.PlaneGeometry(1.5, 0.8), new THREE.MeshStandardMaterial({color: 0x00E5FF, emissive: 0x00E5FF, emissiveIntensity: 0.1, transparent: true, opacity: 0.8, side: THREE.DoubleSide})); screen.position.set(x, 0.8, branchLen + 1.9); screen.rotation.x = -Math.PI / 8; factoryGroup.add(screen); 
    const light = new THREE.Mesh(new THREE.SphereGeometry(0.15), new THREE.MeshStandardMaterial({color: 0x00ffcc, emissive: 0x00aa88})); light.position.set(x - 1.0, 1.4, branchLen + 1.9); factoryGroup.add(light); 
    const laser = new THREE.Mesh(new THREE.PlaneGeometry(1.2, 0.05), new THREE.MeshBasicMaterial({color: 0x00FF00, transparent: true, opacity: 0.8, side: THREE.DoubleSide})); laser.position.set(x, Y_LOWER + 0.25, branchLen + 1.2); laser.visible = false; factoryGroup.add(laser);
    
    const worker = new THREE.Group(); const mSkin = new THREE.MeshStandardMaterial({color: 0xFFB800}); const mCloth = new THREE.MeshStandardMaterial({color: 0x1E3A8A}); const mVest = new THREE.MeshStandardMaterial({color: 0x10B981}); 
    const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, 0.4), mCloth); leg.position.set(x-0.15, 0.2, branchLen + 2.3); worker.add(leg); 
    const leg2 = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, 0.4), mCloth); leg2.position.set(x+0.15, 0.2, branchLen + 2.3); worker.add(leg2); 
    const torso = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.6, 0.3), mVest); torso.position.set(x, 0.7, branchLen + 2.3); worker.add(torso); 
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.15), mSkin); head.position.set(x, 1.15, branchLen + 2.3); worker.add(head); 
    const hat = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.18, 0.1), new THREE.MeshStandardMaterial({color: 0xFF0000})); hat.position.set(x, 1.25, branchLen + 2.3); worker.add(hat); 
    const armG = new THREE.CylinderGeometry(0.06, 0.06, 0.5); const armL = new THREE.Mesh(armG, mVest); armL.position.set(x-0.3, 0.8, branchLen + 2.0); armL.rotation.x = -Math.PI/3; armL.rotation.z = -Math.PI/8; worker.add(armL); 
    const armR = new THREE.Mesh(armG, mVest); armR.position.set(x+0.3, 0.8, branchLen + 2.0); armR.rotation.x = -Math.PI/3; armR.rotation.z = Math.PI/8; worker.add(armR); worker.castShadow = true; factoryGroup.add(worker);
    
    const stLabel = document.createElement('div'); stLabel.className = 'station-label'; stLabel.innerText = `S${(i+1).toString().padStart(2, '0')}`; 
    stationsContainerRef.value.appendChild(stLabel); 
    
    stations.push({ 
        id: i, x: x, screen: screen, labelDom: stLabel, laser: laser, light: light, 
        desk: desk, worker: worker, isPoweredOff: false
    });
  }
}

// ==========================================
// 🌟 终极修复：使用真实的 tSpawn，彻底激活排队逻辑！
// ==========================================
const parsePlaybook = (playbook) => {
  try {
    activeBoxes.forEach(b => {
      scene.remove(b.mesh);
      if (b.label && b.label.parentNode) b.label.parentNode.removeChild(b.label);
    });
    activeBoxes.clear();
    
    if (!playbook || !playbook.timeline || playbook.timeline.length === 0) return;

    const timeline = playbook.timeline;
    const baseTimeMs = new Date(timeline[0].spawn_time || timeline[0].start_time).getTime();
    const uniqueOrders = new Set();
    
    orderStats = { total: 0, completed: 0, map: {} };
    const BELT_SPEED = currentConfig.belt_speed; 

    simData = timeline.map(item => {
      uniqueOrders.add(item.order_id);
      const orderId = item.order_id;
      if(!orderStats.map[orderId]) { orderStats.map[orderId] = { totalBoxes: 0, boxesFinished: 0 }; }
      orderStats.map[orderId].totalBoxes++;

      // 🌟 获取绝对真实的后端下发和加工时间
      const tSpawn = (new Date(item.spawn_time || item.start_time).getTime() - baseTimeMs) / 1000;
      const tStart = (new Date(item.start_time).getTime() - baseTimeMs) / 1000;
      const tEnd = (new Date(item.end_time).getTime() - baseTimeMs) / 1000;
      
      const stIdx = item.target_station - 1;
      const eX = stations[stIdx].x; 
      
      const distIn = Math.abs(eX - START_X);
      const distOut = Math.abs(eX - START_X); 
      
      // 🌟【真正释放排队的灵魂代码】废除伪造的 2秒 固定排队时间！
      // 真实拐入支线时间 = 出生时间 + 主线行驶耗时
      let tl = { start: tStart, return_main: tEnd };
      tl.spawn = tSpawn;
      tl.branch = tSpawn + (distIn / BELT_SPEED); 
      
      const timeUpBranch = branchOutLen / BELT_SPEED;
      tl.return_branch_end = tl.return_main + timeUpBranch;
      const timeReturnMain = distOut / BELT_SPEED;
      tl.exit = tl.return_branch_end + timeReturnMain;

      return {
        box_id: item.box_id,
        stIdx: stIdx,
        timeline: tl,
        sku: item.sku || ''
      };
    });

    const activeStationIds = Array.isArray(playbook.active_station_ids)
      ? new Set(playbook.active_station_ids.map(item => Number(item)))
      : null;
    const activeCount = playbook.active_stations || 16;
    stations.forEach((st, idx) => {
      st.isPoweredOff = activeStationIds && activeStationIds.size > 0
        ? !activeStationIds.has(idx + 1)
        : (idx >= activeCount);
      if (st.isPoweredOff) {
        st.worker.visible = false; 
        st.desk.material.color.setHex(0x334155); st.desk.material.emissive.setHex(0x000000);
        st.screen.material.color.setHex(0x1e293b); st.light.material.color.setHex(0x1e293b);  
        st.labelDom.style.color = '#475569'; st.labelDom.style.borderColor = '#475569'; st.labelDom.style.background = 'rgba(10, 15, 25, 0.9)';
        st.labelDom.innerText = `S${(st.id+1).toString().padStart(2, '0')} (休眠)`;
      } else {
        st.worker.visible = true; 
        st.desk.material.color.setHex(0xF8FAFC); st.desk.material.emissive.setHex(0x000000);
        st.screen.material.color.setHex(0x00E5FF);
        st.labelDom.style.color = '#00E5FF'; st.labelDom.style.borderColor = '#00E5FF'; st.labelDom.style.background = 'rgba(10, 25, 45, 0.9)';
        st.labelDom.innerText = `S${(st.id+1).toString().padStart(2, '0')}`;
      }
    });

    orderStats.total = uniqueOrders.size;
    
    let localMaxTime = 10;
    for (let i=0; i<simData.length; i++) {
        if (simData[i].timeline.exit > localMaxTime) {
            localMaxTime = simData[i].timeline.exit;
        }
    }
    maxTime = localMaxTime + 0.5;

    kpiData.ordersTotal = orderStats.total; kpiData.boxesTotal = timeline.length; kpiData.maxTime = maxTime;
    currentSimTime = 0; lastTime = 0; 
  } catch (e) {
    console.error("🚨 剧本解析发生错误：", e);
  }
}

const raycaster = new THREE.Raycaster();
const mouse = new THREE.Vector2();

const handleMouseMove = (event) => {
  if (!containerRef.value || !camera) return;

  const rect = containerRef.value.getBoundingClientRect();
  const clientX = event.clientX - rect.left;
  const clientY = event.clientY - rect.top;

  mouse.x = (clientX / rect.width) * 2 - 1;
  mouse.y = -(clientY / rect.height) * 2 + 1;

  raycaster.setFromCamera(mouse, camera);
  
  const boxMeshes = Array.from(activeBoxes.values()).map(b => b.mesh);
  const intersects = raycaster.intersectObjects(boxMeshes);

  if (intersects.length > 0) {
    const boxObj = intersects[0].object;
    const data = boxObj.userData;

    let orderId = "未知订单";
    let partType = "未知";
    if (data.id.includes('-P')) {
      const parts = data.id.split('-P');
      orderId = parts[0]; partType = parts[1];
    } else {
      orderId = data.id;
    }

    tooltipParams.orderId = orderId;
    tooltipParams.partType = data.sku || partType;
    tooltipParams.stName = `S${(data.station + 1).toString().padStart(2, '0')}`;
    tooltipParams.x = clientX + 15;
    tooltipParams.y = clientY + 15;
    tooltipParams.visible = true;
    
    document.body.style.cursor = 'pointer';
    activeBoxes.forEach(b => b.mesh.material.emissive.setHex(0x000000));
    boxObj.material.emissive.setHex(0x333333); 
  } else {
    tooltipParams.visible = false;
    document.body.style.cursor = 'default';
    activeBoxes.forEach(b => b.mesh.material.emissive.setHex(0x000000));
  }
};

// ==========================================
// 🌟 排队推挤系统动画
// ==========================================
const updateSimulation = (delta) => {
  if (containerRef.value) {
    stations.forEach(s => { 
      const pos = new THREE.Vector3(s.x, 3.5, branchLen + 1.2); 
      pos.project(camera); 
      if (pos.z < 1) {
        s.labelDom.style.display = 'block';
        s.labelDom.style.left = `${(pos.x * .5 + .5) * containerRef.value.clientWidth}px`; 
        s.labelDom.style.top = `${(pos.y * -.5 + .5) * containerRef.value.clientHeight}px`; 
      } else {
        s.labelDom.style.display = 'none';
      }
    });
  }

  if (!isPlaying.value || simData.length === 0) return;

  let dt = delta * playbackSpeed.value; 
  currentSimTime += dt; 
  if (currentSimTime > maxTime) currentSimTime = maxTime;
  
  currentTimeStr.value = currentSimTime.toFixed(1);
  timeSliderVal.value = currentSimTime;

  let finishedCount = 0; let activeCount = 0;
  let currentOrderProgress = JSON.parse(JSON.stringify(orderStats.map)); 
  let stStatusCount = Array(currentConfig.num_stations).fill(0).map(() => ({ active: false, bufferBoxes: 0, concurrentOrders: new Set() }));

  simData.forEach(boxData => {
    const t = currentSimTime, tl = boxData.timeline, stIdx = boxData.stIdx, eX = stations[stIdx].x;
    const orderId = boxData.box_id.split('-P')[0];

    if (t >= tl.exit) { finishedCount++; currentOrderProgress[orderId].boxesFinished++; } 
    else if (t >= tl.spawn) { activeCount++; }
    
    if (t >= tl.branch && t < tl.return_main) { stStatusCount[stIdx].concurrentOrders.add(orderId); }
    if (t >= tl.branch && t < tl.start) { stStatusCount[stIdx].bufferBoxes++; }
    
    if (t >= tl.start && t < tl.return_main) {
        stStatusCount[stIdx].active = true;
        if (!stations[stIdx].isPoweredOff) {
            stations[stIdx].screen.material.emissiveIntensity = 1.0; 
            stations[stIdx].laser.visible = true; 
            stations[stIdx].laser.position.z = branchLen + Math.sin(t * 10) * 0.35; 
            stations[stIdx].light.material.color.setHex(0x00E5FF); 
            stations[stIdx].light.material.emissive.setHex(0x00E5FF);
        }
    }

    if (t >= tl.spawn && t <= tl.exit) {
        let boxObj = activeBoxes.get(boxData.box_id);
        if (!boxObj) {
            let shortName = "BOX";
            if (boxData.box_id.includes('-P')) {
                const rawSKU = boxData.box_id.split('-P').pop();
                shortName = rawSKU.length > 4 ? rawSKU.slice(-4) : rawSKU;
            }
            const boxColor = stringToColor(boxData.box_id);
            const mesh = new THREE.Mesh(new THREE.BoxGeometry(BOX_S, BOX_S, BOX_S), new THREE.MeshStandardMaterial({ color: boxColor, emissive: 0x000000, roughness:0.2, metalness:0.4 }));
            mesh.castShadow = true; mesh.receiveShadow = true; 
            mesh.userData = {
              id: boxData.box_id,
              station: stIdx,
              sku: boxData.sku
            };
            scene.add(mesh); 
            
            const label = document.createElement('div'); label.className = 'box-label'; label.innerText = "P_" + shortName; 
            labelsContainerRef.value.appendChild(label);
            
            boxObj = { mesh: mesh, label: label, currentZ: 0 }; activeBoxes.set(boxData.box_id, boxObj);
        }

        const box = boxObj.mesh; let targetX, targetY, targetZ;

        // 🌟 排队拥挤与平滑蠕动算法
        if (t < tl.branch) { 
            targetX = lerp(START_X, eX, (t-tl.spawn)/(tl.branch-tl.spawn)); targetY = Y_LOWER; targetZ = 0; boxObj.currentZ = targetZ; 
        } else if (t < tl.return_main) {
            targetX = eX; targetY = Y_LOWER; 
            let limitZ;
            
            // 如果还未开始加工，动态计算前面有几个在排队的箱子
            if (t < tl.start) {
                let boxesAhead = 0;
                for(let i=0; i<simData.length; i++) { 
                    if (simData[i].stIdx === stIdx 
                        && simData[i].box_id !== boxData.box_id 
                        && simData[i].timeline.branch < tl.branch 
                        && t < simData[i].timeline.return_main) {
                        boxesAhead++; 
                    }
                }
                // 每多一个箱子排队，极限位置往后退 0.8 个单位距离
                limitZ = boxesAhead === 0 ? branchLen : (branchLen - 1.2) - (boxesAhead - 1) * 0.8; 
            } else { 
                limitZ = branchLen; // 开始加工时，占据工位
            } 

            // 平滑推挤：让箱子以皮带速度贴上去，而不是闪现
            if (boxObj.currentZ < limitZ) { 
                boxObj.currentZ += dt * currentConfig.belt_speed; 
                if (boxObj.currentZ > limitZ) boxObj.currentZ = limitZ; 
            } else { 
                boxObj.currentZ = limitZ; 
            }
            targetZ = boxObj.currentZ;
        } else if (t < tl.return_branch_end) { 
            let progress = (t - tl.return_main) / (tl.return_branch_end - tl.return_main);
            targetX = eX; targetY = lerp(Y_LOWER, Y_UPPER, progress); targetZ = lerp(branchLen, 0, progress); boxObj.currentZ = targetZ; 
        } else {
            targetX = lerp(eX, START_X, (t - tl.return_branch_end) / (tl.exit - tl.return_branch_end)); targetY = Y_UPPER; targetZ = 0; boxObj.currentZ = targetZ;
        }
        
        box.position.set(targetX, targetY, targetZ); boxObj.label.style.display = 'block'; 
        
        if (containerRef.value) {
          const screenPos = box.position.clone(); screenPos.y += 0.5; screenPos.project(camera);
          boxObj.label.style.left = `${(screenPos.x * .5 + .5) * containerRef.value.clientWidth}px`; 
          boxObj.label.style.top = `${(screenPos.y * -.5 + .5) * containerRef.value.clientHeight}px`;
        }
    } else { 
        let b = activeBoxes.get(boxData.box_id); 
        if (b) { scene.remove(b.mesh); if(b.label && b.label.parentNode) b.label.parentNode.removeChild(b.label); activeBoxes.delete(boxData.box_id); } 
    }
  });

  for(let i=0; i<currentConfig.num_stations; i++) {
      if (stations[i].isPoweredOff) continue; 
      if (!stStatusCount[i].active) { 
          stations[i].screen.material.emissiveIntensity = 0.1; 
          stations[i].laser.visible = false; 
          stations[i].light.material.color.setHex(0x00ffcc); 
          stations[i].light.material.emissive.setHex(0x00aa88); 
      }
  }

  let completedOrdersCount = 0;
  Object.values(currentOrderProgress).forEach(order => { if (order.boxesFinished === order.totalBoxes) completedOrdersCount++; });
  
  kpiData.ordersDone = completedOrdersCount;
  kpiData.boxesDone = finishedCount;
  kpiData.boxesActive = activeBoxes.size;
  kpiData.progressPct = simData.length > 0 ? ((finishedCount / simData.length) * 100).toFixed(1) : 0;
  kpiData.currentTime = currentSimTime;

  emit('update-kpi', kpiData);

  const statusArray = stStatusCount.map((st, idx) => ({
    active: st.active,
    orderCount: st.concurrentOrders.size,
    maxOrders: 2,
    isPoweredOff: stations[idx].isPoweredOff
  }));
  emit('update-stations', statusArray);

  if (finishedCount === simData.length && simData.length > 0) isPlaying.value = false;
  lastTime = currentSimTime;
}

const animate = () => {
  animationId = requestAnimationFrame(animate)
  const delta = clock.getDelta()
  updateSimulation(delta)
  controls.update()
  renderer.render(scene, camera)
}

const handleResize = () => {
  camera.aspect = containerRef.value.clientWidth / containerRef.value.clientHeight
  camera.updateProjectionMatrix()
  renderer.setSize(containerRef.value.clientWidth, containerRef.value.clientHeight)
}

onMounted(() => { 
  initScene(); animate(); window.addEventListener('resize', handleResize);
  if (containerRef.value) { containerRef.value.addEventListener('mousemove', handleMouseMove); }
})

onBeforeUnmount(() => { 
  window.removeEventListener('resize', handleResize); 
  if (containerRef.value) { containerRef.value.removeEventListener('mousemove', handleMouseMove); }
  cancelAnimationFrame(animationId); renderer.dispose() 
})
</script>

<template>
  <div class="factory-container" ref="containerRef">
    
    <div ref="labelsContainerRef" class="labels-layer"></div>
    <div ref="stationsContainerRef" class="labels-layer"></div>

    <div class="custom-tooltip" v-show="tooltipParams.visible" :style="{ left: tooltipParams.x + 'px', top: tooltipParams.y + 'px' }">
      <div style="border-bottom:1px solid #00E5FF; margin-bottom:10px; padding-bottom:6px; font-size:14px; text-shadow: 0 0 5px #00E5FF;">
        <strong>📦 物理物料箱档案</strong>
      </div>
      <div class="tooltip-row"><span class="tooltip-label">归属母订单</span><span class="tooltip-value highlight-text">{{ tooltipParams.orderId }}</span></div>
      <div class="tooltip-row"><span class="tooltip-label">子零件型号</span><span class="tooltip-value">P-{{ tooltipParams.partType }}</span></div>
      <div class="tooltip-row" style="margin-top:8px; border-top:1px dashed #3A5A7A; padding-top:8px;"><span class="tooltip-label">目标加工站</span><span class="tooltip-value" style="color:#00FF00;">🎯 {{ tooltipParams.stName }}</span></div>
    </div>

    <div class="time-overlay" v-if="simData.length > 0">
      <div class="time-value">T+ {{ currentTimeStr }} s</div>
      <div class="time-target">/ {{ maxTime.toFixed(1) }} s</div>
    </div>

    <div class="playback-controls">
      <button class="ctrl-btn play-btn" @click="togglePlay" :disabled="simData.length === 0">{{ isPlaying ? '⏸️ 暂停' : '▶️ 播放' }}</button>
      <input type="range" class="time-slider" min="0" :max="maxTime" :value="timeSliderVal" disabled />
      <div class="speed-group">
        <select class="speed-select" v-model="playbackSpeed" @change="setSpeed($event.target.value)">
            <option :value="1">1x 实时</option>
            <option :value="5">5x 倍速</option>
            <option :value="10">10x 极速</option>
            <option :value="20">20x 超神</option>
        </select>
      </div>
    </div>

    <div class="empty-overlay" v-if="simData.length === 0">
      <div class="icon">🏭</div>
      <div>数字孪生物理引擎就绪，等待注入排产剧本...</div>
    </div>
  </div>
</template>

<style>
.box-label { position: absolute; color: #fff; background: rgba(0, 0, 0, 0.9); padding: 3px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; border: 1px solid #00E5FF; transform: translate(-50%, -100%); display: none; z-index: 50; pointer-events: none; }
.station-label { position: absolute; color: #00E5FF; background: rgba(10, 25, 45, 0.9); padding: 3px 10px; border-radius: 5px; font-size: 14px; font-weight: 900; border: 1px solid #00E5FF; transform: translate(-50%, -50%); z-index: 40; pointer-events: none; transition: 0.3s; }
</style>

<style scoped>
.factory-container { width: 100%; height: 100%; position: relative; background: radial-gradient(circle at center, #0F1E32 0%, #050A10 100%); border-radius: 12px; overflow: hidden; }
.labels-layer { position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; z-index: 10; }

.custom-tooltip { position: absolute; background: rgba(15, 25, 45, 0.95); color: #fff; padding: 15px; border-radius: 8px; font-size: 13px; border: 1px solid #00E5FF; pointer-events: none; z-index: 200; backdrop-filter: blur(8px); box-shadow: 0 10px 30px rgba(0,229,255,0.2); min-width: 200px; }
.tooltip-row { margin-bottom: 6px; display: flex; justify-content: space-between; }
.tooltip-label { color: #A0B2C6; font-weight: bold; }
.tooltip-value { font-weight: 900; color: #FFFFFF; }
.highlight-text { color: #FFB800; }

.empty-overlay { position: absolute; top: 0; left: 0; width: 100%; height: 100%; display: flex; flex-direction: column; justify-content: center; align-items: center; color: #1E3A5F; font-size: 16px; font-weight: bold; background: rgba(10, 21, 37, 0.6); z-index: 15; }
.empty-overlay .icon { font-size: 40px; margin-bottom: 10px; filter: grayscale(1); opacity: 0.5;}

.time-overlay { position: absolute; top: 20px; left: 20px; background: rgba(10, 25, 45, 0.85); border: 1px solid #00E5FF; padding: 10px 20px; border-radius: 8px; display: flex; align-items: baseline; gap: 10px; box-shadow: 0 0 15px rgba(0, 229, 255, 0.2); z-index: 20; }
.time-value { color: #00E5FF; font-family: monospace; font-size: 24px; font-weight: bold; }
.time-target { color: #A0B2C6; font-family: monospace; font-size: 14px; }

.playback-controls { position: absolute; bottom: 25px; left: 50%; transform: translateX(-50%); background: rgba(15, 25, 40, 0.95); padding: 12px 25px; border-radius: 40px; z-index: 100; display: flex; align-items: center; gap: 15px; border: 1px solid #1E3A5F; box-shadow: 0 5px 20px rgba(0,0,0,0.8); }
.ctrl-btn { background: linear-gradient(135deg, #00E5FF, #0077FF); color: #fff; border: none; padding: 8px 18px; border-radius: 20px; cursor: pointer; font-weight: bold; font-size: 13px; transition: 0.3s; }
.ctrl-btn:hover:not(:disabled) { transform: scale(1.05); }
.ctrl-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.time-slider { flex-grow: 1; accent-color: #00E5FF; height: 6px; background: #1A2B4C; border-radius: 3px; min-width: 300px; }
.speed-select { background:#0F1E32; color:#fff; border:1px solid #00E5FF; padding:6px; border-radius:5px; font-weight:bold; font-size: 13px; cursor: pointer;}
</style>
