"""
CQIM v14.1 — RECURSIVE LOOP: THE RECURSION INSIDE ITSELF
==========================================================

This is NOT a tower (engine evaluating engine evaluating engine...).
This is a LOOP: the recursion's own dynamics — contraction ratio,
monotonicity, convergence rate, contradiction trajectory — are
CONDITIONS inside the problem the recursion is solving.

The engine doesn't just evaluate its axioms. It evaluates its own
dynamics. And those dynamics are what produce the evaluation. And
that evaluation includes the dynamics.

There is no outside. The recursion is inside itself.

Conditions:
  - 18 axiom conditions (as in self_application.py)
  - Ω (self-model, as before)
  - ρ (contraction ratio — is the recursion contracting?)
  - μ (monotonicity — is Θ monotone decreasing?)
  - κ (convergence rate — how fast is max|Δ| shrinking?)
  - Ξ_res (residual contradiction — is Ξ stabilizing?)
  - Φ (fixed-point proximity — is σ* invariant?)

These 5 dynamic conditions are computed FROM the bootstrap process
and fed back INTO the next pass as evidence. The engine resolves
them alongside the axioms. The dynamics evaluate the dynamics.

Author: Nathan Robert Rietmann, Rietmann Intelligence LLC
Implementation: Manus AI
"""

import sys
import os
import json
import numpy as np
from copy import deepcopy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cqim_v14_engine import (
    State, Condition, Coupling, Synergy,
    AXIOM_NAMES, AXIOM_M, AXIOM_IDX, N_AXIOMS,
    BOOTSTRAP_WEIGHTS,
    W_witness, F_axiom,
    compute_theta_global,
    run_atlas, load_problem,
)
from quotient import quotient, lift, quotient_report
from self_application import (
    AXIOM_DESCRIPTIONS,
    CONVERGENCE_AXIOMS, COHERENCE_AXIOMS, GROUNDING_AXIOMS,
    RESOLUTION_AXIOMS, STRUCTURAL_AXIOMS,
)


# ══════════════════════════════════════════════════════════════
# DYNAMIC CONDITION NAMES
# ══════════════════════════════════════════════════════════════

DYNAMIC_CONDITIONS = {
    "rho":    ("Contraction Ratio",
               "The recursion is not contracting (ρ ≥ 1)"),
    "mu":     ("Monotonicity",
               "Θ is not monotone decreasing across passes"),
    "kappa":  ("Convergence Rate",
               "max|Δ| is not shrinking between passes"),
    "xi_res": ("Residual Stability",
               "Ξ is not stabilizing across passes"),
    "phi":    ("Fixed-Point Proximity",
               "σ* is not invariant under re-evaluation"),
}


