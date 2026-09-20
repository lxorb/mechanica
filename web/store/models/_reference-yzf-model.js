import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {MeshoptDecoder} from 'three/addons/libs/meshopt_decoder.module.js';
import {prepareSourceMeshes} from './source-parts.js';
import {VEHICLES} from '../../../shared/vehicles.js';

export const YZF_SOURCE = {
  title: 'Yamaha YZF 2021',
  author: 'VTX',
  url: 'https://sketchfab.com/3d-models/yamaha-yzf-2021-0af46985abc54219be3aaf0991f5a3de',
  license: 'CC BY-NC-SA 4.0',
  licenseUrl: 'https://creativecommons.org/licenses/by-nc-sa/4.0/',
};

// Labels describe source groups, not a manufacturer parts catalogue.
const labels = {
  bikedisc_f: ['front-brakes', 'Front brake discs', 'Running gear'],
  bikedisc_r: ['rear-brake', 'Rear brake disc', 'Running gear'],
  wheel_lf: ['front-wheel', 'Front wheel', 'Running gear'],
  wheel_lr: ['rear-wheel', 'Rear wheel', 'Running gear'],
  bodyshell: ['bodywork', 'Bodywork', 'Body'],
  'bodyshell.001': ['bodywork-2', 'Secondary bodywork', 'Body'],
  chassis: ['chassis', 'Chassis', 'Structure'],
  swingarm: ['swingarm', 'Swingarm', 'Running gear'],
  forks_l: ['lower-forks', 'Lower fork assembly', 'Running gear'],
  forks_u: ['upper-forks', 'Upper fork assembly', 'Running gear'],
  handlebars: ['handlebars', 'Handlebars & controls', 'Structure'],
  headlight_l: ['headlight', 'Headlight', 'Lighting'],
  taillight_l: ['taillight', 'Tail light', 'Lighting'],
  windscreen: ['windscreen', 'Windscreen', 'Body'],
  misc_a: ['engine-exterior', 'Engine exterior', 'Powertrain'],
  misc_b: ['radiator-group', 'Radiator & source group B', 'Powertrain'],
  misc_c: ['exhaust', 'Exhaust', 'Powertrain'],
};

const hondaLabels = {
  enginecbr: ['engine-exterior', 'Engine assembly', 'Powertrain'],
  dials: ['instruments', 'Instrument display', 'Controls'],
  headlight_r: ['headlight-right', 'Right headlight', 'Lighting'],
  taillight_r: ['taillight-right', 'Right tail light', 'Lighting'],
  indicator_lr: ['indicator-left', 'Left rear indicator', 'Lighting'],
  indicator_rr: ['indicator-right', 'Right rear indicator', 'Lighting'],
};
const corvetteLabels = {
  'Main Chassis': ['bodywork', 'Main chassis & body', 'Body'],
  '6.2L LT2 V8 Engine and Engine Bay': ['engine-bay', 'LT2 V8 engine & bay', 'Powertrain'],
  'Engine Bay Bolts': ['engine-bay-bolts', 'Engine bay bolts', 'Powertrain'],
  'Trunk [or Hood]': ['rear-cover', 'Rear engine cover / trunk', 'Body'],
  'SUSpension': ['suspension', 'Suspension', 'Running gear'],
};
const slug = value => value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

export function describeGroup(sourceName, vehicleId = 'yzf-2021') {
  if (vehicleId === 'corvette-c8') {
    const category = /lights|indicator/i.test(sourceName) ? 'Lighting' : /interior|steering|speedo/i.test(sourceName) ? 'Cabin' : /wheel|caliper|suspension/i.test(sourceName) ? 'Running gear' : /door|roof|frunk|glass|grille|carbon|wiper/i.test(sourceName) ? 'Body' : 'Other';
    const [id, name, groupCategory] = corvetteLabels[sourceName] || [slug(sourceName), sourceName, category];
    return {id, name, category: groupCategory, sourceName, verified: false};
  }
  const key = sourceName.replace(/_\d+$/, '').replace(/\.child(?:\.\d+)?$/, '');
  const table = vehicleId === 'honda-cbr650r' ? {...labels, ...hondaLabels, misc_a: null, misc_b: null, misc_c: null} : labels;
  const [id, name, category] = table[key] || [key.replaceAll('_', '-').replaceAll('.', '-'), `Source group ${key.replace('misc_', '').toUpperCase()}`, 'Other'];
  return {id, name, category, sourceName, verified: false};
}

