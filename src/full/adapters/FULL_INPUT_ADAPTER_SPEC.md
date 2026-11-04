# FULL_INPUT_ADAPTER_V1 Specification

Identity: ENGINEERING ADAPTER.

Frozen input:
- drive_q_by_input_ordinal[311] from DEMO-1_SENSORY_ENCODER_V1_0.
- q values belong to Candidate-B integer source-state increment semantics.
- q magnitude is NOT interpreted as MaleCNS voltage, rate, current, or contact count.

Activation rule:
- q == 0 -> inactive.
- q != 0 -> active.

Binding:
- input ordinal is preserved.
- encoder roster root_id == FULL-1 input-map body_id, 311/311.
- FULL runtime target is INPUT_311_INDEX_MAP.runtime_index.
- roster global_index is legacy brain.npz index and is forbidden as Full runtime index.

Drive policy:
- Shiu-default 150 Hz is represented by a deterministic equivalent.
- 20 ms frame = 200 Full ticks at 0.1 ms.
- 3 events per active input per frame.
- local event ticks = floor((j+0.5)*200/3), j=0,1,2 = [33,100,166].
- placement is frame-bound and does not depend on downstream output.

Refractory:
- active Full visual input target: rfc = 0 ms during that Full window.
- inactive Full visual input target: ordinary rfc = 2.2 ms.
- this is an upstream-semantics engineering policy, not biological sensory transduction.

Causality:
- FeedbackFrame[k] is encoded as SourceDrive targeting neural frame k+1.
- neural frame 0 receives an all-zero initial SourceDrive.