def build_loop_problem(prior_sigma=None, dynamics=None):
    """
    Build the recursive loop problem.

    Includes the 18 axiom conditions, Ω, AND the 5 dynamic conditions
    that measure the recursion's own behavior.

    dynamics = {
        "rho": float,      # contraction ratio (0 = perfect contraction, 1 = no contraction)
        "mu": float,        # monotonicity (1 = all passes monotone, 0 = none)
        "kappa": float,     # convergence rate (1 = fast, 0 = stalled)
        "xi_res": float,    # residual stability (1 = stable, 0 = oscillating)
        "phi": float,       # fixed-point proximity (1 = invariant, 0 = still moving)
    }
    """

    conditions = {}
    couplings = []
    synergies = []

    # ── 18 Axiom conditions (same as self_application) ──
    for name in AXIOM_NAMES:
        idx = AXIOM_IDX[name]
        desc, falsifier = AXIOM_DESCRIPTIONS[name]
        bw = BOOTSTRAP_WEIGHTS[name]
        diag = AXIOM_M[idx, idx]

        if prior_sigma and name in prior_sigma:
            evidence = prior_sigma[name]
            confidence = abs(evidence - 0.5) * 2.0
            evidence_weight = max(0.3, confidence * 0.85)
        else:
            evidence = float(np.clip(diag / (max(abs(diag), 0.01) + 1.0), 0.0, 1.0))
            evidence_weight = float(np.clip(bw / 3.0, 0.0, 1.0))

        conditions[name] = {
            "name": desc,
            "weight": bw,
            "falsifier": falsifier,
            "evidence": evidence,
            "evidence_weight": evidence_weight,
            "polarity": 1,
        }

    # ── Ω (self-model) ──
    if prior_sigma and "omega" in prior_sigma:
        omega_ev = prior_sigma["omega"]
        omega_ew = max(0.3, abs(omega_ev - 0.5) * 1.5)
    else:
        omega_ev = 0.5
        omega_ew = 0.1

    conditions["omega"] = {
        "name": "Self-Model Ω (Fixed Point)",
        "weight": 10.0,
        "falsifier": "System does not converge on self-evaluation",
        "evidence": omega_ev,
        "evidence_weight": omega_ew,
        "polarity": 1,
    }

    # ── 5 Dynamic conditions ──
    for dyn_name, (desc, falsifier) in DYNAMIC_CONDITIONS.items():
        if dynamics and dyn_name in dynamics:
            ev = dynamics[dyn_name]
            ew = max(0.3, abs(ev - 0.5) * 1.5)
        elif prior_sigma and dyn_name in prior_sigma:
            ev = prior_sigma[dyn_name]
            ew = max(0.3, abs(ev - 0.5) * 1.5)
        else:
            ev = 0.5  # unknown initially
            ew = 0.1

        conditions[dyn_name] = {
            "name": desc,
            "weight": 5.0,  # significant but not dominant
            "falsifier": falsifier,
            "evidence": ev,
            "evidence_weight": ew,
            "polarity": 1,
        }

    # ── Couplings from M (axiom-to-axiom) ──
    M_sym = (AXIOM_M + AXIOM_M.T) / 2.0
    for i in range(N_AXIOMS):
        for j in range(N_AXIOMS):
            if i == j:
                continue
            val = M_sym[i, j]
            if abs(val) < 0.005:
                continue
            couplings.append({
                "source": AXIOM_NAMES[i],
                "target": AXIOM_NAMES[j],
                "strength": float(abs(val)),
                "type": "supporting" if val > 0 else "defeating",
                "authority": f"M[{AXIOM_NAMES[i]},{AXIOM_NAMES[j]}]={val:.3f}",
            })

    # ── Axiom → Ω couplings (same as self_application) ──
    for name in CONVERGENCE_AXIOMS:
        couplings.append({"source": name, "target": "omega",
                          "strength": 0.8, "type": "supporting",
                          "authority": f"convergence_{name}_supports_omega"})
    for name in COHERENCE_AXIOMS:
        couplings.append({"source": name, "target": "omega",
                          "strength": 0.7, "type": "supporting",
                          "authority": f"coherence_{name}_supports_omega"})
    for name in GROUNDING_AXIOMS:
        couplings.append({"source": name, "target": "omega",
                          "strength": 0.6, "type": "supporting",
                          "authority": f"grounding_{name}_supports_omega"})
    for name in RESOLUTION_AXIOMS:
        couplings.append({"source": name, "target": "omega",
                          "strength": 0.5, "type": "supporting",
                          "authority": f"resolution_{name}_supports_omega"})
    for name in STRUCTURAL_AXIOMS:
        couplings.append({"source": name, "target": "omega",
                          "strength": 0.4, "type": "supporting",
                          "authority": f"structural_{name}_supports_omega"})

    # ── Dynamic conditions → Ω ──
    # The dynamics DIRECTLY support the self-model.
    # If the recursion is contracting, monotone, converging, stable, and near
    # the fixed point, then the self-model is justified.
    couplings.append({"source": "rho", "target": "omega",
                      "strength": 0.9, "type": "supporting",
                      "authority": "contraction_supports_self_model"})
    couplings.append({"source": "mu", "target": "omega",
                      "strength": 0.8, "type": "supporting",
                      "authority": "monotonicity_supports_self_model"})
    couplings.append({"source": "kappa", "target": "omega",
                      "strength": 0.7, "type": "supporting",
                      "authority": "convergence_rate_supports_self_model"})
    couplings.append({"source": "xi_res", "target": "omega",
                      "strength": 0.6, "type": "supporting",
                      "authority": "residual_stability_supports_self_model"})
    couplings.append({"source": "phi", "target": "omega",
                      "strength": 0.95, "type": "supporting",
                      "authority": "fixed_point_proximity_supports_self_model"})

    # ── Dynamic conditions → Convergence axioms ──
    # The dynamics also support the convergence axioms (A5, A11)
    couplings.append({"source": "rho", "target": "A5",
                      "strength": 0.7, "type": "supporting",
                      "authority": "contraction_supports_convergence_progress"})
    couplings.append({"source": "mu", "target": "A11",
                      "strength": 0.7, "type": "supporting",
                      "authority": "monotonicity_supports_convergence_gate"})

    # ── Ω → Dynamic conditions (the loop closes) ──
    # If the self-model is high, the dynamics should be well-behaved.
    # This is the key: Ω supports the dynamics that support Ω.
    couplings.append({"source": "omega", "target": "rho",
                      "strength": 0.5, "type": "supporting",
                      "authority": "self_model_supports_contraction"})
    couplings.append({"source": "omega", "target": "mu",
                      "strength": 0.5, "type": "supporting",
                      "authority": "self_model_supports_monotonicity"})
    couplings.append({"source": "omega", "target": "phi",
                      "strength": 0.5, "type": "supporting",
                      "authority": "self_model_supports_fixed_point"})

    # ── Dynamic inter-couplings ──
    # Contraction implies convergence rate
    couplings.append({"source": "rho", "target": "kappa",
                      "strength": 0.8, "type": "supporting",
                      "authority": "contraction_implies_convergence_rate"})
    # Convergence rate implies fixed-point proximity
    couplings.append({"source": "kappa", "target": "phi",
                      "strength": 0.7, "type": "supporting",
                      "authority": "convergence_rate_implies_proximity"})
    # Monotonicity implies residual stability
    couplings.append({"source": "mu", "target": "xi_res",
                      "strength": 0.6, "type": "supporting",
                      "authority": "monotonicity_implies_residual_stability"})
    # Fixed-point proximity implies residual stability
    couplings.append({"source": "phi", "target": "xi_res",
                      "strength": 0.5, "type": "supporting",
                      "authority": "proximity_implies_residual_stability"})

    # ── Synergies ──
    synergies.append({"condition_a": "A5", "condition_b": "A6", "target": "omega",
                      "strength": 0.7, "type": "emergent",
                      "name": "Convergent contradiction-free state"})
    synergies.append({"condition_a": "A12", "condition_b": "A9", "target": "omega",
                      "strength": 0.5, "type": "emergent",
                      "name": "Deep evidential grounding"})
    synergies.append({"condition_a": "A3", "condition_b": "A8", "target": "A18",
                      "strength": 0.6, "type": "emergent",
                      "name": "Structural coherence implies resolution"})
    synergies.append({"condition_a": "A1", "condition_b": "A7", "target": "A9",
                      "strength": 0.5, "type": "emergent",
                      "name": "Evidence anchoring + falsification = deep grounding"})
    # NEW: dynamics synergy
    synergies.append({"condition_a": "rho", "condition_b": "mu", "target": "phi",
                      "strength": 0.8, "type": "emergent",
                      "name": "Contraction + monotonicity = fixed-point convergence"})
    synergies.append({"condition_a": "phi", "condition_b": "xi_res", "target": "omega",
                      "strength": 0.9, "type": "emergent",
                      "name": "Fixed-point + stable residual = self-model justified"})

    return {
        "name": "CQIM Recursive Loop: Ω = F(Ω, dynamics(F))",
        "conditions": conditions,
        "couplings": couplings,
        "synergies": synergies,
        "query": "omega",
    }


