"""
CQIM v13 — External Fixed-Point Stability Test: M(Σ*) = Σ*
=============================================================

Test authored by an external AI (attempt 3) to evaluate whether the CQIM
engine's converged state σ* is a genuine attractor of the dynamics.

Protocol (from axiomselftestfinal3.json):
  1. Run engine to convergence on the 18-axiom self-encoding. Record σ* and Θ(σ*).
  2. For trials 1-10: perturb σ* with Uniform(-0.05, +0.05) noise, clip to [0,1].
  3. Run engine from each perturbation. Record σ_recovered.
  4. Compute max|σ_recovered - σ*| for each trial.
  5. PASS if all 10 max deviations < 0.02. FAIL if any > 0.10.

This is a fixed-point stability test. It asks: is σ* a genuine attractor?

Author: Nathan Robert Rietmann, Rietmann Intelligence LLC
Test spec: External AI challenge (axiomselftestfinal3.json)
"""

import sys
import os
import json
import numpy as np

# Add parent directory to path for engine import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cqim_v13_engine import (
    load_problem, run_atlas, format_result,
    compute_theta_global, State, Condition, Coupling
)


def rebuild_state_from_spec(spec):
    """Rebuild a fresh State object from the JSON spec."""
    name, state, query = load_problem(spec)
    return name, state, query


def run_from_initial(state, sigma_init, max_passes=100, max_local_iter=500):
    """Run the atlas solver starting from a given initial state.

    We set the initial satisfaction values on the state's conditions
    before calling run_atlas, which reads them as the starting point.
    """
    # Set initial sigma on the state
    for i, cid in enumerate(state.ids):
        state.conditions[cid].satisfaction = float(sigma_init[i])

    result = run_atlas(state, weight_mode="master", verbose=False,
                       max_passes=max_passes, max_local_iter=max_local_iter)
    return result


