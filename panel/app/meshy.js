import * as THREE from 'three';
import {GLTFLoader} from './vendor/loaders/GLTFLoader.js';
export const REQUIRED=['FlyRoot','HeadPivot','AbdomenPivot','LeftWingPivot','RightWingPivot',
 'L1','L2','L3','R1','R2','R3','L1_Knee','L2_Knee','L3_Knee','R1_Knee','R2_Knee','R3_Knee'];
export async function loadMeshy(url='/models/FLY01_ROBOT_MESHY_RUNTIME_v1_1A_WINGFIX.glb'){
 const gltf=await new GLTFLoader().loadAsync(url),asset=gltf.scene.getObjectByName('FlyRoot');
 if(!asset||REQUIRED.some(n=>!asset.getObjectByName(n)))throw Error('Meshy required joint missing');
 const root=new THREE.Group(),fit=new THREE.Group();root.name='DisplayRoot';root.add(fit);fit.add(asset);
 asset.rotation.y=-Math.PI/2;asset.scale.set(1,1,-1);root.updateMatrixWorld(true);
 const head=asset.getObjectByName('HeadPivot').getWorldPosition(new THREE.Vector3());
 const abdomen=asset.getObjectByName('AbdomenPivot').getWorldPosition(new THREE.Vector3());
 const front=head.sub(abdomen);if(Math.hypot(front.x,front.z)<1e-6)throw Error('Model forward axis undefined');
 // The Motion/vision convention is forward -Z. Correct asset basis only once.
 asset.rotation.y+=Math.atan2(front.x,-front.z);root.updateMatrixWorld(true);
 const box=new THREE.Box3().setFromObject(asset),size=box.getSize(new THREE.Vector3());
 const scale=3.2/Math.max(size.x,size.z);fit.scale.setScalar(scale);
 fit.position.set(-(box.min.x+box.max.x)*scale/2,-.88-box.min.y*scale,-(box.min.z+box.max.z)*scale/2);
 let meshes=0,textured=0;
 asset.traverse(o=>{if(!o.isMesh)return;meshes++;o.castShadow=false;o.receiveShadow=false;
  for(const m of Array.isArray(o.material)?o.material:[o.material]){
   if(m.map)textured++;
   if(m.name.startsWith('MAT_Meshy_BodyAtlas')){m.roughness=.34;m.metalness=.025;m.envMapIntensity=1.05;}
   if(m.name==='MAT_Wing_Transparent'||m.name==='MAT_Wing_Vein'||m.name.startsWith('MAT_Meshy_Wing_Transparent')){
    m.transparent=true;m.opacity=m.name.startsWith('MAT_Meshy_')?.78:Math.max(m.opacity,.86);
    m.depthWrite=false;m.side=THREE.DoubleSide;
    if(m.name.startsWith('MAT_Meshy_')){m.roughness=.24;m.metalness=.02;m.color.setHex(0xf2fbff);m.emissive.setHex(0x06141a);m.emissiveIntensity=.1;}
   }m.needsUpdate=true;
  }
 });
 root.updateMatrixWorld(true);
 const bounds=new THREE.Box3().setFromObject(root),a=asset.getObjectByName('HeadPivot').getWorldPosition(new THREE.Vector3()),b=asset.getObjectByName('AbdomenPivot').getWorldPosition(new THREE.Vector3());
 const rotations=Object.fromEntries(REQUIRED.map(n=>[n,asset.getObjectByName(n).rotation.toArray()]));
 // Neutral joint pose is intentional. No fabricated gait, no time-driven flap on STOP.
 root.userData.updateRig=()=>{};
 root.userData.status={source:'ROBOT_GLTF',model:'V1.1A_WINGFIX',nodes:REQUIRED,meshes,textured,
  floor:bounds.min.y,span:bounds.getSize(new THREE.Vector3()).toArray(),forward:a.sub(b).normalize().toArray(),jointRotations:rotations};
 return root;
}
