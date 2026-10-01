# Shift mode: per-shift hours, coverage stacking, and usage-based wear

## Context

Today "shift mode" (`availability_model == "session"`) only changes how availability is **measured** (discrete checkpoint sampling in `calculate_session_availability`) and disables the standby pool. It does **not** change failure dynamics: every machine/part ages by raw calendar time regardless of mode, so `period=15` years has always meant "15 years of nonstop 24/7 operation" even in session mode. Continuous mode is, mathematically, a single 24h/day shift.

The user wants shift mode to become a real usage model:
1. Configure shifts as **days + number of shifts + hours per shift** (replacing the current `sessions_per_day` + `session_gap_hours` gap-only config), capped at ≤24h/day.
2. When a machine fails, try to cover its shift with a STANDBY machine first; if none free, stack the shift onto an already-ACTIVE machine working a different shift that day.
3. Make Weibull aging **usage-based**: a machine/part only wears while actually working a shift. A machine covering 2 shifts in a day wears ~2x faster that day. Continuous mode must remain bit-identical to today (24/7 baseline).

## Key design decision: two clocks, joined by an exact day-walk (no averaging)

Today `MaintenanceItemSimulation.runtime` serves double duty: it's both the calendar position (used for PM cycles, replacement years, period bound) **and** the Weibull age (`current_age` fed into `weibull_residual_life`). PM/replacement schedules are calendar-based per spec and must stay that way.

