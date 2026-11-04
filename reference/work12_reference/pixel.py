"""PixelDirectionMVP: engineering category, not calibrated geometry or BODY feedback."""
from copy import deepcopy
import math

class PixelDirectionMVP:
    def __init__(self,roster,q,deadband_px=2,max_age_ms=250):
        if len(roster)!=311 or q!=2458 or not math.isfinite(deadband_px) or deadband_px<0:
            raise ValueError('frozen roster/intensity and nonnegative threshold required')
        if not math.isfinite(max_age_ms) or max_age_ms<=0:raise ValueError('finite age bound')
        self.roster,self.q=roster,q;self.deadband=deadband_px;self.max_age=max_age_ms
        self.latest=self.pending=None;self.session=None;self.last_frame=-1;self.next_step=0
        self.reason='NO_OBSERVATION';self.events=[]
    def submit(self,o):
        o=deepcopy(o)
        try:
            if o.get('schema')!='BY02_VISION_OBSERVATION_V1':raise ValueError('BY02 schema')
            if o.get('coordinate_system')!='IMAGE_X_RIGHT_Y_DOWN_PIXEL_CENTERS':raise ValueError('coordinates')
            if self.session is None:self.session=o['session_id']
            if o['session_id']!=self.session or type(o['frame_id']) is not int or o['frame_id']<=self.last_frame:raise ValueError('identity/order')
            if o['clock_domain']!='HOST_MONOTONIC' or o['processed_monotonic_ns']<o['received_monotonic_ns']:raise ValueError('clock')
            self.last_frame=o['frame_id']
            if o['status']!='VALID' or o['object_count']!=1:
                self.latest=self.pending=None;self.reason=o['status'];return False
            w,h=o['width'],o['height'];c=o['selected_center_xy']
            if type(w)is not int or type(h)is not int or min(w,h)<2 or not isinstance(c,list) or len(c)!=2 or any(not math.isfinite(v) for v in c) or not(0<=c[0]<w and 0<=c[1]<h):raise ValueError('pixels')
            delta=c[0]-(w-1)/2
            group='LEFT' if delta < -self.deadband else 'RIGHT' if delta>self.deadband else 'BILATERAL'
            self.latest=dict(id=f"{o['session_id']}:{o['frame_id']}",group=group,
                received_ns=o['received_monotonic_ns'],processed_ns=o['processed_monotonic_ns'],
                pixel_center_xy=c,width=w,height=h,source=o['source'],status='VALID')
            self.reason='VALID';return True
        except (ValueError,KeyError,TypeError,OverflowError) as exc:
            self.latest=self.pending=None;self.reason='REJECTED:'+str(exc);return False
    def select(self,o,now):
        age=(now-o['received_ns'])/1e6 if o else None
        valid=o is not None and 0<=age<self.max_age and now>=o['processed_ns']
        group=o['group'] if valid else 'NONE'
        q=[self.q if group=='BILATERAL' or group in ('LEFT','RIGHT') and row['side']==group[0] else 0 for row in self.roster]
        return dict(observation_id=o['id'] if valid else None,group=group,q=q,age_ms=age,
            received_ns=o['received_ns'] if valid else None,
            reason='HOLD_WITHIN_RECEIVE_AGE' if valid else ('STALE' if o else self.reason),
            age_basis='HOST_RECEIVE_ESTIMATE_UNKNOWN_EXPOSURE',geometry_verified=False,
            capture_time_status='UNKNOWN_EXPOSURE',motion_eligible=False)
    def sample(self,k,now):
        if k!=self.next_step:raise ValueError('cannot skip or repeat adopted neural step')
        applied=self.select(self.pending,now);scheduled=self.select(self.latest,now)
        self.pending=deepcopy(self.latest) if scheduled['observation_id'] else None
        self.next_step+=1
        return dict(schema='PixelDirectionMVP',model_step=k,target_next_step=k+1,
            deadband_px=self.deadband,max_receive_age_ms=self.max_age,applied=applied,scheduled=scheduled,
            neutral_is_not_brake=True,center_is_not_straight=True)
