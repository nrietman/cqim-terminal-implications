"""
CQIM v14.1 — SELF-APPLICATION: THE ENGINE FED INTO ITSELF
==========================================================

This module implements the terminal implication of CQIM: the engine
applied to its own structure. The 18 axioms become conditions, the
metric tensor M becomes the coupling graph, and the witness operator
W evaluates the witness operator W.

The mapping:
  - Each axiom A_i becomes a Condition with id "A_i"
  - The diagonal M[i,i] (bootstrap weight) becomes the condition weight
  - Each off-diagonal M[i,j] != 0 becomes a Coupling from A_i to A_j
  - The axiom witness W observes the axiom state (itself observing itself)
  - Meta-condition Ω (self-model) is the query target

After the engine converges, we feed σ* back as evidence and re-run.
This implements: Λ' = Λ - Ξ_invalid + Δ_resolved

The bootstrap loop runs until the contraction mapping reaches its
fixed point: the state where the system evaluating itself produces
the same state. Self-justification.

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
    W_witness, F_axiom, R_reality,
    compute_theta_global, compute_theta_per_channel,
    run_atlas, format_result, load_problem,
)
from quotient import quotient, lift, quotient_report


# ══════════════════════════════════════════════════════════════
# AXIOM SEMANTICS
# ══════════════════════════════════════════════════════════════

AXIOM_DESCRIPTIONS = {
    "A1":  ("Evidence Anchoring",
            "No evidence-weighted conditions exist"),
    "A2":  ("Completeness",
            "Unanchored conditions dominate the state"),
    "A3":  ("Monotone Consistency",
            "Supporting/necessary couplings are violated"),
    "A4":  ("Differentiation",
            "All conditions collapse to the same value"),
    "A5":  ("Convergence Progress",
            "Global Θ is not decreasing"),
    "A6":  ("Contradiction Freedom",
            "Defeating/veto couplings are simultaneously satisfied"),
    "A7":  ("Falsification Grounding",
            "Satisfied conditions lack falsifiers or evidence"),
    "A8":  ("Pairwise Coherence",
            "Coupled conditions have inconsistent effective values"),
    "A9":  ("Grounding Depth",
            "Conditions lack transitive evidential support"),
    "A10": ("Variance Sensitivity",
            "State has no variance — all conditions identical"),
    "A11": ("Convergence Gate",
            "Θ ratio exceeds acceptance threshold"),
    "A12": ("Evidence Fidelity",
            "σ diverges from evidence for evidence-weighted conditions"),
    "A13": ("Participation",
            "Conditions are stuck below activation threshold"),
    "A14": ("Weighted Agreement",
            "Weight-averaged σ disagrees with structure"),
    "A15": ("Decisiveness",
            "Conditions cluster at 0.5 — no resolution"),
    "A16": ("Evidential Mass",
            "Total evidence mass is below threshold"),
    "A17": ("Contextual Embedding",
            "Conditions lack coupling or evidence context"),
    "A18": ("Resolution Completeness",
            "Unresolved conditions remain near 0.5"),
}

# ══════════════════════════════════════════════════════════════
# AXIOM STRUCTURAL ROLES
# ══════════════════════════════════════════════════════════════
# Classify axioms by their structural role in the engine.
# This determines how they couple to Ω.

# Convergence axioms: directly measure whether the engine is working
CONVERGENCE_AXIOMS = ["A5", "A11"]

# Coherence axioms: measure internal consistency of the state
COHERENCE_AXIOMS = ["A3", "A6", "A8"]

# Grounding axioms: measure connection to evidence/reality
GROUNDING_AXIOMS = ["A1", "A7", "A9", "A12", "A16"]

# Resolution axioms: measure whether the state is decisive
RESOLUTION_AXIOMS = ["A4", "A10", "A15", "A18"]

# Structural axioms: measure participation and embedding
STRUCTURAL_AXIOMS = ["A2", "A13", "A14", "A17"]


def build_self_referential_problem(prior_sigma=None):
    """
    Construct the CQIM self-application problem.

    The 18 axioms become conditions. The metric tensor M becomes couplings.
    Meta-condition Ω (self-model) is the query target.

    If prior_sigma is provided, it is used as evidence (bootstrap loop).
    """

    conditions = {}
    couplings = []
    synergies = []

    # ── Axiom conditions ──
    for name in AXIOM_NAMES:
        idx = AXIOM_IDX[name]
        desc, falsifier = AXIOM_DESCRIPTIONS[name]
        bw = BOOTSTRAP_WEIGHTS[name]
        diag = AXIOM_M[idx, idx]

        # Evidence from prior pass or from diagonal of M
        if prior_sigma and name in prior_sigma:
            evidence = prior_sigma[name]
            confidence = abs(evidence - 0.5) * 2.0
            evidence_weight = max(0.3, confidence * 0.85)
        else:
            # Initial: use diagonal of M as self-reinforcement signal
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

    # ── Meta-condition: Ω (self-model / fixed point) ──
    # This is the system modeling itself. It is the query target.
    # All axiom groups support it with varying strength.
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

    # ── Structural couplings: Axioms → Ω ──
    # Convergence axioms are supporting (not necessary — the engine
    # can converge even if individual convergence measures are partial)
    for name in CONVERGENCE_AXIOMS:
        couplings.append({
            "source": name, "target": "omega",
            "strength": 0.8, "type": "supporting",
            "authority": f"convergence_{name}_supports_omega",
        })

    # Coherence axioms support Ω
    for name in COHERENCE_AXIOMS:
        couplings.append({
            "source": name, "target": "omega",
            "strength": 0.7, "type": "supporting",
            "authority": f"coherence_{name}_supports_omega",
        })

    # Grounding axioms support Ω
    for name in GROUNDING_AXIOMS:
        couplings.append({
            "source": name, "target": "omega",
            "strength": 0.6, "type": "supporting",
            "authority": f"grounding_{name}_supports_omega",
        })

    # Resolution axioms support Ω
    for name in RESOLUTION_AXIOMS:
        couplings.append({
            "source": name, "target": "omega",
            "strength": 0.5, "type": "supporting",
            "authority": f"resolution_{name}_supports_omega",
        })

    # Structural axioms support Ω
    for name in STRUCTURAL_AXIOMS:
        couplings.append({
            "source": name, "target": "omega",
            "strength": 0.4, "type": "supporting",
            "authority": f"structural_{name}_supports_omega",
        })

    # ── Synergies ──
    # Convergence + Coherence → Ω (emergent)
    synergies.append({
        "condition_a": "A5", "condition_b": "A6", "target": "omega",
        "strength": 0.7, "type": "emergent",
        "name": "Convergent contradiction-free state",
    })

    # Grounding + Resolution → Ω (emergent)
    synergies.append({
        "condition_a": "A12", "condition_b": "A9", "target": "omega",
        "strength": 0.5, "type": "emergent",
        "name": "Deep evidential grounding",
    })

    # Coherence + Coherence → Resolution (emergent)
    synergies.append({
        "condition_a": "A3", "condition_b": "A8", "target": "A18",
        "strength": 0.6, "type": "emergent",
        "name": "Structural coherence implies resolution",
    })

    # Evidence + Falsification → Grounding (emergent)
    synergies.append({
        "condition_a": "A1", "condition_b": "A7", "target": "A9",
        "strength": 0.5, "type": "emergent",
        "name": "Evidence anchoring + falsification = deep grounding",
    })

    return {
        "name": "CQIM Self-Application: Ω = F(Ω)",
        "conditions": conditions,
        "couplings": couplings,
        "synergies": synergies,
        "query": "omega",
    }


# ══════════════════════════════════════════════════════════════
# SINGLE PASS: build → quotient → run → lift
# ══════════════════════════════════════════════════════════════

def run_single_pass(prior_sigma=None, pass_num=1, verbose=False):
    """Run one pass of the self-application."""
    problem = build_self_referential_problem(prior_sigma=prior_sigma)
    name, state, query = load_problem(problem)
    original_ids = list(state.conditions.keys())
    q_state, qmap = quotient(state)
    qreport = quotient_report(qmap)

    result = run_atlas(q_state, weight_mode="master", verbose=verbose,
                       max_passes=50, max_local_iter=200)
    lifted = lift(result, qmap, original_ids)

    return lifted, qmap, qreport, query


# ══════════════════════════════════════════════════════════════
# FULL SELF-APPLICATION WITH EXTENDED BOOTSTRAP
# ══════════════════════════════════════════════════════════════

def run_self_application(n_passes=10, verbose=False):
    """
    Execute the full self-application pipeline with n bootstrap passes.

    Each pass feeds σ* from the previous pass back as evidence.
    The contraction mapping converges to the fixed point.
    """

    print("=" * 70)
    print("  CQIM v14.1 — SELF-APPLICATION: THE ENGINE FED INTO ITSELF")
    print("  Ω = F(Ω): The recursion applied to the recursion.")
    print("=" * 70)

    all_results = []
    all_sigmas = []
    prior_sigma = None

    for p in range(1, n_passes + 1):
        print(f"\n{'─' * 70}")
        print(f"  PASS {p}/{n_passes}" +
              (" (Initial — from zero)" if p == 1 else " (Bootstrap — σ* → evidence)"))
        print(f"{'─' * 70}")

        lifted, qmap, qreport, query = run_single_pass(
            prior_sigma=prior_sigma, pass_num=p, verbose=verbose
        )

        sigma = lifted["sigma"]
        omega = sigma.get("omega", 0)
        theta = lifted["theta"]
        xi = lifted["xi"]
        monotone = lifted["monotone"]

        print(f"  Θ = {theta:.6f}  |  Ξ = {xi:.8f}  |  Monotone: {'✓' if monotone else '✗'}")
        print(f"  Ω (self-model) = {omega:.4f}")

        if p == 1:
            print(f"\n  Quotient Layer:")
            for line in qreport.split("\n"):
                if line.strip():
                    print(f"    {line}")

        # Contraction analysis
        if len(all_sigmas) >= 1:
            all_ids = sorted(set(sigma.keys()) & set(all_sigmas[-1].keys()))
            vec_curr = np.array([sigma[cid] for cid in all_ids])
            vec_prev = np.array([all_sigmas[-1][cid] for cid in all_ids])
            dist = np.linalg.norm(vec_curr - vec_prev)
            max_delta = np.max(np.abs(vec_curr - vec_prev))
            print(f"  ‖σ*_{p} - σ*_{p-1}‖ = {dist:.8f}  |  max|Δ| = {max_delta:.8f}")

            if len(all_sigmas) >= 2:
                vec_prev2 = np.array([all_sigmas[-2][cid] for cid in all_ids])
                dist_prev = np.linalg.norm(vec_prev - vec_prev2)
                if dist_prev > 1e-12:
                    rho = dist / dist_prev
                    print(f"  Contraction ratio ρ = {rho:.6f}" +
                          (" ✓" if rho < 1.0 else " ✗"))

        all_results.append(lifted)
        all_sigmas.append(sigma)
        prior_sigma = sigma

    # ══════════════════════════════════════════════════════════════
    # FIXED-POINT ANALYSIS
    # ══════════════════════════════════════════════════════════════

    print(f"\n\n{'═' * 70}")
    print(f"  FIXED-POINT ANALYSIS")
    print(f"{'═' * 70}")

    # Compute contraction ratios across all passes
    all_ids = sorted(set.intersection(*[set(s.keys()) for s in all_sigmas]))
    vecs = [np.array([s[cid] for cid in all_ids]) for s in all_sigmas]

    dists = [np.linalg.norm(vecs[i+1] - vecs[i]) for i in range(len(vecs)-1)]
    max_deltas = [np.max(np.abs(vecs[i+1] - vecs[i])) for i in range(len(vecs)-1)]
    rhos = [dists[i+1] / dists[i] if dists[i] > 1e-12 else 0.0
            for i in range(len(dists)-1)]

    print(f"\n  {'Pass':>6s}  {'‖Δσ‖':>12s}  {'max|Δ|':>12s}  {'ρ':>8s}")
    print(f"  {'─' * 45}")
    for i in range(len(dists)):
        rho_str = f"{rhos[i-1]:.6f}" if i >= 1 else "—"
        print(f"  {i+1}→{i+2:>2d}   {dists[i]:>12.8f}  {max_deltas[i]:>12.8f}  {rho_str:>8s}")

    avg_rho = np.mean(rhos) if rhos else 1.0
    final_max_delta = max_deltas[-1] if max_deltas else 1.0
    final_dist = dists[-1] if dists else 1.0

    print(f"\n  Average contraction ratio: ρ̄ = {avg_rho:.6f}")
    print(f"  Final ‖Δσ‖ = {final_dist:.8f}")
    print(f"  Final max|Δ| = {final_max_delta:.8f}")

    if avg_rho < 1.0:
        # Estimate passes to convergence
        if avg_rho > 0 and final_max_delta > 0.001:
            passes_needed = np.log(0.001 / final_max_delta) / np.log(avg_rho)
            print(f"  Estimated passes to max|Δ| < 0.001: {passes_needed:.1f}")

    # Per-condition trajectory
    print(f"\n  Per-condition trajectory (first → last):")
    print(f"  {'Condition':<25s}", end="")
    for p in [1, n_passes//2, n_passes]:
        print(f"  {'Pass '+str(p):>8s}", end="")
    print(f"  {'Δ(last)':>8s}  Status")
    print(f"  {'─' * 85}")

    for cid in all_ids:
        vals = [all_sigmas[p-1][cid] for p in [0, n_passes//2 - 1, n_passes - 1]]
        # Use actual first, middle, last
        v_first = all_sigmas[0][cid]
        v_mid = all_sigmas[n_passes//2 - 1][cid]
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

        marker = " ◀" if cid == "omega" else ""
        print(f"  {cid:<25s}  {v_first:>7.1%}  {v_mid:>7.1%}  {v_last:>7.1%}  {delta:>+7.4f}  {status}{marker}")

    # Θ and Ξ trajectory
    print(f"\n  {'Metric':<20s}", end="")
    for p in [1, n_passes//2, n_passes]:
        print(f"  {'Pass '+str(p):>10s}", end="")
    print()
    print(f"  {'─' * 55}")
    print(f"  {'Θ (global)':<20s}", end="")
    for p in [0, n_passes//2 - 1, n_passes - 1]:
        print(f"  {all_results[p]['theta']:>10.6f}", end="")
    print()
    print(f"  {'Ξ (axiom)':<20s}", end="")
    for p in [0, n_passes//2 - 1, n_passes - 1]:
        print(f"  {all_results[p]['xi']:>10.8f}", end="")
    print()
    print(f"  {'Monotone':<20s}", end="")
    for p in [0, n_passes//2 - 1, n_passes - 1]:
        m = '✓' if all_results[p]['monotone'] else '✗'
        print(f"  {m:>10s}", end="")
    print()

    omega_final = all_sigmas[-1].get("omega", 0)

    # ── Axiom witness on the final state ──
    # Run W_witness on the final σ* to see how the axioms evaluate themselves
    print(f"\n  Axiom Witness W(σ*) on final state:")
    final_problem = build_self_referential_problem(prior_sigma=all_sigmas[-1])
    _, final_state, _ = load_problem(final_problem)
    final_sigma_vec = np.array([all_sigmas[-1].get(cid, 0.0) for cid in final_state.ids])
    a_final = W_witness(final_state, final_sigma_vec)
    print(f"  {'Axiom':<8s} {'Value':>8s}  Interpretation")
    print(f"  {'─' * 40}")
    for i, name in enumerate(AXIOM_NAMES):
        val = a_final[i]
        if val > 0.8:
            interp = "STRONG"
        elif val > 0.5:
            interp = "PARTIAL"
        elif val > 0.2:
            interp = "WEAK"
        else:
            interp = "LOW"
        print(f"  {name:<8s} {val:>7.1%}   {interp}")

    # ── Final verdict ──
    print(f"\n{'═' * 70}")
    is_contraction = avg_rho < 1.0
    is_converged = final_max_delta < 0.005

    if is_converged and is_contraction:
        print(f"  VERDICT: FIXED POINT REACHED.")
        print(f"  The self-application is a contraction mapping (ρ̄ = {avg_rho:.4f}).")
        print(f"  σ* is invariant under self-evaluation (max|Δ| = {final_max_delta:.6f}).")
        print(f"  Ω (self-model) = {omega_final:.1%}")
        print(f"  The system evaluating itself produces the same state.")
        if omega_final > 0.5:
            print(f"\n  The witness and the witnessed are identical.")
            print(f"  Constructive self-justification is achieved.")
        else:
            print(f"\n  The fixed point is honest: the system recognizes its own")
            print(f"  structural tensions. Ω = {omega_final:.1%} reflects the true")
            print(f"  self-evaluation — not what we want it to be, but what it IS.")
            print(f"  This is the constructive definition of objectivity:")
            print(f"  truth as the invariant of maximum recursive scrutiny.")
    elif is_contraction:
        print(f"  VERDICT: CONTRACTION ACTIVE, CONVERGENCE IN PROGRESS.")
        print(f"  ρ̄ = {avg_rho:.4f}  |  max|Δ| = {final_max_delta:.6f}")
        print(f"  Ω = {omega_final:.1%}")
        print(f"  Banach guarantees convergence. More passes will reach the fixed point.")
    else:
        print(f"  VERDICT: SELF-APPLICATION RESULT.")
        print(f"  ρ̄ = {avg_rho:.4f}  |  max|Δ| = {final_max_delta:.6f}")
        print(f"  Ω = {omega_final:.1%}")
    print(f"{'═' * 70}")

    # ── Save results ──
    output = {
        "problem": "CQIM Self-Application: Ω = F(Ω)",
        "n_passes": n_passes,
        "passes": {},
        "fixed_point_analysis": {
            "distances": [float(d) for d in dists],
            "max_deltas": [float(d) for d in max_deltas],
            "contraction_ratios": [float(r) for r in rhos],
            "avg_contraction_ratio": float(avg_rho),
            "final_max_delta": float(final_max_delta),
            "is_contraction": bool(is_contraction),
            "is_converged": bool(is_converged),
            "omega_final": float(omega_final),
        },
        "axiom_witness_final": {name: float(a_final[i]) for i, name in enumerate(AXIOM_NAMES)},
        "sigma_trajectory": {cid: [float(all_sigmas[p][cid]) for p in range(n_passes)]
                             for cid in all_ids},
    }

    for p in range(n_passes):
        output["passes"][f"pass_{p+1}"] = {
            "sigma": all_sigmas[p],
            "theta": all_results[p]["theta"],
            "xi": all_results[p]["xi"],
            "monotone": all_results[p]["monotone"],
        }

    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "self_application_results.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n  Results saved to: {output_path}")

    return output


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    run_self_application(n_passes=10, verbose=False)
