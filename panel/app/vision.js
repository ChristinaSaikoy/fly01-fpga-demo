import * as THREE from 'three';
import {targetInView,VISION} from './articulation.js';
export function createVision(scene){
 const object=new THREE.Group(),mat=new THREE.MeshStandardMaterial({color:0x5e9bc6,roughness:.4,metalness:.25});
 const cube=new THREE.Mesh(new THREE.BoxGeometry(.6,.6,.6),mat);cube.position.y=-.58;object.add(cube);
 const ring=new THREE.Mesh(new THREE.TorusGeometry(.52,.025,8,48),new THREE.MeshBasicMaterial({color:0xf3d084}));ring.rotation.x=-Math.PI/2;ring.position.y=-.87;object.add(ring);scene.add(object);
 const points=[new THREE.Vector3(0,-.875,0)];
 for(let i=0;i<=64;i++){const a=-VISION.halfAngle+i/64*2*VISION.halfAngle;points.push(new THREE.Vector3(-Math.sin(a)*VISION.range,-.875,-Math.cos(a)*VISION.range));}
 const verts=[];for(let i=1;i<points.length-1;i++)for(const p of [points[0],points[i],points[i+1]])verts.push(p.x,p.y,p.z);
 const geom=new THREE.BufferGeometry();geom.setAttribute('position',new THREE.Float32BufferAttribute(verts,3));
 const field=new THREE.Group();field.add(new THREE.Mesh(geom,new THREE.MeshBasicMaterial({color:0x6ca9b1,transparent:true,opacity:.08,side:THREE.DoubleSide,depthWrite:false})));
 field.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([...points,points[0]]),new THREE.LineBasicMaterial({color:0x49777e,transparent:true,opacity:.65})));scene.add(field);
 const lineGeom=new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(),new THREE.Vector3()]);
 const ray=new THREE.Line(lineGeom,new THREE.LineDashedMaterial({color:0xf3d084,dashSize:.12,gapSize:.08,transparent:true,opacity:.75}));scene.add(ray);
 let enabled=false,bearing=0,distance=3;
 const position=()=>object.position.set(-Math.sin(bearing)*distance,0,-Math.cos(bearing)*distance);
 return {
  place(bodyYaw,side){enabled=side!=='off';bearing=bodyYaw+(side==='left'?.7:side==='right'?-.7:0);position();},
  setDistance(value){distance=Math.max(1.5,Math.min(8,Number(value)||3));position();},
  update(bodyYaw,allow){
   object.visible=field.visible=enabled&&allow;field.rotation.y=bodyYaw;
   const v=targetInView(bodyYaw,object.position.x,object.position.z),seen=enabled&&allow&&v.visible;
   ring.visible=ray.visible=seen;mat.emissive.setHex(seen?0x15483b:0);
   if(seen){const a=lineGeom.attributes.position;a.setXYZ(0,-Math.sin(bodyYaw)*.67,.12,-Math.cos(bodyYaw)*.67);a.setXYZ(1,object.position.x,-.3,object.position.z);a.needsUpdate=true;lineGeom.computeBoundingSphere();ray.computeLineDistances();}
   // Fade head deflection near the FOV boundary; deterministic at the same replay time.
   const fade=Math.min(1,Math.max(0,(VISION.halfAngle-Math.abs(v.relative))/.18),Math.max(0,(VISION.range-v.distance)/.5));
   return {seen,look:seen?Math.max(-.35,Math.min(.35,v.relative))*fade:0,
    label:!allow?'真实视觉未接入':!enabled?'合成目标已隐藏':seen?'合成视野内 · 目标可见':'合成视野外 · 未看见',
    detail:!allow||!enabled?'范围：主体朝向 ±60° / 7 场景单位':`${Math.abs(v.relative*180/Math.PI).toFixed(0)}° ${v.relative>=0?'左侧':'右侧'} · ${v.distance.toFixed(1)} 场景单位`};
  }
 };
}
