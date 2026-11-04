"""Authoritative integer-model candidate for S4-SCOPE-1B. No RTL."""
from dataclasses import dataclass
import numpy as np

@dataclass(frozen=True)
class FixedFormat:
    name: str
    w_bits: int
    w_frac: int
    s_bits: int
    s_frac: int
    a_bits: int
    a_frac: int
    d_bits: int
    d_frac: int

FORMATS = {
    "MINIMAL": FixedFormat("MINIMAL", 12, 10, 16, 12, 20, 14, 16, 15),
    "RECOMMENDED": FixedFormat("RECOMMENDED", 16, 14, 18, 13, 24, 18, 18, 17),
    "SAFE": FixedFormat("SAFE", 18, 16, 20, 15, 28, 22, 18, 17),
}

def signed_bounds(bits):
    return -(1 << (bits - 1)), (1 << (bits - 1)) - 1

def unsigned_bounds(bits):
    return 0, (1 << bits) - 1

def round_away_float(x):
    x = np.asarray(x, dtype=np.float64)
    return np.sign(x) * np.floor(np.abs(x) + 0.5)

def quantize_signed(x, bits, frac):
    lo, hi = signed_bounds(bits)
    q = round_away_float(np.asarray(x, dtype=np.float64) * (1 << frac))
    return np.clip(q, lo, hi).astype(np.int64)

def quantize_unsigned(x, bits, frac):
    lo, hi = unsigned_bounds(bits)
    q = np.floor(np.asarray(x, dtype=np.float64) * (1 << frac) + 0.5)
    return np.clip(q, lo, hi).astype(np.int64)

def rshift_round_away_scalar(x, shift):
    if shift <= 0:
        return int(x) << (-shift)
    x = int(x)
    a = abs(x)
    q = a >> shift
    rem = a & ((1 << shift) - 1)
    half = 1 << (shift - 1)
    if rem >= half:
        q += 1
    return q if x >= 0 else -q

def sat_scalar(x, bits):
    lo, hi = signed_bounds(bits)
    if x < lo:
        return lo, True
    if x > hi:
        return hi, True
    return int(x), False

class CandidateBInteger:
    """Exact integer semantics frozen by s4_scope1_numeric_candidates.json."""

    def __init__(self, pre_local, post_local, weights_float, fmt: FixedFormat):
        self.fmt = fmt
        self.n = int(max(pre_local.max(initial=0), post_local.max(initial=0)) + 1)
        self.pre = np.asarray(pre_local, dtype=np.int32)
        self.post = np.asarray(post_local, dtype=np.int32)
        self.wq = quantize_signed(weights_float, fmt.w_bits, fmt.w_frac)
        self.row = np.zeros(self.n + 1, dtype=np.int64)
        np.cumsum(np.bincount(self.pre, minlength=self.n), out=self.row[1:])
        if not np.all(self.pre[:-1] <= self.pre[1:]):
            raise ValueError("pre_local must be source-sorted CSR order")
        self.decay_q = int(quantize_unsigned(0.8187308, fmt.d_bits, fmt.d_frac))
        self.tonic_q = int(quantize_signed(0.14, fmt.s_bits, fmt.s_frac))
        self.stim_q = int(quantize_signed(0.30, fmt.s_bits, fmt.s_frac))
        self.noise_q = int(quantize_signed(0.22, fmt.s_bits, fmt.s_frac))
        self.threshold_q = 1 << fmt.s_frac
        self.reset()

    def reset(self):
        self.state = np.zeros(self.n, dtype=np.int64)
        self.prev_fired = np.empty(0, dtype=np.int32)
        self.acc_saturation_count = 0
        self.state_saturation_count = 0
        self.steps = 0

    def source_drive(self, source_local):
        for i in np.asarray(source_local, dtype=np.int32):
            v, sat = sat_scalar(int(self.state[i]) + self.stim_q, self.fmt.s_bits)
            self.state[i] = v
            self.state_saturation_count += int(sat)

    def step(self, noise_local=()):
        f = self.fmt
        acc = np.zeros(self.n, dtype=np.int64)
        w_to_a_shift = f.a_frac - f.w_frac
        if w_to_a_shift < 0:
            raise ValueError("accumulator frac must be >= weight frac")
        for src in self.prev_fired:
            for e in range(int(self.row[src]), int(self.row[src + 1])):
                dst = int(self.post[e])
                term = int(self.wq[e]) << w_to_a_shift
                v, sat = sat_scalar(int(acc[dst]) + term, f.a_bits)
                acc[dst] = v
                self.acc_saturation_count += int(sat)

        next_state = np.empty(self.n, dtype=np.int64)
        acc_to_state_shift = f.a_frac - f.s_frac
        for i in range(self.n):
            decayed = rshift_round_away_scalar(
                int(self.state[i]) * self.decay_q, f.d_frac)
            current_acc = int(acc[i]) * 3
            current_state = rshift_round_away_scalar(
                current_acc, acc_to_state_shift)
            v = decayed + current_state + self.tonic_q
            next_state[i] = v

        for i in np.asarray(noise_local, dtype=np.int32):
            next_state[i] += self.noise_q

        fired = np.flatnonzero(next_state >= self.threshold_q).astype(np.int32)
        next_state[fired] = 0

        fired_mask = np.zeros(self.n, dtype=bool)
        fired_mask[fired] = True
        for i in range(self.n):
            if fired_mask[i]:
                continue
            v, sat = sat_scalar(int(next_state[i]), f.s_bits)
            next_state[i] = v
            self.state_saturation_count += int(sat)

        self.state = next_state
        self.prev_fired = fired
        self.steps += 1
        return fired

    def state_float(self):
        return self.state.astype(np.float64) / float(1 << self.fmt.s_frac)