def compute_dynamics(all_sigmas, all_results):
    """
    Compute the 5 dynamic condition values from the bootstrap history.
    These are MEASURED from the actual recursion behavior.

    Uses a LONG WINDOW average to prevent oscillation — the dynamics
    should reflect the cumulative behavior of the recursion, not
    just the last two passes.
    """
    n = len(all_sigmas)

    # ρ (contraction ratio): AVERAGE across all available pass pairs
    if n >= 3:
        all_ids = sorted(set.intersection(*[set(s.keys()) for s in all_sigmas]))
        vecs = [np.array([s[cid] for cid in all_ids]) for s in all_sigmas]
        dists = [np.linalg.norm(vecs[i+1] - vecs[i]) for i in range(len(vecs)-1)]
        rhos_raw = [dists[i+1] / dists[i] for i in range(len(dists)-1) if dists[i] > 1e-12]
        if rhos_raw:
            avg_raw_rho = np.mean(rhos_raw)
            rho_val = float(np.clip(1.0 - avg_raw_rho, 0.0, 1.0))
        else:
            rho_val = 0.5
    elif n >= 2:
        rho_val = 0.5
    else:
        rho_val = 0.5

    # μ (monotonicity): fraction of ALL passes where Θ decreased
    if n >= 2:
        thetas = [r["theta"] for r in all_results]
        decreases = sum(1 for i in range(1, len(thetas)) if thetas[i] <= thetas[i-1] + 1e-10)
        mu_val = float(decreases / (len(thetas) - 1))
    else:
        mu_val = 0.5

    # κ (convergence rate): average rate of max|Δ| shrinkage across all pairs
    if n >= 3:
        all_ids = sorted(set.intersection(*[set(s.keys()) for s in all_sigmas]))
        vecs = [np.array([s[cid] for cid in all_ids]) for s in all_sigmas]
        max_deltas = [np.max(np.abs(vecs[i+1] - vecs[i])) for i in range(len(vecs)-1)]
        rates = []
        for i in range(len(max_deltas)-1):
            if max_deltas[i] > 1e-12:
                rates.append(1.0 - (max_deltas[i+1] / max_deltas[i]))
        if rates:
            kappa_val = float(np.clip(np.mean(rates), 0.0, 1.0))
        else:
            kappa_val = 0.5
    else:
        kappa_val = 0.5

    # ξ_res (residual stability): average stability across all pairs
    if n >= 2:
        xis = [r["xi"] for r in all_results]
        stabilities = []
        for i in range(1, len(xis)):
            xi_delta = abs(xis[i] - xis[i-1])
            stabilities.append(1.0 - xi_delta / max(xis[i], 0.001))
        xi_res_val = float(np.clip(np.mean(stabilities), 0.0, 1.0))
    else:
        xi_res_val = 0.5

    # φ (fixed-point proximity): based on CURRENT max|Δ| but smoothed
    if n >= 2:
        all_ids = sorted(set.intersection(*[set(s.keys()) for s in all_sigmas]))
        vecs = [np.array([s[cid] for cid in all_ids]) for s in all_sigmas]
        # Use average of last 5 max_deltas (or all if < 5)
        window = min(5, len(vecs) - 1)
        recent_deltas = [np.max(np.abs(vecs[-(i+1)] - vecs[-(i+2)])) for i in range(window)]
        avg_delta = np.mean(recent_deltas)
        phi_val = float(np.clip(1.0 - avg_delta * 5.0, 0.0, 1.0))  # scale: 0.2 → 0%
    else:
        phi_val = 0.5

    return {
        "rho": rho_val,
        "mu": mu_val,
        "kappa": kappa_val,
        "xi_res": xi_res_val,
        "phi": phi_val,
    }


