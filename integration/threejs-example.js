// Example only: adapt to your existing Three.js scene, objects and editors.
// Three.js is not bundled in this repository.
import { joinStudent, ClassroomSyncClient } from './classroom-sync-client.js';

export async function connectExistingThreeScene({
  cloudBaseUrl, // e.g. 'https://YOUR-REAL-CLOUDBASE-DOMAIN'
  inviteCode,
  nickname,
  scene,
  THREE,
  onStatus
}) {
  const joinResult = await joinStudent(cloudBaseUrl, { inviteCode, displayName: nickname });
  const meshes = new Map();

  function addObject(object) {
    if (meshes.has(object.id)) return;
    const geometry = new THREE.BoxGeometry(1, 1, 1); // replace with your paper-box geometry
    const material = new THREE.MeshStandardMaterial({ color: object.color });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.name = object.id;
    mesh.position.set(...object.position);
    mesh.rotation.set(...object.rotation);
    mesh.scale.set(...object.scale);
    scene.add(mesh);
    meshes.set(object.id, mesh);
  }
  function removeObject(id) {
    const mesh = meshes.get(id);
    if (!mesh) return;
    scene.remove(mesh);
    mesh.geometry.dispose();
    mesh.material.dispose();
    meshes.delete(id);
  }
  function apply(msg) {
    const d = msg.data;
    if (msg.action === 'object.add') addObject(d.object);
    if (msg.action === 'object.remove') removeObject(d.id);
    const mesh = meshes.get(d.id);
    if (mesh && msg.action === 'object.transform') {
      if (d.position) mesh.position.set(...d.position);
      if (d.rotation) mesh.rotation.set(...d.rotation);
      if (d.scale) mesh.scale.set(...d.scale);
    }
    if (mesh && msg.action === 'object.color') mesh.material.color.set(d.color);
  }

  const client = new ClassroomSyncClient({
    baseUrl: cloudBaseUrl,
    sessionToken: joinResult.sessionToken,
    onStatus,
    onSnapshot: snapshot => {
      // IMPORTANT: rebuild entire group scene from latest authoritative snapshot
      for (const id of Array.from(meshes.keys())) removeObject(id);
      for (const object of snapshot.objects) addObject(object);
    },
    onOperation: apply,
    onError: error => console.warn('[ClassroomSync]', error)
  });
  client.connect();
  // Your UI should use client.sendOp(...) on meaningful edits, not every animation frame.
  return client;
}
