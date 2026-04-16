"""
CQIM v14.1 — META-RECURSION: THE SELF-APPLICATION RUN ON ITSELF
================================================================

Level 0: The engine evaluates a domain problem.
Level 1: The engine evaluates itself (self_application.py → Ω = 20%).
Level 2: The engine evaluates the result of evaluating itself.
Level N: The engine evaluates the result of Level N-1.

At each meta-level, the *converged σ** from the previous level becomes
the *structure* of the next level's problem. Not just the evidence —
the conditions, weights, and couplings are derived from the previous
level's output.

The question: does the meta-recursion converge? Is there a meta-fixed
point where engine(engine(...(engine(self))...)) = engine(self)?

If yes: the recursion is not just self-consistent at one level —
it is self-consistent at ALL levels. The meta-level collapses.

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
    build_self_referential_problem,
    run_single_pass,
    AXIOM_DESCRIPTIONS,
    CONVERGENCE_AXIOMS, COHERENCE_AXIOMS, GROUNDING_AXIOMS,
    RESOLUTION_AXIOMS, STRUCTURAL_AXIOMS,
)


def run_level_1(n_inner_passes=100):
    """
    Run Level 1: the standard self-application bootstrap.
    Returns the fully converged σ* and all diagnostics.
    """
    print("=" * 70)
    print("  META-LEVEL 1: Standard self-application (100 bootstrap passes)")
    print("=" * 70)

    prior_sigma = None
    all_sigmas = []
    all_results = []

    for p in range(1, n_inner_passes + 1):
        lifted, qmap, qreport, query = run_single_pass(
            prior_sigma=prior_sigma, pass_num=p, verbose=False
        )
        sigma = lifted["sigma"]
        all_sigmas.append(sigma)
        all_results.append(lifted)
        prior_sigma = sigma

        if p % 25 == 0 or p == 1:
            omega = sigma.get("omega", 0)
            print(f"  Pass {p:>3d}: Ω = {omega:.4f}, Θ = {lifted['theta']:.6f}")

    final_sigma = all_sigmas[-1]
    final_omega = final_sigma.get("omega", 0)
    final_theta = all_results[-1]["theta"]
    final_xi = all_results[-1]["xi"]

    print(f"\n  Level 1 converged: Ω = {final_omega:.4f}, Θ = {final_theta:.6f}, Ξ = {final_xi:.8f}")
    return final_sigma, all_results[-1]


def build_meta_problem(level_sigma, meta_level):
    """
    Build a meta-level problem from the previous level's converged σ*.

    The previous level's σ* tells us what each axiom's value IS when the
    engine evaluates itself. Now we ask: what does the engine say about
    THAT result?

    Each condition in the meta-problem represents the previous level's
    assessment of an axiom. The evidence is the actual σ* value. The
    weight reflects how strongly that value was established (distance
    from 0.5 = certainty).

    The couplings come from the SAME M tensor — the axiom relationships
    don't change. But the evidence is now the output of the previous level.
    """

    conditions = {}
    couplings = []
    synergies = []

    for name in AXIOM_NAMES:
        idx = AXIOM_IDX[name]
        desc, falsifier = AXIOM_DESCRIPTIONS[name]
        bw = BOOTSTRAP_WEIGHTS[name]

        # Evidence IS the previous level's converged value
        prev_val = level_sigma.get(name, 0.5)
        confidence = abs(prev_val - 0.5) * 2.0
        evidence_weight = max(0.3, confidence * 0.85)

        conditions[name] = {
            "name": f"L{meta_level}: {desc}",
            "weight": bw,
            "falsifier": falsifier,
            "evidence": prev_val,
            "evidence_weight": evidence_weight,
            "polarity": 1,
        }

    # Meta-Ω: the self-model of the self-model
    prev_omega = level_sigma.get("omega", 0.5)
    omega_confidence = abs(prev_omega - 0.5) * 2.0
    omega_ew = max(0.3, omega_confidence * 1.5)

    conditions["omega"] = {
        "name": f"L{meta_level}: Meta-Self-Model Ω^{meta_level}",
        "weight": 10.0,
        "falsifier": f"Level {meta_level} self-evaluation diverges from Level {meta_level-1}",
        "evidence": prev_omega,
        "evidence_weight": omega_ew,
        "polarity": 1,
    }

    # Couplings from M (same structure at every level)
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

    # Axiom → Ω couplings (same structure)
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

    # Synergies (same structure)
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

    return {
        "name": f"CQIM Meta-Recursion Level {meta_level}: Ω^{meta_level} = F(Ω^{meta_level-1})",
        "conditions": conditions,
        "couplings": couplings,
        "synergies": synergies,
        "query": "omega",
    }


def run_meta_level(level_sigma, meta_level, n_inner_passes=50):
    """
    Run one meta-level: build problem from previous σ*, bootstrap to convergence.
    """
    prior_sigma = None
    all_sigmas = []
    all_results = []

    for p in range(1, n_inner_passes + 1):
        # Build the meta-problem with evidence from bootstrap
        if prior_sigma is not None:
            # Inner bootstrap: use this level's evolving σ as evidence
            problem = build_meta_problem(prior_sigma, meta_level)
        else:
            # First inner pass: use previous level's σ* as evidence
            problem = build_meta_problem(level_sigma, meta_level)

        name, state, query = load_problem(problem)
        original_ids = list(state.conditions.keys())
        q_state, qmap = quotient(state)
        result = run_atlas(q_state, weight_mode="master", verbose=False,
                           max_passes=50, max_local_iter=200)
        lifted = lift(result, qmap, original_ids)

        sigma = lifted["sigma"]
        all_sigmas.append(sigma)
        all_results.append(lifted)
        prior_sigma = sigma

    final_sigma = all_sigmas[-1]
    final_result = all_results[-1]
    return final_sigma, final_result, all_sigmas


def run_meta_recursion(n_meta_levels=10, n_inner_passes_l1=100, n_inner_passes=50):
    """
    Run the full meta-recursion:
      Level 1: self-application (100 passes)
      Level 2: engine on Level 1's σ* (50 inner passes)
      Level 3: engine on Level 2's σ* (50 inner passes)
      ...
      Level N: engine on Level N-1's σ* (50 inner passes)
    """

    print("=" * 70)
    print("  CQIM v14.1 — META-RECURSION")
    print("  engine(engine(engine(...(engine(self))...)))")
    print(f"  {n_meta_levels} meta-levels")
    print("=" * 70)

    # Level 1
    l1_sigma, l1_result = run_level_1(n_inner_passes=n_inner_passes_l1)

    meta_sigmas = [l1_sigma]
    meta_results = [l1_result]
    meta_omegas = [l1_sigma.get("omega", 0)]
    meta_thetas = [l1_result["theta"]]
    meta_xis = [l1_result["xi"]]

    # Levels 2..N
    for level in range(2, n_meta_levels + 1):
        print(f"\n{'=' * 70}")
        print(f"  META-LEVEL {level}: engine evaluating Level {level-1}'s result")
        print(f"{'=' * 70}")

        prev_sigma = meta_sigmas[-1]
        level_sigma, level_result, level_trajectory = run_meta_level(
            prev_sigma, meta_level=level, n_inner_passes=n_inner_passes
        )

        omega = level_sigma.get("omega", 0)
        theta = level_result["theta"]
        xi = level_result["xi"]

        meta_sigmas.append(level_sigma)
        meta_results.append(level_result)
        meta_omegas.append(omega)
        meta_thetas.append(theta)
        meta_xis.append(xi)

        # Meta-contraction analysis
        all_ids = sorted(set(level_sigma.keys()) & set(prev_sigma.keys()))
        vec_curr = np.array([level_sigma[cid] for cid in all_ids])
        vec_prev = np.array([prev_sigma[cid] for cid in all_ids])
        meta_dist = np.linalg.norm(vec_curr - vec_prev)
        meta_max_delta = np.max(np.abs(vec_curr - vec_prev))

        print(f"  Ω^{level} = {omega:.6f}")
        print(f"  Θ = {theta:.6f}  |  Ξ = {xi:.8f}")
        print(f"  ‖σ*_L{level} - σ*_L{level-1}‖ = {meta_dist:.8f}")
        print(f"  max|Δ| = {meta_max_delta:.8f}")

        if len(meta_sigmas) >= 3:
            prev2_sigma = meta_sigmas[-3]
            all_ids2 = sorted(set(prev_sigma.keys()) & set(prev2_sigma.keys()))
            vec_p = np.array([prev_sigma[cid] for cid in all_ids2])
            vec_p2 = np.array([prev2_sigma[cid] for cid in all_ids2])
            prev_dist = np.linalg.norm(vec_p - vec_p2)
            if prev_dist > 1e-12:
                meta_rho = meta_dist / prev_dist
                print(f"  Meta-contraction ratio ρ_meta = {meta_rho:.6f}" +
                      (" ✓" if meta_rho < 1.0 else " ✗"))

    # ══════════════════════════════════════════════════════════════
    # META-FIXED-POINT ANALYSIS
    # ══════════════════════════════════════════════════════════════

    print(f"\n\n{'═' * 70}")
    print(f"  META-FIXED-POINT ANALYSIS")
    print(f"{'═' * 70}")

    print(f"\n  {'Level':>6s}  {'Ω':>10s}  {'Θ':>10s}  {'Ξ':>12s}")
    print(f"  {'─' * 45}")
    for i in range(len(meta_omegas)):
        print(f"  {i+1:>6d}  {meta_omegas[i]:>10.6f}  {meta_thetas[i]:>10.6f}  {meta_xis[i]:>12.8f}")

    # Meta-distances
    all_ids = sorted(set.intersection(*[set(s.keys()) for s in meta_sigmas]))
    vecs = [np.array([s[cid] for cid in all_ids]) for s in meta_sigmas]

    meta_dists = [np.linalg.norm(vecs[i+1] - vecs[i]) for i in range(len(vecs)-1)]
    meta_max_deltas = [np.max(np.abs(vecs[i+1] - vecs[i])) for i in range(len(vecs)-1)]
    meta_rhos = [meta_dists[i+1] / meta_dists[i] if meta_dists[i] > 1e-12 else 0.0
                 for i in range(len(meta_dists)-1)]

    print(f"\n  {'Transition':>12s}  {'‖Δσ‖':>12s}  {'max|Δ|':>12s}  {'ρ_meta':>10s}")
    print(f"  {'─' * 52}")
    for i in range(len(meta_dists)):
        rho_str = f"{meta_rhos[i-1]:.6f}" if i >= 1 else "—"
        print(f"  L{i+1}→L{i+2:>2d}    {meta_dists[i]:>12.8f}  {meta_max_deltas[i]:>12.8f}  {rho_str:>10s}")

    avg_meta_rho = np.mean(meta_rhos) if meta_rhos else 1.0

    print(f"\n  Average meta-contraction ratio: ρ̄_meta = {avg_meta_rho:.6f}")
    print(f"  Final meta ‖Δσ‖ = {meta_dists[-1]:.8f}" if meta_dists else "")
    print(f"  Final meta max|Δ| = {meta_max_deltas[-1]:.8f}" if meta_max_deltas else "")

    # Per-condition across meta-levels
    print(f"\n  Per-condition across meta-levels:")
    print(f"  {'Condition':<25s}", end="")
    for lvl in range(1, min(len(meta_sigmas)+1, 6)):
        print(f"  {'L'+str(lvl):>8s}", end="")
    if len(meta_sigmas) > 5:
        print(f"  {'L'+str(len(meta_sigmas)):>8s}", end="")
    print()
    print(f"  {'─' * (25 + 10 * min(len(meta_sigmas), 6))}")

    for cid in all_ids:
        print(f"  {cid:<25s}", end="")
        for lvl in range(min(len(meta_sigmas), 5)):
            print(f"  {meta_sigmas[lvl][cid]:>7.1%}", end="")
        if len(meta_sigmas) > 5:
            print(f"  {meta_sigmas[-1][cid]:>7.1%}", end="")
        marker = " ◀" if cid == "omega" else ""
        print(marker)

    # Omega convergence
    omega_deltas = [abs(meta_omegas[i+1] - meta_omegas[i]) for i in range(len(meta_omegas)-1)]
    print(f"\n  Ω trajectory: {' → '.join(f'{o:.4f}' for o in meta_omegas)}")
    print(f"  Ω deltas:     {' → '.join(f'{d:.6f}' for d in omega_deltas)}")

    # ── Verdict ──
    print(f"\n{'═' * 70}")
    is_meta_contraction = avg_meta_rho < 1.0
    is_meta_converged = meta_max_deltas[-1] < 0.005 if meta_max_deltas else False
    omega_converged = omega_deltas[-1] < 0.001 if omega_deltas else False

    if is_meta_converged and omega_converged:
        print(f"  VERDICT: META-FIXED POINT REACHED.")
        print(f"  The recursion applied to itself applied to itself ... converges.")
        print(f"  Ω^{len(meta_omegas)} = {meta_omegas[-1]:.6f}")
        print(f"  The meta-level collapses. There is no higher level.")
        print(f"  engine(engine(...(engine(self))...)) = engine(self).")
        print(f"  The recursion IS the fixed point at every level simultaneously.")
    elif is_meta_contraction:
        print(f"  VERDICT: META-CONTRACTION ACTIVE.")
        print(f"  ρ̄_meta = {avg_meta_rho:.4f}")
        print(f"  Ω trajectory: {' → '.join(f'{o:.4f}' for o in meta_omegas)}")
        print(f"  The meta-levels are converging. More levels will reach the meta-fixed point.")
    else:
        print(f"  VERDICT: META-RECURSION RESULT.")
        print(f"  ρ̄_meta = {avg_meta_rho:.4f}")
        print(f"  Ω trajectory: {' → '.join(f'{o:.4f}' for o in meta_omegas)}")
    print(f"{'═' * 70}")

    # ── Save ──
    output = {
        "problem": "CQIM Meta-Recursion: engine(engine(...(engine(self))...))",
        "n_meta_levels": n_meta_levels,
        "n_inner_passes_l1": n_inner_passes_l1,
        "n_inner_passes": n_inner_passes,
        "omega_trajectory": [float(o) for o in meta_omegas],
        "theta_trajectory": [float(t) for t in meta_thetas],
        "xi_trajectory": [float(x) for x in meta_xis],
        "meta_distances": [float(d) for d in meta_dists],
        "meta_max_deltas": [float(d) for d in meta_max_deltas],
        "meta_contraction_ratios": [float(r) for r in meta_rhos],
        "avg_meta_contraction": float(avg_meta_rho),
        "sigma_per_level": {f"L{i+1}": {k: float(v) for k, v in meta_sigmas[i].items()}
                            for i in range(len(meta_sigmas))},
    }

    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "meta_recursion_results.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n  Results saved to: {output_path}")

    return output


if __name__ == "__main__":
    run_meta_recursion(n_meta_levels=10, n_inner_passes_l1=100, n_inner_passes=50)
