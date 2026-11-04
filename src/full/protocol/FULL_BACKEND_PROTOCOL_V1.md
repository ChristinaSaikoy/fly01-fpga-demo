# FLY-01 FULL BACKEND PROTOCOL V1

Protocol version: `FLY01_FULL_BACKEND_PROTOCOL_V1`.

## Boundary

The backend accepts frozen `SourceDrive q_vector[311]` and returns a frozen-semantics binary `DNFrame[32]`.

The following remain outside this backend:
- FeedbackFrame / Visual Encoder
- WorldState / BodyState
- FINAL_DN_MOTOR_MAPPING_V1_0
- BodyRuntime
- renderer

## Transport

Reference transport: localhost HTTP on `127.0.0.1`.

Endpoints:
- `GET /status`
- `POST /reset`
- `POST /step`

Transport and backend core are separate modules. Public cloud deployment, TLS, WAN routing, and authentication are not part of FULL-4.

## Lockstep

`MAX_IN_FLIGHT_STEP_PER_SESSION = 1`.

A STEP is accepted only when no STEP/RESET holds the session execution lock. A concurrent STEP receives `BUSY`. There is no unbounded request queue.

## STEP

Required request fields:
`protocol_version, session_id, reset_generation, frame_id, target_neural_timestep_id, source_feedback_frame_id, q_vector[311], q_vector_sha256`.

Rules:
- `target_neural_timestep_id == frame_id`
- frame 0: `source_feedback_frame_id = null`
- frame k>0: `source_feedback_frame_id = k-1`
- q vector contains exactly 311 JSON integers
- q hash is SHA256 of canonical compact JSON integer-array serialization

A successful STEP executes exactly 200 Full-LIF ticks and preserves v, g, last-spike/refractory state, delay ring, spike counts, and tick counter for the next request.

## Ordering and retries

Expected frame IDs are strictly consecutive.

- future frame: `FRAME_GAP`
- older uncached frame: `STALE_FRAME`
- most recent successful frame + identical payload: cached response, `replayed_response=YES`, no state advance
- most recent successful frame + different payload: `DUPLICATE_FRAME_CONFLICT`

Only the most recent successful response is retained. This is sufficient for lockstep transport-timeout retry while keeping cache memory bounded.

## RESET

RESET requires the protocol version and fixed reference session ID.

Successful RESET:
- increments reset_generation
- clears v/g/refractory/last-spike state
- clears delay ring
- resets Full tick and FLY frame counters
- clears adapter/DN aggregation stream state
- clears retry cache
- returns frame_expected=0

Requests from an earlier generation are rejected with `STALE_GENERATION`.

## Errors and mutation

Validation errors do not execute neural ticks and do not mutate neural state.

Defined reference errors include:
`WRONG_PROTOCOL_VERSION, WRONG_SESSION, STALE_GENERATION, BAD_FRAME_ID, BAD_TARGET_NEURAL_TIMESTEP, BAD_SOURCE_FRAME, BAD_Q_LENGTH, NONINTEGER_Q, MISSING_Q_HASH, PAYLOAD_HASH_MISMATCH, FRAME_GAP, STALE_FRAME, DUPLICATE_FRAME_CONFLICT, BUSY, MALFORMED_PACKET, BACKEND_COMPUTE_FAILURE`.

## STATUS

STATUS is model-nonmutating and reports readiness, versions/hashes, current session, generation, expected frame, Full tick counter, busy flag, and last error. STATUS never advances the neural model.

## Timeout boundary

A client transport timeout is not a backend compute failure. A timed-out client retries the same frame/payload/generation and obtains the cached successful response if the backend completed it.

No 20 ms transport timeout is imposed in FULL-4.

## Claims

Reference mode is lockstep and not real-time.

`REALTIME_CLAIM = NO`.

FULL-4 terminates at DNFrame[32]. Mapper and BodyRuntime are not executed.
