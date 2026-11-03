"""Batch compatible opaque leaf meshes in initial drafts only.

Uses indexed concatenation with vertex offsets. Does not merge transparent,
instanced, skinned, mirrored, hidden, ordered, or morph-target meshes.
The returned object is still rendered/validated by the ordinary witness path.
"""
from __future__ import annotations
import re

EXPORT = re.compile(r"export\s+default\s+function\s*([A-Za-z_$][\w$]*)?\s*\(\s*THREE\s*\)")
MARKER = "function __draft_batch_v1(THREE, original)"
BATCH_FUNCTION = re.compile(r"\bfunction\s+__draft_batch_v1\s*\(")

BATCH = r'''
function __draft_batch_v1(THREE, original) {
  const root = new THREE.Group();
  root.add(original);
  root.updateMatrixWorld(true);
  const buckets = new Map();
  original.traverse((mesh) => {
    if (!mesh.isMesh || mesh.isInstancedMesh || mesh.isSkinnedMesh || mesh.children.length) return;
    if (!mesh.visible || mesh.renderOrder !== 0 || mesh.layers.mask !== 1 || mesh.matrixWorld.determinant() <= 0) return;
    if (['onBeforeRender','onAfterRender','onBeforeShadow','onAfterShadow'].some((key) => Object.hasOwn(mesh, key))) return;
    for (let p = mesh.parent; p; p = p.parent) {
      if (!p.visible || p.renderOrder !== 0) return;
    }
    const mat = mesh.material;
    if (!mat || Array.isArray(mat) || mat.transparent || mat.opacity < 1 || mat.transmission > 0 || mat.depthWrite === false) return;
    const geo = mesh.geometry;
    if (!geo || !geo.attributes.position) return;
    if (Object.values(geo.morphAttributes).some((a) => a.length)) return;
    if (geo.drawRange.start !== 0 || geo.drawRange.count !== Infinity) return;
    const names = Object.keys(geo.attributes).sort();
    if (names.some((name) => {
      const a = geo.attributes[name];
      return a.isInterleavedBufferAttribute || a.itemSize < 1 || a.itemSize > 4 ||
        a.count !== geo.attributes.position.count ||
        !['position','normal','uv','uv1','uv2','uv3','color','tangent'].includes(name);
    })) return;
    const layout = names.map((n) => n + ':' + geo.attributes[n].itemSize).join('|') +
      ':' + mesh.castShadow + ':' + mesh.receiveShadow + ':' + mesh.frustumCulled;
    let byLayout = buckets.get(mat);
    if (!byLayout) { byLayout = new Map(); buckets.set(mat, byLayout); }
    let group = byLayout.get(layout);
    if (!group) { group = {names, meshes: [], mat}; byLayout.set(layout, group); }
    group.meshes.push(mesh);
  });
  for (const byLayout of buckets.values()) for (const group of byLayout.values()) {
    if (group.meshes.length < 2) continue;
    const geometries = group.meshes.map((m) => m.geometry.clone().applyMatrix4(m.matrixWorld));
    let vertexCount = 0, indexCount = 0;
    for (const geo of geometries) {
      vertexCount += geo.attributes.position.count;
      indexCount += geo.index ? geo.index.count : geo.attributes.position.count;
    }
    const joined = new THREE.BufferGeometry();
    for (const name of group.names) {
      const itemSize = geometries[0].attributes[name].itemSize;
      const values = new Float32Array(vertexCount * itemSize);
      let offset = 0;
      for (const geo of geometries) {
        const a = geo.attributes[name];
        for (let i = 0; i < a.count; i++) {
          values[offset++] = a.getX(i);
          if (itemSize > 1) values[offset++] = a.getY(i);
          if (itemSize > 2) values[offset++] = a.getZ(i);
          if (itemSize > 3) values[offset++] = a.getW(i);
        }
      }
      joined.setAttribute(name, new THREE.Float32BufferAttribute(values, itemSize));
    }
    const indices = new Uint32Array(indexCount);
    let indexOffset = 0, vertexOffset = 0;
    for (const geo of geometries) {
      const count = geo.index ? geo.index.count : geo.attributes.position.count;
      for (let i = 0; i < count; i++) indices[indexOffset++] = vertexOffset + (geo.index ? geo.index.getX(i) : i);
      vertexOffset += geo.attributes.position.count;
    }
    joined.setIndex(new THREE.BufferAttribute(indices, 1));
    joined.computeBoundingBox();
    joined.computeBoundingSphere();
    const merged = new THREE.Mesh(joined, group.mat);
    merged.castShadow = group.meshes[0].castShadow;
    merged.receiveShadow = group.meshes[0].receiveShadow;
    merged.frustumCulled = group.meshes[0].frustumCulled;
    for (const mesh of group.meshes) mesh.removeFromParent();
    root.add(merged);
    for (const geo of geometries) geo.dispose();
  }
  return root;
}

export default function generate(THREE) {
  return __draft_batch_v1(THREE, __draft_base_v1(THREE));
}
'''


def apply(module: str) -> str:
    if BATCH_FUNCTION.search(module):
        return module
    match = EXPORT.search(module)
    if match is None:
        return module
    renamed = module[:match.start()] + 'function __draft_base_v1(THREE)' + module[match.end():]
    return renamed.rstrip() + '\n' + BATCH
