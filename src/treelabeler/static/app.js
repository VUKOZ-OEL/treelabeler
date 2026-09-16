import * as THREE from 'three';
import { OrbitControls } from '/static/vendor/OrbitControls.js';

const $ = (sel) => document.querySelector(sel);

const state = {
  files: [],
  categories: [],   // [{id, name, group, shortcut, description}]
  groups: [],       // [{id, label}]
  progress: { total: 0, labeled: 0 },
  currentFileId: null,
  currentDist2Dmt: null,    // z externi DB — korekce vysky mrizky
  ctxVisible: false,        // prepinac zobrazeni okolnich bodu
  selectedType: null,      // tree_type kategorie
  selectedQuality: null,   // quality kategorie
};

function showErr(msg) {
  const el = $('#err');
  el.textContent = msg;
  el.style.display = msg ? 'block' : 'none';
}

// --- three.js viewer -----------------------------------------------------
let renderer, scene, camera, controls, pointsObj, ctxObj = null, gridHelper = null, axesCanvas = null, axesCtx = null;

function initViewer() {
  const el = $('#viewer');
  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  el.appendChild(renderer.domElement);

  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0a0f14);

  camera = new THREE.PerspectiveCamera(60, 1, 0.01, 100000);
  camera.position.set(10, 10, 10);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.rotateSpeed = 0.9;
  controls.zoomSpeed = 1.0;
  controls.panSpeed = 0.8;
  controls.minDistance = 0.01;
  controls.maxDistance = 100000;

  const amb = new THREE.AmbientLight(0xffffff, 0.6);
  scene.add(amb);
  const dir = new THREE.DirectionalLight(0xffffff, 0.8);
  dir.position.set(50, 100, 50);
  scene.add(dir);

  // overlay osy (canvas vpravo dole) — musí sedět rozměry canvasu i holderu,
  // jinak se obsah uřízne (200px kreslený do 100px rámečku)
  const cv = document.createElement('canvas');
  cv.width = 100; cv.height = 100;
  cv.style.width = '100px'; cv.style.height = '100px';
  const holder = $('#axes-overlay');
  holder.innerHTML = '';
  holder.appendChild(cv);
  axesCanvas = cv;
  axesCtx = cv.getContext('2d');

  window.addEventListener('resize', resize);

  // ResizeObserver na samotný viewport — chytí i změny layoutu, které
  // window resize nezpůsobí (otevření DevTools vedle okna, atd.)
  const wrap = $('#viewer-wrap');
  const ro = new ResizeObserver(resize);
  ro.observe(wrap);

  resize();
  animate();
}

function drawAxesOverlay() {
  if (!axesCtx) return;
  const ctx = axesCtx;
  ctx.clearRect(0, 0, 100, 100);
  ctx.save();
  ctx.translate(42, 58);

  const axes = [
    { v: new THREE.Vector3(1, 0, 0), c: '#ef4444', label: 'X' },
    { v: new THREE.Vector3(0, 1, 0), c: '#22c55e', label: 'Z' },   // Z = výška (naše Y je ze Z)
    { v: new THREE.Vector3(0, 0, 1), c: '#3b82f6', label: 'Y' },
  ];
  const camQ = camera.quaternion.clone().invert();
  ctx.lineWidth = 2;
  ctx.font = 'bold 13px system-ui';
  axes.forEach((ax) => {
    const p = ax.v.clone().applyQuaternion(camQ);
    const x2 = p.x * 30, y2 = -p.y * 30;
    ctx.strokeStyle = ax.c;
    ctx.fillStyle = ax.c;
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.lineTo(x2, y2);
    ctx.stroke();
    ctx.fillText(ax.label, x2 + 2, y2 + 4);
  });
  ctx.restore();
}

function drawHeightScale(dy) {
  // měřítko výšky (osa Z) — text v levém dolním rohu
  const el = $('#height-scale');
  if (!el) return;
  if (!dy || dy <= 0) { el.textContent = ''; return; }
  // zaokrouhli na hezkou hodnotu
  const step = niceStep(dy / 4);
  el.textContent = `Height: ${dy.toFixed(1)} m | step: ${step.toFixed(1)} m`;
}

function niceStep(v) {
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const m = v / p;
  if (m < 1.5) return 1 * p;
  if (m < 3) return 2 * p;
  if (m < 7) return 5 * p;
  return 10 * p;
}

