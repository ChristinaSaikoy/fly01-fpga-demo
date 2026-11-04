import {test} from 'node:test';import assert from 'node:assert/strict';
import {legPose,targetInView,RIG,VISION} from '../app/articulation.js';
const length=(a,b)=>Math.hypot(...a.map((v,i)=>v-b[i]));
test('six legs preserve both bone lengths and never target below the floor',()=>{
 for(let angle=-12;angle<12;angle+=.031)for(const side of [-1,1])for(let i=0;i<3;i++){
  const p=legPose(angle,Math.abs(angle),side,i);
  assert.ok(Math.abs(length(p.hip,p.knee)-RIG.upper)<1e-10);
  assert.ok(Math.abs(length(p.knee,p.foot)-RIG.lower)<1e-10);
  assert.ok(p.foot[1]>=RIG.ground/RIG.scale-1e-12);assert.ok(p.lift<=.180001);
 }
});
test('initial stance places all six feet on the ground and startup is continuous',()=>{
 for(const side of [-1,1])for(let i=0;i<3;i++){
  const p=legPose(0,0,side,i),next=legPose(.00001,.00001,side,i);
  assert.equal(p.lift,0);assert.ok(length(p.foot,next.foot)<1e-6);
 }
});
test('tripods alternate, seeking and reversing have no pose reset',()=>{
 const legs=[-1,1].flatMap(side=>[0,1,2].map(i=>legPose(.15,.15,side,i)));
 assert.equal(legs.filter(p=>p.lift>1e-8).length,3);
 const before=legPose(1,3,-1,0),after=legPose(1,4,-1,0);assert.deepEqual(before,after);
});
test('visibility matches the drawn body-centered sector, including range and angular boundaries',()=>{
 assert.equal(targetInView(0,0,-3).visible,true);assert.equal(targetInView(Math.PI,0,-3).visible,false);
 assert.equal(targetInView(0,0,-VISION.range).visible,true);assert.equal(targetInView(0,0,-VISION.range-.01).visible,false);
 assert.equal(targetInView(0,3,0).visible,false);assert.equal(targetInView(0,0,0).visible,false);
 for(const sign of [-1,1]){const a=sign*(VISION.halfAngle+.001);assert.equal(targetInView(0,-Math.sin(a)*3,-Math.cos(a)*3).visible,false);}
});
