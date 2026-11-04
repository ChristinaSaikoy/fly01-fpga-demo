# FULL-3 Timebase Contract V1

Outer FLY timebase:
- dt = 20 ms.
- FLY frame id k has model timestamp k * 20 ms.

Full LIF timebase:
- dt = 0.1 ms.
- exactly 200 Full ticks per FLY frame.
- neural frame k owns ticks k*200 through k*200+199 inclusive.

Frozen causal delay:
1. Observe/construct FeedbackFrame[k].
2. Frozen sensory encoder computes SourceDrive targeting neural frame k+1.
3. SourceDrive already queued from FeedbackFrame[k-1] is applied during Full window k.
4. Full MaleCNS executes all 200 ticks continuously; state and delay ring persist across FLY frames.
5. FULL_DN_ADAPTER_V1 OR-aggregates DN spikes in exactly this 200-tick window into DNFrame[k].
6. FeedbackFrame[k] never affects Full window k.

Initial condition:
- neural frame 0 uses all-zero SourceDrive with no source feedback frame.
- FeedbackFrame[0] produces SourceDrive[1].

Frame lineage fields:
- FLY_FRAME_ID = k.
- FULL_TICK_START = k*200.
- FULL_TICK_END = k*200+199.
- SOURCE_FRAME = k-1 for applied non-initial SourceDrive; null for k=0.
- TARGET_NEURAL_FRAME = k.

Reset clears:
- v, g, last-spike/refractory state, delay ring.
- global Full tick counter.
- FLY frame counter.
- pending SourceDrive/adapter phase.
- DN aggregation state.