function resize() {
  const el = $('#viewer-wrap');
  if (!el) return;
  const rect = el.getBoundingClientRect();
  const w = Math.max(1, Math.round(rect.width));
  const h = Math.max(1, Math.round(rect.height));
  renderer.setPixelRatio(window.devicePixelRatio);
  // setSize S nastavením CSS (updateStyle=true, default): canvas.style.width/height = w/h px,
  // buffer zustane w*pixelRatio. Bez toho (false) se na displejich se scalingem (DPR>1)
  // canvas zobrazi 1.5x vetsi a stred renderu se posune do praveho dolniho rohu viewportu.
  renderer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}

function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
  drawAxesOverlay();
}

function b64ToArrayBuffer(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

async function loadTree(fileId) {
  showErr('');
  const res = await fetch(`/api/file/${fileId}/points`);
  if (!res.ok) { showErr('Failed to load points: ' + res.statusText); return; }
  const payload = await res.json();
  document.title = `TreeLabeler — ${state.files.find((f) => f.id === fileId)?.filename || fileId}`;

  if (pointsObj) {
    scene.remove(pointsObj);
    pointsObj.geometry.dispose();
    pointsObj.material.dispose();
    pointsObj = null;
  }
  if (gridHelper) {
    scene.remove(gridHelper);
    gridHelper.geometry.dispose();
    gridHelper.material.dispose();
    gridHelper = null;
  }
  if (ctxObj) {
    ctxObj.traverse((c) => { if (c.geometry) c.geometry.dispose(); if (c.material) c.material.dispose(); });
    scene.remove(ctxObj);
    ctxObj = null;
  }
  // reset prepinace contextu — na novem stromu je vzdy off, zapina se explicitne
  state.ctxVisible = false;
  $('#btn-ctx').classList.remove('active');

  // float64 ze serveru (presnost), pak prevedeme na float32 pro WebGL
  const pos64 = new Float64Array(b64ToArrayBuffer(payload.positions_b64));
  const origin = payload.origin;

  // Centrovaní v double precision: odecteme pivot ve float64, pak az float32
  const n = pos64.length / 3;
  const centered = new Float32Array(pos64.length);
  const ox = origin[0], oy = origin[1], oz = origin[2];
  for (let i = 0; i < n; i++) {
    const x = pos64[3 * i] - ox;
    const y = pos64[3 * i + 1] - oy;
    const z = pos64[3 * i + 2] - oz;
    centered[3 * i] = x;
    centered[3 * i + 1] = z;
    centered[3 * i + 2] = y;
  }

  const geom = new THREE.BufferGeometry();
  geom.setAttribute('position', new THREE.BufferAttribute(centered, 3));
  geom.computeBoundingBox();
  geom.computeBoundingSphere();

  const bb = geom.boundingBox;
  const dy = bb.max.y - bb.min.y;
  // velikost bodu podle velikosti stromu (prumer vsech rozmeru)
  const avgDim = ((bb.max.x - bb.min.x) + dy + (bb.max.z - bb.min.z)) / 3 || 1;
  // vyber barvy podle aktualnich labelu (hotovy vs nehotovy)
  const fileRec = state.files.find((f) => f.id === fileId);
  const { label, rgb } = colorForLabels(fileRec?.tree_type, fileRec?.quality);

  const mat = new THREE.PointsMaterial({
    size: Math.max(avgDim / 200, 0.01),
    color: rgb,
    sizeAttenuation: true,
    transparent: true,
    opacity: 0.92,
    depthWrite: true,
  });
  pointsObj = new THREE.Points(geom, mat);

  // Měřcí mřížka: 3x3 buňky po 1 m, ve výšce nejnižšího bodu mračna (osa Z).
  // Body jsou centrované kolem pivota; výška Z z LAZ jde ve three.js na osu Y,
  // takže rovina mřížky je Y = bb.min.y (nejnižší bod mračna).
  // Střed mřížky = XZ souřadnice nejnižšího bodu stromu, aby připadl do střední buňky.
  let lowX = 0, lowZ = 0, lowY = Infinity;
  for (let i = 0; i < n; i++) {
    const yy = centered[3 * i + 1];
    if (yy < lowY) { lowY = yy; lowX = centered[3 * i]; lowZ = centered[3 * i + 2]; }
  }
  // dist2dmt z externi DB: korekce vysky mrizky (zaporna => mrizka vyse)
  const d2 = payload.dist2dmt;
  state.currentDist2Dmt = (typeof d2 === 'number' && isFinite(d2)) ? d2 : 0;
  const grid = new THREE.GridHelper(3, 3, 0xffffff, 0x6b7f95);
  grid.material.transparent = true;
  grid.material.opacity = 0.75;
  grid.position.set(lowX, lowY - state.currentDist2Dmt, lowZ);
  scene.add(grid);
  gridHelper = grid;
  // pamatuj origin — okolni body se centruji na nej pri nacteni
  state.currentOrigin = { ox, oy, oz };
  pointsObj.userData.label = label;
  pointsObj.userData.treeType = fileRec?.tree_type || null;
  pointsObj.userData.quality = fileRec?.quality || null;
  scene.add(pointsObj);

  // Reset kamery: bod rotace = střed bounding boxu, vzdálenost podle FOV
  const center = geom.boundingSphere.center;
  const radius = geom.boundingSphere.radius || 1;

  // aktualizovat velikost rendereru pro případ, že se změnil layout (DevTools, změna okna…)
  resize();

  const fovRad = THREE.MathUtils.degToRad(camera.fov);
  const aspect = camera.aspect || 1;
  // vzdalenost proti FOV — horizontalne i vertikalne; pouzijeme konzervativnější variantu
  const distFitH = radius / Math.tan(fovRad / 2);
  const distFitW = radius / (Math.tan(fovRad / 2) * aspect);
  const dist = Math.max(distFitH, distFitW) * 1.2;

  const startAngle = Math.PI / 4;
  const el = Math.PI / 6;
  camera.position.set(
    center.x + dist * Math.cos(el) * Math.sin(startAngle),
    center.y + dist * Math.sin(el),
    center.z + dist * Math.cos(el) * Math.cos(startAngle)
  );
  camera.near = Math.max(0.01, dist / 100);
  camera.far = dist * 100;
  camera.updateProjectionMatrix();

  // Nastav nový target a ulož ho jako referenční pozici — bez toho by OrbitControls 
  // po reset() vrátil kameru dopredu/zpet do minula.
  controls.target.copy(center);
  controls.saveState();

  controls.update();
  drawHeightScale(dy);

  state.currentFileId = fileId;
  console.log('[treelabeler] loadTree', fileId, {
    center: center.toArray().map(v => +v.toFixed(2)),
    radius: +radius.toFixed(2),
    dist: +dist.toFixed(2),
    camPos: camera.position.toArray().map(v => +v.toFixed(2)),
    target: controls.target.toArray().map(v => +v.toFixed(2)),
  });
  renderFileList();
}

// --- Okolni body (tj. stromy kolem z cloud_segmented_-1.laz) --------------
// lazy-load: nacte se az na prvni zobrazeni, pak se jen prepina viditelnost.
// Barva tlumene zelena (kontrast k aktivnimu mračnu, nijak nesoutezi s labely).

async function loadContextIfNeeded() {
  if (ctxObj !== null) return;      // uz je — nic nedelame
  if (state.currentFileId === null) return;
  const res = await fetch(`/api/file/${state.currentFileId}/context`);
  if (!res.ok) { showErr('Context failed: ' + res.statusText); state.ctxVisible = false; return; }
  const payload = await res.json();
  if (!payload.segments || payload.segments.length === 0 && !payload.background) {
    showErr('Context: ' + (payload.reason || 'no data'));
    state.ctxVisible = false;
    return;
  }
  // mazat davne pocitani — segments budou logicky oddelene
  const { ox, oy, oz } = state.currentOrigin;
  ctxObj = new THREE.Group();
  ctxObj.visible = state.ctxVisible;

  // 1) neighbor tree segments — tlumena zelena
  const neighborColor = new THREE.Color(0x6f8457);   // olive-sage
  for (const seg of (payload.segments || [])) {
    const pos64 = new Float64Array(b64ToArrayBuffer(seg.positions_b64));
    const n = pos64.length / 3;
    const centered = new Float32Array(pos64.length);
    for (let i = 0; i < n; i++) {
      centered[3 * i]     = pos64[3 * i]     - ox;
      centered[3 * i + 1] = pos64[3 * i + 2] - oz;
      centered[3 * i + 2] = pos64[3 * i + 1] - oy;
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(centered, 3));
    const m = new THREE.PointsMaterial({
      size: 0.05, color: neighborColor, sizeAttenuation: true,
      transparent: true, opacity: 0.45, depthWrite: true,
    });
    const segPts = new THREE.Points(g, m);
    ctxObj.add(segPts);
  }

  // 2) -1 background (okoli) — seda barva (tesne pod korunou)
  if (payload.background) {
    const pos64 = new Float64Array(b64ToArrayBuffer(payload.background.positions_b64));
    const n = pos64.length / 3;
    const centered = new Float32Array(pos64.length);
    for (let i = 0; i < n; i++) {
      centered[3 * i]     = pos64[3 * i]     - ox;
      centered[3 * i + 1] = pos64[3 * i + 2] - oz;
      centered[3 * i + 2] = pos64[3 * i + 1] - oy;
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(centered, 3));
    const m = new THREE.PointsMaterial({
      size: 0.03, color: new THREE.Color(0x7a8288), sizeAttenuation: true,
      transparent: true, opacity: 0.35, depthWrite: true,
    });
    const bgPts = new THREE.Points(g, m);
    ctxObj.add(bgPts);
  }

  scene.add(ctxObj);
  console.log('[treelabeler] context: neighbors=', payload.neighbors?.length || 0,
              'bg=', payload.background?.n || 0);
}

function toggleContext() {
  state.ctxVisible = !state.ctxVisible;
  const btn = $('#btn-ctx');
  btn.classList.toggle('active', state.ctxVisible);
  if (ctxObj) ctxObj.visible = state.ctxVisible;
  if (state.ctxVisible) loadContextIfNeeded();
}

// --- color coding podle labelu ------------------------------------------
// Nehotové stromy: jedna universalni, vysoce kontrastni a neprabůdna barva
// Hotové stromy: podle tree_type/quality s rozlisitelnymi odstiny (teplá/chladná).
// Cíl: po práci znáš barvu = kategorie, aniž by to rušilo vnímání mračna.
const COLORS = {
  pending:     { label: 'pending',       rgb: new THREE.Color(0x9fb4c8) },   // chladná šedá-blue, dobře kontrastuje vs černé pozadí
  not_a_tree:  { label: 'not-a-tree',    rgb: new THREE.Color(0x7e22ce) },   // tmavě fialová — unikátní signál ne-stromu
  broadleaf: {
    'Complete':      { label: 'bl-complete',     rgb: new THREE.Color(0xffd60a) },   // světlá zlatá
    'Missing part':  { label: 'bl-missing',      rgb: new THREE.Color(0xff9f1a) },   // oranžová
    'Excessive part':{ label: 'bl-excess',       rgb: new THREE.Color(0xff5a1a) },   // tlumená oranžovo-červená
    'Multitree':     { label: 'bl-multitree',    rgb: new THREE.Color(0x7c1d02) },   // hluboká červenohnědá
  },
  coniferous: {
    'Complete':      { label: 'co-complete',     rgb: new THREE.Color(0x6ee7b7) },   // mint/zelená
    'Missing part':  { label: 'co-missing',      rgb: new THREE.Color(0x1db954) },   // výrazná zelená
    'Excessive part':{ label: 'co-excess',       rgb: new THREE.Color(0x007a3d) },   // tmavá green
    'Multitree':     { label: 'co-multitree',    rgb: new THREE.Color(0x002b16) },   // velmi tmavá green/černá
  },
};

function colorForLabels(treeType, quality) {
  if (!treeType) return COLORS.pending;
  if (treeType === 'Not a tree') return COLORS.not_a_tree;
  const sub = treeType === 'Broadleaf' ? COLORS.broadleaf
             : treeType === 'Coniferous' ? COLORS.coniferous
             : null;
  if (sub && sub[quality]) return sub[quality];
  return COLORS.pending;
}

// --- UI rendering ------------------------------------------------------
function renderCategories() {
  const gLabel = (gid) => (state.groups.find((g) => g.id === gid)?.label || gid);
  const buildGroup = (containerSel, groupId) => {
    const container = $(containerSel);
    container.innerHTML = '';
    const wrap = document.createElement('div');
    wrap.className = 'cat-subgroup';
    const head = document.createElement('div');
    head.className = 'cat-group-title';
    head.textContent = gLabel(groupId) + ':';
    wrap.appendChild(head);
    state.categories.filter((c) => c.group === groupId).forEach((cat) => {
      const btn = document.createElement('button');
      btn.className = 'cat-btn';
      btn.dataset.name = cat.name;
      btn.dataset.group = groupId;
      btn.title = cat.description || '';
      if (cat.shortcut) {
        const kbd = document.createElement('kbd');
        kbd.className = 'key';
        kbd.textContent = cat.shortcut.toUpperCase();
        btn.appendChild(kbd);
      }
      const label = document.createElement('span');
      label.className = 'cat-label';
      label.textContent = cat.name;
      btn.appendChild(label);
      btn.addEventListener('click', () => selectCat(groupId, cat.name));
      wrap.appendChild(btn);
    });
    container.appendChild(wrap);
  };

  buildGroup('#cat-type', 'tree_type');
  buildGroup('#cat-quality', 'quality');
}

function selectCat(group, name) {
  if (group === 'tree_type') state.selectedType = (state.selectedType === name) ? null : name;
  else state.selectedQuality = (state.selectedQuality === name) ? null : name;
  refreshCatButtons();
  // jakmile je strom „hotový“ (podle pravidel), automaticky uložit + posunout dál
  maybeAutoAdvance();
}

function maybeAutoAdvance() {
  if (state.currentFileId === null) return;
  const sel = state.selectedType;
  if (!sel) return;
  const notTree = sel === 'Not a tree';
  const isTree = sel === 'Broadleaf' || sel === 'Coniferous';
  if (notTree) {
    commitLabel();           // uložené nebo ne, pojede dál
  } else if (isTree && state.selectedQuality) {
    commitLabel();           // Broadleaf/Coniferous + quality → auto
  }
}

function refreshCatButtons() {
  document.querySelectorAll('.cat-btn').forEach((b) => {
    const g = b.dataset.group;
    const active = (g === 'tree_type' && b.dataset.name === state.selectedType) ||
                   (g === 'quality' && b.dataset.name === state.selectedQuality);
    b.classList.toggle('active', active);
  });
}

function renderFileList() {
  const wrap = $('#file-list');
  const scrollPos = wrap.scrollTop;   // zachovat pozici scrollu i u stovek souborů
  wrap.innerHTML = '';
  state.files.forEach((f) => {
    const div = document.createElement('div');
    const isNotTree = f.tree_type === 'Not a tree';
    const done = isNotTree ? !!f.tree_type : !!(f.tree_type && f.quality);
    div.className = 'file-item' + (done ? ' done' : '') +
      (f.id === state.currentFileId ? ' selected' : '');
    const tags = [];
    if (f.tree_type) tags.push(`<span class="tag tt">${f.tree_type}</span>`);
    if (f.quality) tags.push(`<span class="tag ql">${f.quality}</span>`);
    div.innerHTML = `${f.filename}${tags.length ? ' ' + tags.join(' ') : ''}`;
    div.title = f.abs_path;
    div.addEventListener('click', () => {
      selectCatForFile(f);
      loadTree(f.id);
    });
    wrap.appendChild(div);
  });
  wrap.scrollTop = scrollPos;
  // pokud je vybraný soubor mimo výhled, poscrolluj na něj
  const sel = wrap.querySelector('.file-item.selected');
  if (sel && (sel.offsetTop < wrap.scrollTop || sel.offsetTop > wrap.scrollTop + wrap.clientHeight)) {
    sel.scrollIntoView({ block: 'nearest' });
  }
}

function selectCatForFile(f) {
  state.selectedType = f.tree_type || null;
  state.selectedQuality = f.quality || null;
  refreshCatButtons();
}

function renderProgress() {
  const el = $('#progress-big');
  el.textContent = `${state.progress.labeled}/${state.progress.total}`;
  el.classList.toggle('complete', state.progress.total > 0 && state.progress.labeled === state.progress.total);
}

// --- data ---------------------------------------------------------------
async function refreshFiles() {
  const res = await fetch('/api/files');
  const data = await res.json();
  state.files = data.files;
  state.progress = data.progress;
  renderFileList();
  renderProgress();
}

async function bootstrap() {
  const res = await fetch('/api/bootstrap');
  const data = await res.json();
  state.files = data.files;
  state.categories = data.categories;
  state.groups = data.groups || [];
  state.progress = data.progress;
  $('#datadir').value = data.data_dir;

  renderCategories();
  renderFileList();
  renderProgress();

  const next = await fetch('/api/next-unlabeled').then((r) => r.json());
  if (next.file_id !== null && next.file_id !== undefined) loadTree(next.file_id);
  else if (state.files.length) loadTree(state.files[0].id);
}

async function commitLabel() {
  if (state.currentFileId === null) return;

  const notTree = state.selectedType === 'Not a tree';

  // Pravidla:
  // - nic nevybrano -> skip na dalsi strom (next button/space)
  // - Not a tree -> segmentation se nepozaduje
  // - Broadleaf/Coniferous -> povinna segmentation
  if (!notTree && state.selectedType && !state.selectedQuality) {
    showErr('Complete the SEGMENTATION category for this tree.');
    return;
  }

  if (state.selectedType || state.selectedQuality) {
    // ulozit label
    const res = await fetch('/api/label', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        file_id: state.currentFileId,
        tree_type: state.selectedType,
        quality: notTree ? null : state.selectedQuality,
      }),
    });
    if (!res.ok) { showErr('Save failed: ' + (await res.json()).detail); return; }
    const out = await res.json();
    state.progress = out.progress;
    await refreshFiles();
  }

  const currentId = state.currentFileId;
  const allFiles = state.files;
  const myIdx = allFiles.findIndex((f) => f.id === currentId);
  const labeled = await fetch('/api/files').then((r) => r.json()).then((d) => {
    state.files = d.files; state.progress = d.progress; return d.files;
  });

  // find next unlabeled, cycling from after current
  const unlabeledIds = new Set(labeled.filter((f) =>
    !(f.tree_type === 'Not a tree' ? true : (f.tree_type && f.quality))
  ).map((f) => f.id));

  let nextFile = null;
  for (let off = 1; off <= allFiles.length; off++) {
    const cand = allFiles[(myIdx + off) % allFiles.length];
    if (unlabeledIds.has(cand.id)) { nextFile = cand; break; }
  }

  state.selectedType = null;
  state.selectedQuality = null;
  refreshCatButtons();
  renderFileList();
  renderProgress();

  if (nextFile !== null) {
    loadTree(nextFile.id);
  } else {
    showErr('✔ All done — every tree has both categories.');
  }
}

