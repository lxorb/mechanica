import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {RoomEnvironment} from 'three/addons/environments/RoomEnvironment.js';
import {disposeYZF} from './yzf-model.js';
import {spreadSourceMeshes} from './source-parts.js';

export function createAssemblyScene(host, model, callbacks = {}) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color('#101519');
  const sceneScale = Math.max(1, model.size.length() / 2.8);
  scene.fog = new THREE.Fog('#101519', 9 * sceneScale, 26 * sceneScale);
  const renderer = new THREE.WebGLRenderer({antialias: true, powerPreference: 'high-performance'});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.15;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  host.appendChild(renderer.domElement);
  const camera = new THREE.PerspectiveCamera(34, 1, 0.02, 80);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.07;
  controls.minDistance = 0.15;
  controls.maxDistance = 40;
  controls.maxPolarAngle = Math.PI * 0.96;
  controls.autoRotateSpeed = 0.55;
  scene.add(model.root);
  const generator = new THREE.PMREMGenerator(renderer);
  const room = new RoomEnvironment();
  const environment = generator.fromScene(room, 0.04);
  scene.environment = environment.texture;
  scene.environmentIntensity = 0.85;
  room.dispose();
  generator.dispose();
  scene.add(new THREE.HemisphereLight('#c5d9f3', '#303733', 1.4));
  function light(position, color, intensity) {
    const item = new THREE.DirectionalLight(color, intensity);
    item.position.set(...position);
    scene.add(item);
    return item;
  }
  const key = light([2, 5, 4], '#e8eeff', 3.3);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  Object.assign(key.shadow.camera, {left: -4, right: 4, top: 4, bottom: -4, near: 0.1, far: 15});
  key.shadow.normalBias = 0.012;
  key.shadow.bias = -0.0001;
  light([-3, 3, -3], '#87a8ff', 3.5);
  light([-2, 2, 4], '#c9f4df', 1.6);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(400, 400), new THREE.MeshStandardMaterial({color: '#101719', roughness: 1, metalness: 0, envMapIntensity: 0.12}));
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = -0.012;
  floor.receiveShadow = true;
  scene.add(floor);
  const grid = new THREE.Mesh(new THREE.PlaneGeometry(16, 16), new THREE.ShaderMaterial({
    transparent: true, depthWrite: false,
    uniforms: {color: {value: new THREE.Color('#738b89')}},
    vertexShader: 'varying vec2 vUv;void main(){vUv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',
    fragmentShader: 'varying vec2 vUv;uniform vec3 color;void main(){vec2 p=(vUv-.5)*64.;vec2 q=abs(fract(p-.5)-.5)/fwidth(p);float line=1.-min(min(q.x,q.y),1.);float fade=1.-smoothstep(.03,.4,length(vUv-.5));gl_FragColor=vec4(color,line*fade*.16);}',
  }));
  grid.rotation.x = -Math.PI / 2;
  grid.position.y = -0.009;
  scene.add(grid);
  const xray = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, side: THREE.DoubleSide, blending: THREE.AdditiveBlending,
    uniforms: {time: {value: 0}, color: {value: new THREE.Color('#75c4bc')}},
    vertexShader: 'varying vec3 vN;varying vec3 vV;varying vec3 vW;void main(){vec4 p=modelViewMatrix*vec4(position,1.);vN=normalize(normalMatrix*normal);vV=normalize(-p.xyz);vW=(modelMatrix*vec4(position,1.)).xyz;gl_Position=projectionMatrix*p;}',
    fragmentShader: 'uniform float time;uniform vec3 color;varying vec3 vN;varying vec3 vV;varying vec3 vW;void main(){float rim=pow(1.-abs(dot(normalize(vN),normalize(vV))),2.6);float scan=exp(-pow((vW.y-mod(time*.23,2.4))*19.,2.));gl_FragColor=vec4(color*(.5+rim+scan*.4),.024+rim*.19+scan*.045);}',
  });
  const wire = new THREE.MeshBasicMaterial({color: '#8dd4c0', wireframe: true, transparent: true, opacity: 0.27});
  const selectedWire = new THREE.MeshBasicMaterial({color: '#e1fff1', wireframe: true});
  const highlights = new Map();
  model.materials.forEach(material => {
    const highlight = material.clone();
    highlight.emissive?.set('#44a87f');
    highlight.emissiveIntensity = 0.25;
    highlights.set(material, highlight);
  });
  let selected = null, selectedMesh = null, detailSpacing = 0, currentDetailSpacing = 0, meshIsolated = false;
  let mode = 'studio', spacing = 0, currentSpacing = 0, isolated = false;
  let hidden = new Set(), preview = null, tween = null, disposed = false, frame = 0;
  let last = performance.now();
  const directions = {
    hero: new THREE.Vector3(1.5, 0.85, 2.8),
    side: new THREE.Vector3(0, 0.035, 1),
    front: new THREE.Vector3(1, 0.04, 0),
    rear: new THREE.Vector3(-1, 0.06, 0),
    top: new THREE.Vector3(0.001, 1, 0),
  };
  function report() {
    callbacks.onState?.({selected, selectedMesh, detailSpacing, meshIsolated, isolated, hidden: [...hidden], playing: !!preview, spacing});
  }
  function updateMaterials() {
    model.meshes.forEach(mesh => {
      const active = selectedMesh ? selectedMesh === mesh.userData.meshId : selected === mesh.userData.partId;
      const original = mesh.userData.originalMaterial;
      mesh.material = mode === 'wireframe' ? (active ? selectedWire : wire) :
        mode === 'xray' && !active ? xray : active ? (Array.isArray(original) ? original.map(m => highlights.get(m)) : highlights.get(original)) : original;
    });
  }
  function updateVisibility() {
    model.groups.forEach(part => { part.node.visible = !hidden.has(part.id) && (!isolated || part.id === selected); });
    model.meshes.forEach(mesh => { mesh.visible = !meshIsolated || mesh.userData.meshId === selectedMesh; });
  }
  function boundsFor(id) {
    model.root.updateMatrixWorld(true);
    if (id && selectedMesh) { const mesh = model.meshes.find(m => m.userData.meshId === selectedMesh); if (mesh) return new THREE.Box3().setFromObject(mesh); }
    if (id && model.groups.has(id)) return new THREE.Box3().setFromObject(model.groups.get(id).node);
    const box = new THREE.Box3();
    model.groups.forEach(part => { if (part.node.visible) box.union(new THREE.Box3().setFromObject(part.node)); });
    return box.isEmpty() ? new THREE.Box3().setFromObject(model.root) : box;
  }
  function fit(direction, id, instant = false, extra = 1, box = boundsFor(id)) {
    const center = box.getCenter(new THREE.Vector3());
    const radius = Math.max(0.12, box.getSize(new THREE.Vector3()).length() * 0.5);
    const v = THREE.MathUtils.degToRad(camera.fov / 2);
    const h = Math.atan(Math.tan(v) * camera.aspect);
    const distance = radius / Math.sin(Math.min(v, h)) * (id ? 1.15 : 1.13) * extra;
    if (!id) center.y += box.getSize(new THREE.Vector3()).y * 0.10;
    const position = direction.clone().normalize().multiplyScalar(distance).add(center);
    if (instant) { camera.position.copy(position); controls.target.copy(center); controls.update(); }
    else tween = {start: performance.now(), from: camera.position.clone(), to: position, targetFrom: controls.target.clone(), targetTo: center};
  }
  function fitSpread(includePreview = false, direction = camera.position.clone().sub(controls.target)) {
    const box = new THREE.Box3();
    model.groups.forEach(part => {
      if (!part.node.visible) return;
      const placed = new THREE.Box3();
      part.meshes.forEach(mesh => {
        if (!mesh.visible) return;
        const offset = part.explode.clone().multiplyScalar(spacing);
        if (part.id === selected) offset.addScaledVector(mesh.userData.detailOffset, detailSpacing);
        placed.union(mesh.geometry.boundingBox.clone().translate(offset));
      });
      box.union(placed);
      if (includePreview && part.id === selected) box.union(placed.clone().translate(part.previewOffset));
    });
    if (!box.isEmpty()) fit(direction, null, false, 1, box);
  }
  function select(id, focus = false) {
    if (id != null && !model.groups.has(id)) return false;
    preview = null;
    if (selected !== id) { detailSpacing = currentDetailSpacing = 0; model.groups.forEach(p => spreadSourceMeshes(p, 0)); }
    selectedMesh = null; meshIsolated = false;
    selected = id;
    if (id) hidden.delete(id); else isolated = false;
    updateVisibility(); updateMaterials(); report();
    if (id && focus) fit(camera.position.clone().sub(controls.target), id);
    return true;
  }
  function selectMesh(id, focus = false) {
    const mesh = model.meshes.find(m => m.userData.meshId === id);
    if (!mesh) return false;
    if (selected !== mesh.userData.partId) select(mesh.userData.partId);
    preview = null; selectedMesh = id; hidden.delete(selected);
    updateVisibility(); updateMaterials(); report();
    if (focus) fit(camera.position.clone().sub(controls.target), selected);
    return true;
  }
  const ray = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  let down = null;
  const onDown = event => { tween = null; down = event.button === 0 ? {x: event.clientX, y: event.clientY, id: event.pointerId} : null; };
  const onUp = event => {
    const start = down; down = null;
    if (!start || start.id !== event.pointerId || Math.hypot(event.clientX - start.x, event.clientY - start.y) > 5) return;
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.set((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1);
    ray.setFromCamera(pointer, camera);
    const visibleMeshes = model.meshes.filter(mesh => mesh.parent.visible && mesh.visible);
    const hit = ray.intersectObjects(visibleMeshes, false)[0];
    if (hit && detailSpacing > 0) selectMesh(hit.object.userData.meshId);
    else select(hit?.object.userData.partId || null);
  };
  const onDoubleClick = () => { if (selected) fit(camera.position.clone().sub(controls.target), selected); };
  renderer.domElement.addEventListener('pointerdown', onDown);
  renderer.domElement.addEventListener('pointerup', onUp);
  renderer.domElement.addEventListener('dblclick', onDoubleClick);
  let previousWidth = 0;
  const resize = () => {
    if (!host.clientWidth || !host.clientHeight) return;
    camera.aspect = host.clientWidth / host.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(host.clientWidth, host.clientHeight);
    if (previousWidth && previousWidth !== host.clientWidth) fitSpread();
    previousWidth = host.clientWidth;
  };
  const observer = new ResizeObserver(resize); observer.observe(host); resize();
  fit(directions.hero, null, true);
  function tick(now) {
    if (disposed) return;
    frame = requestAnimationFrame(tick);
    const dt = Math.min((now - last) / 1000, 0.05); last = now;
    xray.uniforms.time.value = now / 1000;
    currentSpacing = THREE.MathUtils.damp(currentSpacing, spacing, 6, dt);
    currentDetailSpacing = THREE.MathUtils.damp(currentDetailSpacing, detailSpacing, 6, dt);
    let previewAmount = 0;
    if (preview) {
      const t = Math.min((now - preview.start) / 5500, 1);
      previewAmount = Math.sin(Math.PI * t) ** 2;
      if (t === 1) { preview = null; report(); }
    }
    model.groups.forEach(part => {
      part.node.position.copy(part.explode).multiplyScalar(currentSpacing);
      spreadSourceMeshes(part, part.id === selected ? currentDetailSpacing : 0);
      if (preview && part.id === selected) {
        if (selectedMesh) { const mesh = part.meshes.find(m => m.userData.meshId === selectedMesh); mesh?.position.addScaledVector(mesh.userData.detailOffset, previewAmount); }
        else part.node.position.addScaledVector(part.previewOffset, previewAmount);
      }
    });
    if (tween) {
      const t = Math.min(1, (now - tween.start) / 750), eased = t * t * (3 - 2 * t);
      camera.position.lerpVectors(tween.from, tween.to, eased);
      controls.target.lerpVectors(tween.targetFrom, tween.targetTo, eased);
      if (t === 1) tween = null;
    }
    controls.update(); renderer.render(scene, camera);
  }
  frame = requestAnimationFrame(tick);
  report();
  return {
    select, selectMesh,
    setDetailSpacing(value) {
      if (!selected || !Number.isFinite(value)) return;
      detailSpacing = THREE.MathUtils.clamp(value, 0, 1); preview = null;
      fitSpread(); report();
    },
    isolateMesh() { if (!selectedMesh) return; meshIsolated = !meshIsolated; updateVisibility(); report(); if (meshIsolated) fit(camera.position.clone().sub(controls.target), selected); else fitSpread(); },
    view(name) { if (directions[name]) fitSpread(false, directions[name]); },
    focus() { if (selected) fit(camera.position.clone().sub(controls.target), selected); },
    setMode(value) { if (!['studio', 'xray', 'wireframe'].includes(value)) return; mode = value; updateMaterials(); },
    setOrbit(value) { controls.autoRotate = !!value; },
    setSpacing(value) { if (!Number.isFinite(value)) return; spacing = THREE.MathUtils.clamp(value, 0, 1); preview = null; fitSpread(); report(); },
    isolate() { if (!selected) return; isolated = !isolated; updateVisibility(); fitSpread(); report(); },
    hideSelected() { if (!selected) return; hidden.add(selected); selected = selectedMesh = null; meshIsolated = false; isolated = false; preview = null; updateVisibility(); updateMaterials(); report(); },
    showAll() { hidden.clear(); isolated = false; meshIsolated = false; updateVisibility(); fitSpread(); report(); },
    hideBodywork() { model.groups.forEach(p => {if (p.category === 'Body') hidden.add(p.id);}); isolated = false; if (hidden.has(selected)) {selected = selectedMesh = null; meshIsolated = false;} preview = null; updateVisibility(); updateMaterials(); report(); },
    preview() { if (!selected) return; preview = preview ? null : {start: performance.now()}; if (preview) fitSpread(true); report(); },
    reset() {
      spacing = currentSpacing = detailSpacing = currentDetailSpacing = 0; preview = null; isolated = meshIsolated = false; hidden.clear(); selected = selectedMesh = null;
      controls.autoRotate = false;
      model.groups.forEach(part => { part.node.position.set(0, 0, 0); spreadSourceMeshes(part, 0); });
      updateVisibility(); updateMaterials(); fit(directions.hero); report();
    },
    capture() { renderer.render(scene, camera); return renderer.domElement.toDataURL('image/png'); },
    getState() { return {selected, selectedMesh, detailSpacing, meshIsolated, mode, spacing, isolated, hidden: [...hidden], playing: !!preview, camera: camera.position.toArray(), groups: [...model.groups.values()].map(p => ({id: p.id, visible: p.node.visible, position: p.node.position.toArray()}))}; },
    dispose() {
      disposed = true; cancelAnimationFrame(frame); observer.disconnect(); controls.dispose();
      renderer.domElement.removeEventListener('pointerdown', onDown);
      renderer.domElement.removeEventListener('pointerup', onUp);
      renderer.domElement.removeEventListener('dblclick', onDoubleClick);
      disposeYZF(model); highlights.forEach(m => m.dispose());
      [xray, wire, selectedWire, floor.material, grid.material].forEach(m => m.dispose());
      floor.geometry.dispose(); grid.geometry.dispose(); environment.dispose(); key.shadow.map?.dispose();
      renderer.dispose(); renderer.domElement.remove();
    },
  };
}
