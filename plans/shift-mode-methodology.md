# Operational-time formulation of duty-cycle-dependent degradation

## Calendar time vs. operational time

Let `t` denote calendar time. Define an *operating-rate function* `ρ(t) ∈ {0,1}`, indicating
whether the unit is in active service at calendar instant `t` (1 during a scheduled shift on
an active day, 0 otherwise). The unit's *operational age* — the cumulative exposure that
drives degradation — is

```
A(t) = ∫₀ᵗ ρ(s) ds
```

rather than `t` itself. This separates the calendar clock (used for maintenance/replacement
scheduling, which remains date-driven) from the wear clock (used for the failure process,
which only advances during active operation).

## Periodicity

The shift schedule is periodic with period `T = 7` days: `ρ(t + T) = ρ(t)`. Consequently `A`
decomposes exactly as

```
A(t) = ⌊t/T⌋ · W + a(t mod T),      W = ∫₀ᵗ ρ(s) ds
```

where `W` is the total weekly operating time and `a(τ) = ∫₀^τ ρ(s) ds` for `τ ∈ [0, T)` is
the *within-period exposure function* — a piecewise-linear, non-decreasing step function with
one breakpoint per shift (≤ 7 × |shifts/day| breakpoints total). Both `W` and `a(·)` are fixed
for the simulation, since the duty cycle is assigned once per unit and does not change during
a run (no shift-stacking/coverage — see scope note below).

## Failure process

The unit's lifetime is governed by a Weibull hazard defined on the operational-time scale:
failure occurs when `A(t)` first reaches a random threshold `X ~ Weibull(η, β)`. This is the
standard formalization of usage-based (as opposed to age-based) reliability models — the
hazard accumulates with exposure, not elapsed calendar time.

## Residual-life sampling

Given survival to calendar time `t₀` (operational age `A(t₀)`), the residual operational
lifetime `R` is drawn by inverse-cumulative-hazard sampling, exactly as for the calendar-time
case but evaluated on `A(t₀)` rather than `t₀`:

```
H(a) = (a/η)^β
U ~ Uniform(0,1)
a* = η · (H(A(t₀)) − ln U)^{1/β}
R  = a* − A(t₀)
```

## Mapping residual operational time back to calendar time

The failure event occurs at the calendar instant `t_f = A⁻¹(A(t₀) + R)`. Because `A` is
periodic and piecewise-linear, this inverse has a closed form rather than requiring numerical
root-finding or discretized search:

```
target = A(t₀) + R
n = ⌊target / W⌋,    r = target − nW            (0 ≤ r < W)
t_f = n·T + a⁻¹(r)
```

where `a⁻¹(r)` is evaluated against the fixed within-period exposure table — a constant-size
(≤7-row) lookup.

## Complexity

Because the duty cycle is periodic and fixed for the duration of the simulation, both `A(t)`
and its inverse reduce to a quotient/remainder decomposition plus a bounded-size table lookup:
**O(1)** per evaluation, independent of the simulation horizon. This is the relevant contrast
to a naive discretized simulation of exposure accumulation (stepping through the horizon at,
e.g., daily resolution), which would require `O(N)` operations per query, where `N` is the
number of elapsed periods — a meaningful distinction given the failure time is re-evaluated
frequently under the discrete-event re-scheduling scheme used here (each rescheduling event
redraws the failure time for the affected unit from its current operational age, with no
caching of prior draws).

## Modeling assumption

Degradation is treated as a deterministic function of accumulated *operating* time rather
than calendar time, with the duty cycle entering only through the periodic exposure function
`ρ(·)` — a standard simplification in reliability models for intermittently-operated equipment,
as opposed to continuously-operated equipment where `A(t) ≡ t` (the latter is exactly the
existing "continuous" mode, recovered when `ρ(t) ≡ 1`).

## Note on scope vs. an averaged-rate alternative

A simpler, related formulation replaces `ρ(·)` with its time-average `duty_factor = W / T` and
rescales the Weibull scale parameter directly: `η_eff = η / duty_factor`, with `current_age`
left in calendar units. This is exact in the long-run average sense (Weibull scale parameters
transform linearly under a constant time-rescaling) but discards sub-period phase information
(which day of the week a failure lands on). The exact formulation above is used instead because
it costs the same O(1) per evaluation and preserves that information, at the cost of a small,
fixed-size weekly lookup table per unit instead of a single scalar.

## Scope note (current implementation)

Per the simplified failure-response policy adopted for this feature: when a unit fails, only
the existing STANDBY pool is checked for a replacement (as today) — shifts are never
redistributed onto other active units. Consequently a unit's duty cycle, and therefore its
`ρ(·)`/`a(·)`/`W` table, is fixed for the entire simulation run and is computed once at
simulation start.
