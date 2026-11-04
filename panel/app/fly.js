import * as THREE from 'three';
import {legPose,RIG} from './articulation.js';
function ellipsoid(radius,scale,material){
  const m=new THREE.Mesh(new THREE.SphereGeometry(radius,32,20),material);m.scale.copy(scale);m.castShadow=true;return m;
}
function cylinderBetween(a,b,r,mat){
  const mid=a.clone().add(b).multiplyScalar(.5);
  const len=a.distanceTo(b);
  const mesh=new THREE.Mesh(new THREE.CylinderGeometry(r,r,len,10),mat);
  mesh.position.copy(mid);mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),b.clone().sub(a).normalize());
  return mesh;
}
function buildFly(){
  const root=new THREE.Group();root.name='FlyRoot';
  const dark=new THREE.MeshStandardMaterial({color:0x211b17,roughness:.7,metalness:.05});
  const abdomenMat=new THREE.MeshStandardMaterial({color:0x3a2d1f,roughness:.65});
  const eyeMat=new THREE.MeshStandardMaterial({color:0x8d2024,roughness:.35});
  const legMat=new THREE.MeshStandardMaterial({color:0x665746,roughness:.55});
  const jointMat=new THREE.MeshStandardMaterial({color:0xd4a862,metalness:.5,roughness:.3});
  const wingMat=new THREE.MeshPhysicalMaterial({color:0xdcecff,transparent:true,opacity:.36,roughness:.15,side:THREE.DoubleSide,depthWrite:false});
  const thorax=ellipsoid(.68,new THREE.Vector3(.72,.63,.86),dark);root.add(thorax);
  const neck=new THREE.Group();neck.position.z=-.82;root.add(neck);
  const head=ellipsoid(.48,new THREE.Vector3(.8,.72,.7),dark);neck.add(head);
  const abdomen=ellipsoid(.74,new THREE.Vector3(.55,.5,1.08),abdomenMat);abdomen.position.z=.95;root.add(abdomen);
  for(const sx of [-1,1]){
    const eye=ellipsoid(.24,new THREE.Vector3(.7,1,.55),eyeMat);eye.position.set(.31*sx,.06,-.26);neck.add(eye);
    neck.add(cylinderBetween(new THREE.Vector3(.13*sx,.2,-.2),new THREE.Vector3(.3*sx,.48,-.55),.025,jointMat));
  }
  for(const sx of [-1,1]){
    const wing=new THREE.Mesh(new THREE.CircleGeometry(.82,32,0,Math.PI),wingMat);
    wing.scale.set(1.55,.58,1);wing.rotation.set(-Math.PI/2,.15*sx,-.3*sx);
    wing.position.set(.63*sx,.22,.25);root.add(wing);
  }
  const legs=[];
  for(const side of [-1,1])for(let i=0;i<3;i++){
    const hip=new THREE.Group();hip.name=`hip-${side}-${i}`;hip.position.set(.4*side,-.25,(i-1)*.48);root.add(hip);
    const kneePos=new THREE.Vector3(0,-RIG.upper,0);
    hip.add(cylinderBetween(new THREE.Vector3(),kneePos,.046,legMat));
    hip.add(ellipsoid(.075,new THREE.Vector3(1,1,1),jointMat));
    const knee=new THREE.Group();knee.name=`knee-${side}-${i}`;knee.position.copy(kneePos);hip.add(knee);
    knee.add(ellipsoid(.065,new THREE.Vector3(1,1,1),jointMat));
    const foot=new THREE.Vector3(0,-RIG.lower,0);
    knee.add(cylinderBetween(new THREE.Vector3(),foot,.035,legMat));
    const toe=ellipsoid(.055,new THREE.Vector3(1.6,.5,2.1),legMat);toe.position.copy(foot);knee.add(toe);
    legs.push({hip,knee,toe,side,i});
  }
  const down=new THREE.Vector3(0,-1,0),upper=new THREE.Vector3(),lower=new THREE.Vector3(),inverse=new THREE.Quaternion();
  root.userData.updateRig=(angle,travel,look=0,detected=false)=>{
    for(const leg of legs){
      const p=legPose(angle,travel,leg.side,leg.i);
      upper.fromArray(p.knee).sub(leg.hip.position).normalize();leg.hip.quaternion.setFromUnitVectors(down,upper);
      inverse.copy(leg.hip.quaternion).invert();
      lower.fromArray(p.foot).sub(new THREE.Vector3().fromArray(p.knee)).normalize().applyQuaternion(inverse);
      leg.knee.quaternion.setFromUnitVectors(down,lower);
      leg.toe.quaternion.copy(leg.knee.quaternion).invert().multiply(inverse);
    }
    neck.rotation.y=look;eyeMat.emissive.setHex(detected?0x962d12:0x000000);eyeMat.emissiveIntensity=.65;
  };
  root.add(new THREE.ArrowHelper(new THREE.Vector3(0,0,-1),new THREE.Vector3(0,.82,0),1.25,0xf0c55d,.22,.12));
  root.scale.setScalar(RIG.scale);
  return root;
}

export {buildFly};
