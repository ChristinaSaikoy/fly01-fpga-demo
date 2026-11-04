// Visual kinematics only. These lengths and scene units are not measurements of the car.
export const RIG={scale:.82,ground:-.9,upper:.68,lower:.78};
export const VISION={range:7,halfAngle:Math.PI/3};
const add=(a,b)=>a.map((v,i)=>v+b[i]),sub=(a,b)=>a.map((v,i)=>v-b[i]);
const mul=(a,s)=>a.map(v=>v*s),dot=(a,b)=>a.reduce((n,v,i)=>n+v*b[i],0);
const unit=a=>mul(a,1/Math.hypot(...a));
export function solveLeg(hip,foot,side){
 const delta=sub(foot,hip),d=Math.hypot(...delta),dir=unit(delta);
 if(d>RIG.upper+RIG.lower||d<Math.abs(RIG.upper-RIG.lower))throw Error('Visual foot target is unreachable');
 const pole=[side,.6,0],bend=unit(sub(pole,mul(dir,dot(pole,dir))));
 const along=(RIG.upper**2-RIG.lower**2+d*d)/(2*d);
 const height=Math.sqrt(Math.max(0,RIG.upper**2-along**2));
 return add(hip,add(mul(dir,along),mul(bend,height)));
}
export function legPose(angle,travel,side,index){
 const ramp=Math.min(1,Math.max(0,travel)/.12),amplitude=ramp*ramp*(3-2*ramp);
 const phase=angle*16+(index%2?Math.PI:0)+(side>0?Math.PI:0);
 const hip=[.4*side,-.25,(index-1)*.48];
 const foot=[1.25*side,RIG.ground/RIG.scale,(index-1)*.85];
 const radius=Math.hypot(foot[0],foot[2]),stroke=Math.sin(phase)*.16*amplitude;
 // Tangential foot sweep for in-place turning, alternating tripod lift.
 foot[0]+=foot[2]/radius*stroke;foot[2]-=1.25*side/radius*stroke;
 foot[1]+=Math.max(0,Math.sin(phase))*.18*amplitude;
 return {hip,knee:solveLeg(hip,foot,side),foot,lift:foot[1]-RIG.ground/RIG.scale};
}
export function targetInView(bodyYaw,x,z){
 const distance=Math.hypot(x,z),bearing=Math.atan2(-x,-z);
 const relative=Math.atan2(Math.sin(bearing-bodyYaw),Math.cos(bearing-bodyYaw));
 return {visible:distance>0&&distance<=VISION.range&&Math.abs(relative)<=VISION.halfAngle,relative,distance};
}