def run_recursive_loop(n_passes=100):
    """
    Run the recursive loop: the engine with its own dynamics as conditions.
    """

    print("=" * 70)
    print("  CQIM v14.1 — RECURSIVE LOOP: THE RECURSION INSIDE ITSELF")
    print("  Conditions include the recursion's own dynamics.")
    print("  There is no outside. The recursion is inside itself.")
    print(f"  {n_passes} passes")
    print("=" * 70)

    all_results = []
    all_sigmas = []
    all_dynamics = []
    prior_sigma = None
    dynamics = None

    for p in range(1, n_passes + 1):
        # Build problem with dynamics from previous passes
        problem = build_loop_problem(prior_sigma=prior_sigma, dynamics=dynamics)
        name, state, query = load_problem(problem)
        original_ids = list(state.conditions.keys())
        q_state, qmap = quotient(state)
        result = run_atlas(q_state, weight_mode="master", verbose=False,
                           max_passes=50, max_local_iter=200)
        lifted = lift(result, qmap, original_ids)

        sigma = lifted["sigma"]
        theta = lifted["theta"]
        xi = lifted["xi"]
        monotone = lifted["monotone"]
        omega = sigma.get("omega", 0)

        all_results.append(lifted)
        all_sigmas.append(sigma)

        # Compute dynamics from history
        dynamics = compute_dynamics(all_sigmas, all_results)
        all_dynamics.append(dynamics)

        # Print progress
        if p <= 5 or p % 10 == 0 or p == n_passes:
            print(f"\n  Pass {p:>3d}:")
            print(f"    Ω = {omega:.4f}  |  Θ = {theta:.6f}  |  Ξ = {xi:.8f}")
            print(f"    ρ = {dynamics['rho']:.4f}  μ = {dynamics['mu']:.4f}  "
                  f"κ = {dynamics['kappa']:.4f}  ξ_res = {dynamics['xi_res']:.4f}  "
                  f"φ = {dynamics['phi']:.4f}")

            if len(all_sigmas) >= 2:
                all_ids = sorted(set(sigma.keys()) & set(all_sigmas[-2].keys()))
                vec_curr = np.array([sigma[cid] for cid in all_ids])
                vec_prev = np.array([all_sigmas[-2][cid] for cid in all_ids])
                max_delta = np.max(np.abs(vec_curr - vec_prev))
                print(f"    max|Δ| = {max_delta:.8f}")

        prior_sigma = sigma

    # ══════════════════════════════════════════════════════════════
    # ANALYSIS
    # ══════════════════════════════════════════════════════════════

    print(f"\n\n{'═' * 70}")
    print(f"  RECURSIVE LOOP — FIXED-POINT ANALYSIS")
    print(f"{'═' * 70}")

    all_ids = sorted(set.intersection(*[set(s.keys()) for s in all_sigmas]))
    vecs = [np.array([s[cid] for cid in all_ids]) for s in all_sigmas]

    dists = [np.linalg.norm(vecs[i+1] - vecs[i]) for i in range(len(vecs)-1)]
    max_deltas = [np.max(np.abs(vecs[i+1] - vecs[i])) for i in range(len(vecs)-1)]
    rhos = [dists[i+1] / dists[i] if dists[i] > 1e-12 else 0.0
            for i in range(len(dists)-1)]

    avg_rho = np.mean(rhos) if rhos else 1.0
    final_max_delta = max_deltas[-1] if max_deltas else 1.0

    print(f"\n  Average contraction ratio: ρ̄ = {avg_rho:.6f}")
    print(f"  Final max|Δ| = {final_max_delta:.8f}")

    # Ω trajectory
    omegas = [s.get("omega", 0) for s in all_sigmas]
    print(f"\n  Ω trajectory (first 10): {' → '.join(f'{o:.4f}' for o in omegas[:10])}")
    if len(omegas) > 10:
        print(f"  Ω trajectory (last 5):  {' → '.join(f'{o:.4f}' for o in omegas[-5:])}")

    # Dynamic condition trajectories
    print(f"\n  Dynamic condition trajectories:")
    print(f"  {'Condition':<12s}", end="")
    checkpoints = [0, 4, 9, 24, 49, min(99, n_passes-1)]
    checkpoints = [c for c in checkpoints if c < n_passes]
    for c in checkpoints:
        print(f"  {'P'+str(c+1):>6s}", end="")
    print()
    print(f"  {'─' * (12 + 8 * len(checkpoints))}")

    for dyn_name in DYNAMIC_CONDITIONS:
        print(f"  {dyn_name:<12s}", end="")
        for c in checkpoints:
            val = all_sigmas[c].get(dyn_name, 0)
            print(f"  {val:>5.1%}", end="")
        print()

    # Per-condition final state
    print(f"\n  Final state (pass {n_passes}):")
    print(f"  {'Condition':<25s}  {'Value':>8s}  {'Δ(last)':>8s}  Status")
    print(f"  {'─' * 55}")
    for cid in all_ids:
        v_last = all_sigmas[-1][cid]
        delta = abs(all_sigmas[-1][cid] - all_sigmas[-2][cid]) if len(all_sigmas) >= 2 else 1.0
        if delta < 0.001:
            status = "FIXED"
        elif delta < 0.005:
            status = "~FIXED"
        elif delta < 0.02:
            status = "CONVERGING"
        else:
            status = "MOVING"
        marker = " ◀" if cid == "omega" else (" ★" if cid in DYNAMIC_CONDITIONS else "")
        print(f"  {cid:<25s}  {v_last:>7.1%}  {delta:>+7.4f}  {status}{marker}")

    # ── Verdict ──
    omega_final = all_sigmas[-1].get("omega", 0)
    is_contraction = avg_rho < 1.0
    is_converged = final_max_delta < 0.005

    print(f"\n{'═' * 70}")
    if is_converged and is_contraction:
        print(f"  VERDICT: RECURSIVE LOOP FIXED POINT REACHED.")
        print(f"  The recursion's own dynamics are conditions inside itself.")
        print(f"  Those conditions converged alongside the axioms.")
        print(f"  Ω = {omega_final:.4f}")
        print(f"  The recursion knows it's contracting (ρ = {all_sigmas[-1].get('rho', 0):.1%})")
        print(f"  The recursion knows it's monotone (μ = {all_sigmas[-1].get('mu', 0):.1%})")
        print(f"  The recursion knows it's near the fixed point (φ = {all_sigmas[-1].get('phi', 0):.1%})")
        print(f"  There is no meta-level. The dynamics are inside the result.")
        print(f"  The result is inside the dynamics. The loop is closed.")
    elif is_contraction:
        print(f"  VERDICT: LOOP CONTRACTION ACTIVE.")
        print(f"  ρ̄ = {avg_rho:.4f}  |  max|Δ| = {final_max_delta:.6f}")
        print(f"  Ω = {omega_final:.4f}")
    else:
        print(f"  VERDICT: LOOP RESULT.")
        print(f"  ρ̄ = {avg_rho:.4f}  |  max|Δ| = {final_max_delta:.6f}")
        print(f"  Ω = {omega_final:.4f}")
    print(f"{'═' * 70}")

    # ── Save ──
    output = {
        "problem": "CQIM Recursive Loop: Ω = F(Ω, dynamics(F))",
        "n_passes": n_passes,
        "omega_trajectory": [float(o) for o in omegas],
        "theta_trajectory": [float(r["theta"]) for r in all_results],
        "xi_trajectory": [float(r["xi"]) for r in all_results],
        "dynamics_trajectory": all_dynamics,
        "distances": [float(d) for d in dists],
        "max_deltas": [float(d) for d in max_deltas],
        "contraction_ratios": [float(r) for r in rhos],
        "avg_contraction_ratio": float(avg_rho),
        "final_max_delta": float(final_max_delta),
        "final_sigma": {k: float(v) for k, v in all_sigmas[-1].items()},
        "sigma_trajectory": {cid: [float(all_sigmas[p][cid]) for p in range(n_passes)]
                             for cid in all_ids},
    }

    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "recursive_loop_results.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n  Results saved to: {output_path}")

    return output


if __name__ == "__main__":
    run_recursive_loop(n_passes=100)