So: keep `runtime` as the calendar clock (untouched semantics), and add a new `wear_age` clock used only for Weibull draws. In continuous mode `wear_age` advances 1:1 with calendar time (a machine's schedule is "always working" → identical to current behavior, bit-for-bit). In session mode, the two clocks are related by an **exact forward/backward walk through the machine's actual shift schedule**, not an averaged multiplier — this is the same day-by-day stepping pattern already used in `calculate_session_availability` (which walks days, checks `weekday in session_day_set`, and emits per-shift timestamps), generalized into a shared helper used for wear accounting too.

A machine's daily worked-hours depends only on: is today an active day (`session_days`), and which shift(s) is it working today (its own `shift_slot`'s duration, plus a covered slot's duration if `covering_for` is set). That gives a per-day "wear-hours available" number; the walker just consumes/produces against it.

**Forward (residual wear-years needed → calendar `start_time`, used when scheduling the next failure):**
Starting from the machine's current calendar position, step day by day. Each day: if it's a working day, that day contributes its shift-hours toward the residual; if the residual is exhausted partway through, the failure timestamp lands proportionally inside that day's working block (converted to a year-fraction). If not exhausted, carry the day's hours off the residual, skip to the next calendar day (non-working days contribute 0 and are skipped entirely), and repeat.

**Backward (a calendar span already elapsed → wear-hours actually accrued, used to update `wear_age` in the existing `elapsed = ...` bookkeeping):**
Same walker, run in the "sum hours worked across this date range" direction instead of "find date once N hours are worked."

Implement both as one shared helper (e.g. `functions/helper_functions.py: walk_shift_schedule(...)`) parameterized by direction, rather than two divergent implementations.

Because the existing event loop already recomputes a machine's next event (`get_next_event`) and re-pushes it into the heap (with lazy-deletion via the version counter) any time its state changes, a schedule change (start/stop covering) just means: walk-accumulate `wear_age` up to "now" under the *old* schedule, then re-push so the next failure gets redrawn (a fresh forward walk) under the *new* schedule. No architecture change needed for the FEL — this is the same pattern already used for "machine just became ACTIVE" reschedules (`self._machines_to_reschedule`). If a schedule changes again before a previously-walked event fires, that event is simply stale and gets superseded by the existing lazy-deletion mechanism once the machine is re-pushed.

## Implementation steps

### 1. Config shape (replace gap-based config with per-shift durations)
- `Alternative` (`classes/alternative.py`): replace `sessions_per_day: int` + `session_gap_hours: float` with `shift_durations: list[float]` (hours per shift, e.g. `[8, 8]`; length = number of shifts/day; validate sum ≤ 24 — validate in the API layer, not here).
- `api/routers/simulation.py` `SimulationConfig`: same field swap.
- `services/simulation_service.py`, `services/ahp_service.py`: thread `shift_durations` through instead of the two old fields (same pattern as today, just renamed/reshaped).
- Frontend `frontend/src/lib/api/types.ts`: `SimulationBehavior.shift_durations: number[]` replacing `sessions_per_day`/`session_gap_hours`; update `DEFAULT_SIMULATION_BEHAVIOR`.
- Frontend `frontend/src/routes/scenarios/+page.svelte` (~lines 339-377): replace the "Shifts/day" button group + single gap `AppInput` with: a stepper for shift count (adds/removes an entry in `shift_durations`) and one `AppInput` per shift for its hour length, validating the sum live (disable/flag if >24). Reuse the existing button-group and `AppInput` patterns already in this file.
- `db/models/scenario_profile.py`: no change — `config` is free-form JSONB.

### 2. Availability measurement (`functions/helper_functions.py: calculate_session_availability`)
- Replace `sessions_per_day`/`session_gap_hours` params with `shift_durations: list[float]`.
- Checkpoint times per active day = cumulative offsets `sum(shift_durations[:k])/24` converted to year-fraction, for `k in range(len(shift_durations))`, instead of `s * gap_years`.

### 3. Shift slot assignment (new, simulation-start only)
- At `Simulation` construction (where machines are sorted/assigned ACTIVE/STANDBY today), for session mode only: round-robin assign each ACTIVE machine a `shift_slot` index (`0..len(shift_durations)-1`) as a simulation-scoped dynamic attribute (same pattern as `pm_stagger_index`).
- This assignment is fixed for the run; only the *coverage* relationship changes during the run.

### 4. `MaintenanceItemSimulation` changes (`classes/maintenance_item_simulation.py`)
- Add `self.wear_age: float = 0` (machine-level and part-level).
- Add `self.covering_for: MachineModel | None = None` (machine-level only).
- In `get_next_event()`: machine-level and part-level Weibull draws use `self.wear_age` as `current_age` (not `self.runtime`). Convert the returned residual wear-years into a calendar `start_time` via the **forward day-walk** (`walk_shift_schedule`, see above), starting from `self.runtime`, using the machine's current `shift_slot`/`covering_for` schedule. Continuous mode: the walker degenerates to "every day is fully worked," so `start_time == self.runtime + residual` exactly as today. Part-level continues to also respect the parent machine's `runtime`/period bound check as today, just substituting wear_age/the walker for the age and time-mapping.

### 5. Runtime-mutation points (`classes/simulation.py`) — mirror existing `elapsed`/`runtime` updates with `wear_age` updates
At each of the 4 existing mutation sites (`handle_failure`, `handle_purchase_replacement`, `handle_preventive_maintenance`, `handle_end_of_maintenance`), wherever `elapsed` is computed and applied to `ps.runtime`/`machine_simulation.runtime`, also accumulate `wear_age` via the **backward day-walk** over `[previous_runtime, previous_runtime + elapsed)` under the schedule that was in effect for that segment (captured *before* any reassignment in that same handler call). Parts inherit the parent machine's schedule for their own wear_age accrual (a part only wears while its host machine is actually operating). Continuous mode: the walker degenerates to "every day fully worked," so `wear_age += elapsed` exactly as today.

### 6. Coverage / stacking logic (`classes/simulation.py: handle_failure` / `handle_end_of_maintenance`)
- Keep the existing "try STANDBY first" block unchanged (it already runs regardless of mode).
- Replace the session-mode `elif no_standby_pool: return` branch with: search ACTIVE machines with a different `shift_slot`, not already `covering_for` someone, and assign the cheapest/first eligible one: set `covering_sim.covering_for = failed_machine`. Walk-flush its `wear_age`/`runtime` bookkeeping up to now under the *old* schedule (same flush pattern as step 5), then re-push it so its next failure is redrawn (fresh forward walk) under the new, larger daily shift-hours.
- In `handle_end_of_maintenance`, when a repaired machine returns to ACTIVE, find any machine with `covering_for == machine`, clear the relationship, walk-flush + re-push it (schedule drops back to its own single shift).
- Continuous mode and the `normal_threshold >= machine_number` case keep today's existing stacking-via-maintenance-extension behavior unchanged (`no_standby_pool` flag stays for that combination).

### 7. Out of scope / unchanged
- PM and replacement scheduling stay calendar-based (no change).
- Continuous mode behavior must be verified bit-identical (duty_factor ≡ 1.0 everywhere).
- No DB migration needed (JSONB scenario config).

## Verification
- Add/adjust a quick manual run via `python app.py` (or a small script) comparing continuous-mode results before/after the refactor for the same random seed — outputs (total_cost, availabilities) should match exactly, proving the wear_age/duty_factor plumbing is a no-op when `availability_model == "continuous"`.
- Manually exercise session mode with e.g. 2 shifts of 8h on Mon–Fri: confirm via printed/logged events that a machine taking on a covering shift fails sooner (lower residual wear-years before next failure) than peers, and that `covering_for` is cleared once the original machine returns to service.
- Frontend: run `npm run dev` in `frontend/`, open the Scenarios page, confirm the new per-shift duration inputs render, sum-validate to ≤24h, and persist/reload correctly through a saved scenario profile.
- Run existing simulation via the API (`/api/simulation`) for both modes and confirm no exceptions and sane availability numbers.
