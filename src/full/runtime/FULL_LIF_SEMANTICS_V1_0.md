# FULL_LIF_SEMANTICS_V1_0

TASK = FULL-1-CANONICAL-GRAPH-DYNAMICS-RECONSTRUCTION

MODEL_IDENTITY =
MaleCNS v1.0 structural connectome
+
Shiu-derived engineering LIF dynamics

BIOLOGICAL_GROUND_TRUTH_CLAIM = NO
MALECNS_PARAMETER_REFIT = NO

## Primary dynamics source

Primary reference:
philshiu/Drosophila_brain_model
commit 91bdd1e7dcf193f3e7ca5a8933497fcef63b7960
model.py

The upstream frozen environment records Python 3.10.11, Brian2 2.5.1 and NumPy 1.22.3.
FULL-1 reproduced that Python/Brian2/NumPy combination for semantics tests.

Third-party Kisame76/drosophila-brain-mlx is retained only as an independent engineering reference.
It does not replace the upstream Shiu semantics and its MaleCNS outputs are not biological ground truth.

## Frozen continuous equations

For a neuron that is not refractory:

dv/dt = (v_rest - v + g) / tau_membrane

dg/dt = -g / tau_synaptic

with:

v_rest = -52 mV
v_reset = -52 mV
v_threshold = -45 mV
tau_membrane = 20 ms
tau_synaptic = 5 ms
refractory = 2.2 ms
synaptic_delay = 1.8 ms
w_syn = 0.275 mV per signed synaptic contact

Threshold comparison is strict:

v > -45 mV

w_syn is explicitly a free parameter in the Shiu implementation.
It has NOT been refit to MaleCNS.
## Simulation clock

Brian2 2.5.1 defaultclock under the upstream-compatible environment was measured directly:

dt = 0.1 ms

The upstream model.py does not override defaultclock.dt.

Therefore:

refractory = 22 ticks
synaptic delay = 18 ticks

The actual Brian2 default schedule was measured as:

start
groups
thresholds
synapses
resets
end

FULL_CPU_ORACLE_V1 follows this schedule semantically.

## Exact one-tick ordering

For model tick k:

### 1. Refractory refresh

FULL_CPU_ORACLE_V1 evaluates not_refractory as (tick - last_spike_tick) >= refractory_ticks before the state update.

A neuron that spiked at tick k0 with refractory = 2.2 ms is blocked for the following interval and becomes eligible again at tick k0 + 22.

Direct Brian2 experiment:
spike at t = 0.0 ms
not_refractory = false through t = 2.1 ms
not_refractory = true at t = 2.2 ms

### 2. State update — groups slot

Only neurons currently not refractory update v and g.

Brian2 method='linear' is represented in the float64 oracle using the closed-form update with the operation association validated against Brian2 2.5.1:

DECAY_V = exp(-dt / tau_membrane)

DECAY_G = exp(-dt / tau_synaptic)

V0_TERM =
v_rest - v_rest * exp(-dt / tau_membrane)

COUPLE_G =
((tau_synaptic / (tau_membrane - tau_synaptic))
 * (-exp(dt/tau_membrane) + exp(dt/tau_synaptic))
 * exp(-dt/tau_membrane))
 * exp(-dt/tau_synaptic)

Then:

v_updated =
V0_TERM + (g * COUPLE_G + v * DECAY_V)

g_updated =
g * DECAY_G

A refractory neuron retains its previous v and g at this phase.
### 3. Threshold evaluation — thresholds slot

After the state update and BEFORE same-tick synaptic/external arrivals:

spike =
not_refractory AND (v > v_threshold)

Therefore an external event applied at t = 0 cannot create a t = 0 spike.

Direct Brian2 probe:
an event adding +68.75 mV to a resting neuron at t = 0 produced its spike at t = 0.1 ms.

### 4. Delayed recurrent propagation — synapses slot

A spike generated at tick k is delivered through recurrent synapses at:

k + 18 ticks

which is exactly 1.8 ms.

Direct Brian2 probe:
source spike at t = 0
postsynaptic g first became non-zero at t = 1.8 ms.

For each active presynaptic source, the runtime sums its signed integer contact counts into every destination.

The resulting integer contact sum is multiplied by:

w_syn = 0.275 mV

and added to postsynaptic g.

For the canonical MaleCNS runtime graph:

acetylcholine -> positive signed count
GABA -> negative signed count
glutamate -> negative signed count

Unknown, unclear and modulatory presynaptic NT classes have no fast-sign outgoing runtime edge in V1.

### 5. External drive — synapses slot

Shiu upstream external activation uses Brian2 PoissonInput:

target variable = v
N = 1 per target
default rate = 150 Hz
weight = w_syn * f_poi
f_poi = 250

Therefore:

external weight per event =
0.275 mV * 250
=
68.75 mV

The upstream poi() function sets the refractory duration of every driven target to 0 ms.

For correctness validation, FULL-1 uses explicit deterministic external event trains instead of Poisson RNG.
This deliberately separates dynamics correctness from random-number-generator behavior.

External input is applied after threshold evaluation.
Its earliest possible threshold effect is therefore the next tick.

### 6. Reset — resets slot

For neurons that crossed threshold earlier in this tick:

v -> v_reset = -52 mV
g -> 0 mV

The exact upstream reset string also contains:

w = 0

but Brian2 introspection shows w is NOT a persistent NeuronGroup state variable.
A real Synapses.w remained unchanged after a neuron reset.
Therefore the persistent reset semantics are only v and g.

Because reset occurs after the synapses slot, any same-tick synaptic/external write onto a neuron that already crossed threshold is overwritten by reset.
## Refractory write semantics

Both upstream state variables are declared with:

(unless refractory)

Direct Brian2 2.5.1 tests show that this applies not only to their differential updates but also to synaptic writes.

A target that spiked at t=0 received deterministic writes during refractory:

g += 5 mV at t=0.5 ms -> DROPPED
v += 20 mV at t=0.5 ms -> DROPPED

At the exact release tick:

g += 5 mV at t=2.2 ms -> ACCEPTED
v += 20 mV at t=2.2 ms -> ACCEPTED

Therefore V1 semantics are:

SYNAPTIC INPUT ARRIVING DURING REFRACTORY = DROPPED

not accumulated
not queued

This rule is part of FULL_CPU_ORACLE_V1.

## Multiple simultaneous presynaptic spikes

All delayed signed contact counts arriving at the same destination in one tick are summed as integers before application of w_syn.

This preserves deterministic accumulation and exactly matches the canonical signed contact-count representation.

## Self loops

Self edges are retained by the canonical runtime graph.

A neuron's own spike therefore returns after the same fixed 1.8 ms delay and is treated identically to any other recurrent edge.

## Output representation

The oracle and future runtime should prefer:

spike events: (tick, runtime_index)

or:

per-neuron spike counts

A full 166,700 x every-tick dense spike raster is not part of the default runtime contract.

## Determinism boundary

Given identical:

canonical pack
initial v/g state
refractory configuration
explicit external event sequence

FULL_CPU_ORACLE_V1 must produce bit-identical repeated:

spike counts
spike events
final v
final g
final refractory timing state

Poisson RNG is outside this deterministic dynamics gate and must be separately seeded if used.

## Correctness evidence

Direct semantics probe:
evidence/BRIAN2_SEMANTICS_PROBE.json

Oracle implementation:
FULL_CPU_ORACLE_V1.py

Brian2 parity:
BRIAN2_PARITY_REPORT.json

Oracle repeatability:
CPU_ORACLE_VALIDATION.json

Independent canonical pack verification:
PACK_VERIFICATION.json