/** Freeze a rigid skin at its imported pose without changing its surface. */
export function bakeRigidGeometry(mesh) {
  const geometry = mesh.geometry.clone();
  const transform = mesh.matrixWorld.clone();
  if (mesh.isSkinnedMesh) {
    const indices = geometry.getAttribute('skinIndex');
    const weights = geometry.getAttribute('skinWeight');
    let joint = null;
    for (let i = 0; i < weights.count; i++) {
      let vertexJoint = null;
      for (let k = 0; k < 4; k++) {
        const weight = weights.getComponent(i, k);
        if (weight < 0.00001) continue;
        if (Math.abs(weight - 1) > 0.00001 || vertexJoint !== null) {
          geometry.dispose();
          throw new Error('This model contains a deforming skin; its geometry needs a different importer.');
        }
        vertexJoint = indices.getComponent(i, k);
      }
      if (vertexJoint === null || (joint !== null && joint !== vertexJoint)) {
        geometry.dispose();
        throw new Error('A source mesh spans multiple joints; import stopped to preserve its geometry.');
      }
      joint = vertexJoint;
    }
    const skin = new THREE.Matrix4()
      .multiplyMatrices(mesh.skeleton.bones[joint].matrixWorld, mesh.skeleton.boneInverses[joint]);
    transform.multiply(mesh.bindMatrixInverse).multiply(skin).multiply(mesh.bindMatrix);
    const bone = mesh.skeleton.bones[joint];
    geometry.userData.sourceJoint = bone.userData.name || bone.name;
    geometry.deleteAttribute('skinIndex');
    geometry.deleteAttribute('skinWeight');
  }
  geometry.applyMatrix4(transform);
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
  return geometry;
}

export const loadYZF = onProgress => loadVehicle('yzf-2021', onProgress);
export async function loadVehicle(vehicleId, onProgress) {
  if (!VEHICLES[vehicleId]) throw new Error('Unknown vehicle');
  const gltf = await new GLTFLoader().setMeshoptDecoder(MeshoptDecoder).loadAsync(`/models/${vehicleId}/model.glb`, onProgress);
  const root = new THREE.Group();
  const groups = new Map();
  const meshes = [];
  const materials = new Set();
  const originalGeometries = new Set();
  gltf.scene.updateMatrixWorld(true);
  gltf.scene.traverse(object => {
    if (!object.isMesh) return;
    originalGeometries.add(object.geometry);
    const geometry = bakeRigidGeometry(object);
    const sourceName = geometry.userData.sourceJoint || object.parent.userData.name || object.parent.name;
    const descriptor = describeGroup(sourceName, vehicleId);
    if (!groups.has(descriptor.id)) {
      const node = new THREE.Group();
      node.name = descriptor.name;
      root.add(node);
      groups.set(descriptor.id, {...descriptor, node, meshes: [], triangles: 0});
    }
    const part = groups.get(descriptor.id);
    const mesh = new THREE.Mesh(geometry, object.material);
    mesh.name = object.name;
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.userData = {partId: part.id, originalMaterial: object.material, sourceNode: object.userData.name || object.name, sourceGroup: sourceName};
    part.node.add(mesh);
    part.meshes.push(mesh);
    part.triangles += (geometry.index?.count || geometry.attributes.position.count) / 3;
    meshes.push(mesh);
    for (const material of [].concat(object.material)) materials.add(material);
  });
  // Geometry stays intact; only a shared display orientation and translation change.
  const orient = new THREE.Matrix4().makeRotationY(-Math.PI / 2);
  meshes.forEach(mesh => mesh.geometry.applyMatrix4(orient));
  const bounds = new THREE.Box3().setFromObject(root);
  const center = bounds.getCenter(new THREE.Vector3());
  const offset = new THREE.Matrix4().makeTranslation(-center.x, -bounds.min.y, -center.z);
  meshes.forEach(mesh => mesh.geometry.applyMatrix4(offset));
  root.updateMatrixWorld(true);
  const size = new THREE.Box3().setFromObject(root).getSize(new THREE.Vector3());
  for (const part of groups.values()) {
    part.bounds = new THREE.Box3().setFromObject(part.node);
    part.center = part.bounds.getCenter(new THREE.Vector3());
    const c = part.center;
    part.explode = new THREE.Vector3(c.x * 0.6, Math.max(0.12, c.y * 0.65), c.z * 1.8);
    if (part.id === 'bodywork') part.explode.set(0, size.y * 0.65, -size.z * 0.65);
    if (part.id === 'bodywork-2') part.explode.set(-0.15, size.y * 0.9, size.z * 0.7);
    if (part.id === 'engine-exterior') part.explode.set(0, 0.1, size.z * 0.95);
    if (part.id === 'chassis') part.explode.set(0, 0, 0);
    part.previewOffset = part.explode.clone();
    if (part.previewOffset.length() < 0.25) part.previewOffset.set(0, 0.6, 0.5);
    prepareSourceMeshes(part);
    part.materialNames = [...new Set(part.meshes.flatMap(m => [].concat(m.material).map(mat => mat.name)))];
  }
  originalGeometries.forEach(g => g.dispose());
  const skeletons = new Set();
  gltf.scene.traverse(o => { if (o.skeleton) skeletons.add(o.skeleton); });
  skeletons.forEach(s => s.dispose());
  return {root, groups, meshes, materials, size, vehicleId, triangles: [...groups.values()].reduce((n, p) => n + p.triangles, 0)};
}

export function disposeYZF(model) {
  const textures = new Set();
  model.meshes.forEach(mesh => mesh.geometry.dispose());
  model.materials.forEach(material => {
    Object.values(material).forEach(value => { if (value?.isTexture) textures.add(value); });
    material.dispose();
  });
  textures.forEach(texture => texture.dispose());
}