async function skipToNextUnlabeled() {
  // bez ulaceni — jako Space / Next button: posun na dalsi nehotový
  if (state.currentFileId === null) return;
  const currentId = state.currentFileId;
  const allFiles = state.files;

  const labeledData = await fetch('/api/files').then((r) => r.json());
  const unlabeledIds = new Set(labeledData.files.filter((f) =>
    !(f.tree_type === 'Not a tree' ? true : (f.tree_type && f.quality))
  ).map((f) => f.id));

  const myIdx = allFiles.findIndex((f) => f.id === currentId);
  let nextFile = null;
  for (let off = 1; off <= allFiles.length; off++) {
    const cand = allFiles[(myIdx + off) % allFiles.length];
    if (unlabeledIds.has(cand.id)) { nextFile = cand; break; }
  }
  if (!nextFile) { showErr('✔ All done — every tree has both categories.'); return; }

  state.selectedType = null;
  state.selectedQuality = null;
  refreshCatButtons();
  loadTree(nextFile.id);
}

// --- events -------------------------------------------------------------
document.addEventListener('keydown', (e) => {
  const tag = document.activeElement?.tagName || '';
  if (tag === 'INPUT' || tag === 'TEXTAREA') return;

  // Space = preskit/posuni na dalsi strom; ulozeni probiha automaticky pri vyberu kategorii
  if (e.code === 'Space') { e.preventDefault(); skipToNextUnlabeled(); return; }

  // C = show/hide okolni body (context)
  if (e.key.toLowerCase() === 'c') { toggleContext(); return; }

  // pismenkove zkratky z konfigurace (Q/W/E species, A/S/D/F segmentation)
  const key = e.key.toLowerCase();
  const cat = state.categories.find((c) => (c.shortcut || '').toLowerCase() === key);
  if (cat) selectCat(cat.group, cat.name);
});

$('#btn-ctx').addEventListener('click', toggleContext);

$('#btn-next').addEventListener('click', async () => {
  const next = await fetch('/api/next-unlabeled').then((r) => r.json());
  if (next.file_id !== null && next.file_id !== undefined) loadTree(next.file_id);
  else showErr('✔ All labeled.');
});

$('#btn-export').addEventListener('click', () => { window.location = '/api/export.csv'; });

$('#btn-load-dir').addEventListener('click', async () => {
  const dir = $('#datadir').value.trim();
  if (!dir) { showErr('Enter a data folder path.'); return; }
  const res = await fetch('/api/set-datadir', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ data_dir: dir }),
  });
  if (!res.ok) {
    const msg = (await res.json()).detail || res.statusText;
    showErr('Cannot load folder: ' + msg);
    return;
  }
  state.selectedType = null;
  state.selectedQuality = null;
  state.ctxVisible = false;
  $('#btn-ctx').classList.remove('active');
  if (ctxObj) { scene.remove(ctxObj); ctxObj.geometry.dispose(); ctxObj.material.dispose(); ctxObj = null; }
  await bootstrap();
});

initViewer();
bootstrap();