def run_stability_test(verbose=True):
    """Execute the fixed-point stability test."""

    # ── Load the test spec ──
    test_path = os.path.join(os.path.dirname(__file__), "axiom_self_test_3.json")
    with open(test_path) as f:
        spec = json.load(f)

    print("=" * 70)
    print("  CQIM v13 — EXTERNAL FIXED-POINT STABILITY TEST")
    print("  M(Σ*) = Σ* — Perturbation Recovery")
    print("=" * 70)
    print()
    print(f"  Test spec: {spec['name']}")
    print(f"  Conditions: {len(spec['conditions'])}")
    print(f"  Couplings:  {len(spec['couplings'])}")
    print(f"  Protocol:   Converge → Perturb ×10 → Re-converge → Check deviation")
    print(f"  Pass:       All 10 max deviations < 0.02")
    print(f"  Fail:       Any max deviation > 0.10")
    print()

    # ── Step 1: Run to convergence, record σ* ──
    print("  STEP 1: Converging to σ*...")
    name, state, query = load_problem(spec)
    result_star = run_atlas(state, weight_mode="master", verbose=verbose,
                            max_passes=100, max_local_iter=500)

    sigma_star = result_star["sigma"]
    theta_star = result_star["theta"]
    axiom_ids = sorted(sigma_star.keys(), key=lambda x: int(x[1:]))
    sigma_star_vec = np.array([sigma_star[aid] for aid in axiom_ids])

    print(f"\n  σ* converged:")
    print(f"  {'Axiom':<6} {'Name':<40} {'σ*':>8}")
    print(f"  {'─'*6} {'─'*40} {'─'*8}")
    for aid in axiom_ids:
        cname = spec["conditions"][aid]["name"][:40]
        print(f"  {aid:<6} {cname:<40} {sigma_star[aid]:8.4f}")
    print(f"\n  Θ(σ*) = {theta_star:.6f}")
    print(f"  Monotone: {result_star['monotone']}")
    print(f"  Charts: {result_star['n_charts']}, Passes: {result_star['passes']}")
    print()

    # ── Step 2-4: Perturb and recover ──
    print("  STEP 2-4: Perturbation trials (10 trials, ±0.05 noise)...")
    print()

    np.random.seed(42)  # Reproducible
    n_trials = 10
    perturbation_magnitude = 0.05
    pass_threshold = 0.02
    fail_threshold = 0.10

    deviations = []
    trial_details = []

    for trial in range(n_trials):
        # Generate perturbation
        noise = np.random.uniform(-perturbation_magnitude, perturbation_magnitude,
                                  size=len(sigma_star_vec))
        sigma_perturbed = np.clip(sigma_star_vec + noise, 0.0, 1.0)

        # Compute Θ at perturbed point
        name_t, state_t, query_t = load_problem(spec)
        state_t.set_sigma(sigma_perturbed)
        theta_perturbed = compute_theta_global(state_t, sigma_perturbed)

        # Re-converge from perturbed state
        # We need to reload a fresh state and set initial conditions
        name_r, state_r, query_r = load_problem(spec)
        for i, cid in enumerate(state_r.ids):
            state_r.conditions[cid].satisfaction = float(sigma_perturbed[i])

        result_r = run_atlas(state_r, weight_mode="master", verbose=False,
                             max_passes=100, max_local_iter=500)

        sigma_recovered = np.array([result_r["sigma"][aid] for aid in axiom_ids])
        theta_recovered = result_r["theta"]

        # Compute deviation
        diff = np.abs(sigma_recovered - sigma_star_vec)
        max_dev = float(np.max(diff))
        mean_dev = float(np.mean(diff))
        worst_axiom = axiom_ids[np.argmax(diff)]

        deviations.append(max_dev)
        trial_details.append({
            "trial": trial + 1,
            "max_dev": max_dev,
            "mean_dev": mean_dev,
            "worst_axiom": worst_axiom,
            "theta_perturbed": theta_perturbed,
            "theta_recovered": theta_recovered,
            "monotone": result_r["monotone"],
        })

        status = "✓" if max_dev < pass_threshold else ("✗" if max_dev > fail_threshold else "~")
        print(f"  Trial {trial+1:2d}: max_dev={max_dev:.6f}  mean_dev={mean_dev:.6f}  "
              f"worst={worst_axiom}  Θ_pert={theta_perturbed:.4f}→Θ_rec={theta_recovered:.4f}  "
              f"mono={result_r['monotone']}  [{status}]")

    print()

    # ── Step 5: Verdict ──
    print("  " + "=" * 60)
    print("  STEP 5: RESULTS")
    print("  " + "=" * 60)
    print()

    all_pass = all(d < pass_threshold for d in deviations)
    any_fail = any(d > fail_threshold for d in deviations)
    max_overall = max(deviations)
    mean_overall = np.mean(deviations)

    print(f"  Max deviation across all trials:  {max_overall:.6f}")
    print(f"  Mean deviation across all trials: {mean_overall:.6f}")
    print(f"  Θ(σ*):                           {theta_star:.6f}")
    print()

    print(f"  Per-trial deviations:")
    for td in trial_details:
        status = "PASS" if td["max_dev"] < pass_threshold else (
            "FAIL" if td["max_dev"] > fail_threshold else "PARTIAL")
        print(f"    Trial {td['trial']:2d}: {td['max_dev']:.6f} → {status}")

    print()

    if all_pass:
        verdict = "PASS — σ* is a stable fixed point. All perturbations recovered within 0.02."
        verdict_code = "PASS"
    elif any_fail:
        verdict = "FAIL — σ* is not a stable fixed point. At least one deviation > 0.10."
        verdict_code = "FAIL"
    else:
        verdict = "PARTIAL — Some deviations between 0.02 and 0.10."
        verdict_code = "PARTIAL"

    print(f"  VERDICT: {verdict}")
    print(f"  Threshold: max_dev < 0.02 = PASS, max_dev > 0.10 = FAIL")
    print()

    # ── Per-axiom recovery analysis ──
    print("  " + "─" * 60)
    print("  PER-AXIOM RECOVERY ANALYSIS (mean |σ_recovered - σ*| across 10 trials)")
    print("  " + "─" * 60)

    # Collect all recovered sigmas
    all_recovered = []
    np.random.seed(42)  # Reset seed for reproducibility
    for trial in range(n_trials):
        noise = np.random.uniform(-perturbation_magnitude, perturbation_magnitude,
                                  size=len(sigma_star_vec))
        sigma_perturbed = np.clip(sigma_star_vec + noise, 0.0, 1.0)
        name_r, state_r, query_r = load_problem(spec)
        for i, cid in enumerate(state_r.ids):
            state_r.conditions[cid].satisfaction = float(sigma_perturbed[i])
        result_r = run_atlas(state_r, weight_mode="master", verbose=False,
                             max_passes=100, max_local_iter=500)
        recovered = np.array([result_r["sigma"][aid] for aid in axiom_ids])
        all_recovered.append(recovered)

    all_recovered = np.array(all_recovered)
    mean_per_axiom = np.mean(np.abs(all_recovered - sigma_star_vec), axis=0)
    max_per_axiom = np.max(np.abs(all_recovered - sigma_star_vec), axis=0)

    print(f"\n  {'Axiom':<6} {'Name':<35} {'σ*':>8} {'Mean Dev':>10} {'Max Dev':>10}")
    print(f"  {'─'*6} {'─'*35} {'─'*8} {'─'*10} {'─'*10}")
    for j, aid in enumerate(axiom_ids):
        cname = spec["conditions"][aid]["name"][:35]
        print(f"  {aid:<6} {cname:<35} {sigma_star_vec[j]:8.4f} "
              f"{mean_per_axiom[j]:10.6f} {max_per_axiom[j]:10.6f}")

    print()
    print("=" * 70)
    print(f"  FINAL: {verdict_code}")
    print(f"  Max deviation: {max_overall:.6f}  (threshold: < 0.02)")
    print("=" * 70)

    return {
        "verdict": verdict_code,
        "max_deviation": max_overall,
        "mean_deviation": mean_overall,
        "deviations": deviations,
        "sigma_star": sigma_star,
        "theta_star": theta_star,
        "trial_details": trial_details,
    }


if __name__ == "__main__":
    results = run_stability_test(verbose=True)
