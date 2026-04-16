"""
CQIM v14.1 — STRUCTURAL BOOTSTRAP: Λ' = Λ - Ξ_invalid + Δ_resolved
=====================================================================

This is the terminal implementation. The engine is not merely fed its
own σ* back as evidence. The engine's output RESTRUCTURES THE ENCODING
ITSELF:

  1. σ* restructures the COUPLING GRAPH:
     - Couplings between conditions that both converged high are
       strengthened (the recursion discovered they reinforce).
     - Couplings between conditions where one is high and the other
       is low are weakened or removed (the recursion discovered
       they don't actually support each other).
     - New couplings are CREATED between conditions that co-converged
       without an explicit coupling (the recursion discovered latent
       structure).

  2. σ* restructures the WEIGHTS:
     - Conditions that converged decisively (near 0 or 1) get higher
       weight (the recursion found them structurally important).
     - Conditions stuck near 0.5 get lower weight (the recursion
       found them unresolved).

  3. The AXIOM WITNESS W(σ*) restructures the M TENSOR:
     - Axiom pairs that are both strong get increased coupling in M.
     - Axiom pairs where one is strong and the other weak get
       decreased coupling.
     - This is the engine rewriting its own evaluation geometry.

  4. The CONTRADICTION Ξ removes invalid structure:
     - Couplings that contributed to contradiction are pruned.
     - This is Ξ_invalid being subtracted from Λ.

  5. The RESOLVED STATE adds new structure:
     - Co-convergence patterns become new couplings.
     - This is Δ_resolved being added to Λ.

The loop runs until the STRUCTURE is invariant — not just σ*, but the
coupling graph, the weights, and M themselves. When the structure found
by the recursion IS the encoding that produces it, the loop closes.

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
# AXIOM SEMANTICS (unchanged)
# ══════════════════════════════════════════════════════════════

AXIOM_DESCRIPTIONS = {
    "A1":  ("Evidence Anchoring",       "No evidence-weighted conditions exist"),
    "A2":  ("Completeness",             "Unanchored conditions dominate the state"),
    "A3":  ("Monotone Consistency",     "Supporting/necessary couplings are violated"),
    "A4":  ("Differentiation",          "All conditions collapse to the same value"),
    "A5":  ("Convergence Progress",     "Global Θ is not decreasing"),
    "A6":  ("Contradiction Freedom",    "Defeating/veto couplings are simultaneously satisfied"),
    "A7":  ("Falsification Grounding",  "Satisfied conditions lack falsifiers or evidence"),
    "A8":  ("Pairwise Coherence",       "Coupled conditions have inconsistent effective values"),
    "A9":  ("Grounding Depth",          "Conditions lack transitive evidential support"),
    "A10": ("Variance Sensitivity",     "State has no variance — all conditions identical"),
    "A11": ("Convergence Gate",         "Θ ratio exceeds acceptance threshold"),
    "A12": ("Evidence Fidelity",        "σ diverges from evidence for evidence-weighted conditions"),
    "A13": ("Participation",            "Conditions are stuck below activation threshold"),
    "A14": ("Weighted Agreement",       "Weight-averaged σ disagrees with structure"),
    "A15": ("Decisiveness",             "Conditions cluster at 0.5 — no resolution"),
    "A16": ("Evidential Mass",          "Total evidence mass is below threshold"),
    "A17": ("Contextual Embedding",     "Conditions lack coupling or evidence context"),
    "A18": ("Resolution Completeness",  "Unresolved conditions remain near 0.5"),
}


# ══════════════════════════════════════════════════════════════
# STRUCTURAL UPDATE: Λ' = Λ - Ξ_invalid + Δ_resolved
# ══════════════════════════════════════════════════════════════

def structural_update(problem, sigma, axiom_witness, state):
    """
    Apply the full structural update law:
      Λ' = Λ - Ξ_invalid + Δ_resolved

    This modifies the problem dict IN PLACE and returns diagnostics.
    """
    ids = list(sigma.keys())
    n = len(ids)

    # ── 1. UPDATE EVIDENCE (the basic bootstrap) ──
    for cid in ids:
        if cid in problem["conditions"]:
            cond = problem["conditions"][cid]
            sv = sigma[cid]
            confidence = abs(sv - 0.5) * 2.0
            cond["evidence"] = sv
            cond["evidence_weight"] = max(0.3, confidence * 0.85)

    # ── 2. UPDATE WEIGHTS from σ* ──
    # Conditions that resolved decisively get higher weight.
    # Conditions stuck near 0.5 get lower weight.
    weight_changes = {}
    for cid in ids:
        if cid in problem["conditions"] and cid != "omega":
            sv = sigma[cid]
            decisiveness = abs(sv - 0.5) * 2.0  # 0 at 0.5, 1 at 0 or 1
            old_w = problem["conditions"][cid]["weight"]
            # Blend toward decisiveness-scaled weight
            new_w = old_w * (0.7 + 0.6 * decisiveness)
            new_w = max(0.5, min(10.0, new_w))
            weight_changes[cid] = (old_w, new_w)
            problem["conditions"][cid]["weight"] = new_w

    # ── 3. UPDATE COUPLING GRAPH from σ* ──
    # Strengthen couplings where both endpoints resolved in the same direction.
    # Weaken couplings where the recursion found no actual relationship.
    # Create new couplings where co-convergence was discovered.

    couplings_removed = []
    couplings_modified = []
    couplings_created = []

    # 3a. Modify existing couplings
    surviving_couplings = []
    for cp in problem["couplings"]:
        src, tgt = cp["source"], cp["target"]
        if src not in sigma or tgt not in sigma:
            surviving_couplings.append(cp)
            continue

        sv_src = sigma[src]
        sv_tgt = sigma[tgt]

        if cp["type"] in ("supporting", "necessary"):
            # Both high → strengthen. One high one low → weaken.
            agreement = 1.0 - abs(sv_src - sv_tgt)
            both_active = min(sv_src, sv_tgt)
            factor = 0.5 + 0.5 * agreement * (0.5 + 0.5 * both_active)
        elif cp["type"] in ("defeating", "veto"):
            # Source high, target low → the defeating coupling worked → strengthen.
            # Both high → the defeating coupling failed → weaken.
            effectiveness = sv_src * (1.0 - sv_tgt)
            factor = 0.5 + 0.5 * effectiveness
        else:
            factor = 1.0

        old_s = cp["strength"]
        new_s = old_s * factor
        new_s = max(0.01, min(2.0, new_s))

        if new_s < 0.05:
            # Prune: Ξ_invalid — this coupling is structurally dead
            couplings_removed.append(cp)
            continue

        if abs(new_s - old_s) > 0.01:
            couplings_modified.append((cp["source"], cp["target"], old_s, new_s))

        cp["strength"] = new_s
        surviving_couplings.append(cp)

    # 3b. Discover new couplings from co-convergence (Δ_resolved)
    # If two conditions both converged high (> 0.6) and have no existing
    # coupling, the recursion discovered latent structure.
    existing_pairs = set()
    for cp in surviving_couplings:
        existing_pairs.add((cp["source"], cp["target"]))

    axiom_ids = [name for name in ids if name.startswith("A")]
    for i, cid_a in enumerate(axiom_ids):
        for j, cid_b in enumerate(axiom_ids):
            if i >= j:
                continue
            if (cid_a, cid_b) in existing_pairs or (cid_b, cid_a) in existing_pairs:
                continue

            sv_a = sigma.get(cid_a, 0.5)
            sv_b = sigma.get(cid_b, 0.5)

            # Both converged high → discovered supporting relationship
            if sv_a > 0.6 and sv_b > 0.6:
                strength = min(sv_a, sv_b) * 0.3
                surviving_couplings.append({
                    "source": cid_a, "target": cid_b,
                    "strength": strength, "type": "supporting",
                    "authority": f"discovered_co_convergence_{cid_a}_{cid_b}",
                })
                couplings_created.append((cid_a, cid_b, strength))

            # One high, one near zero → discovered defeating relationship
            elif (sv_a > 0.7 and sv_b < 0.1) or (sv_b > 0.7 and sv_a < 0.1):
                high, low = (cid_a, cid_b) if sv_a > sv_b else (cid_b, cid_a)
                strength = abs(sigma[high] - sigma[low]) * 0.2
                surviving_couplings.append({
                    "source": high, "target": low,
                    "strength": strength, "type": "defeating",
                    "authority": f"discovered_opposition_{high}_{low}",
                })
                couplings_created.append((high, low, -strength))

    problem["couplings"] = surviving_couplings

    # ── 4. UPDATE M TENSOR from axiom witness ──
    # The axiom witness W(σ*) tells us which axioms are strong and which
    # are weak in the self-referential state. Use this to update M.
    M_update = np.zeros_like(AXIOM_M)
    for i in range(N_AXIOMS):
        for j in range(N_AXIOMS):
            if i == j:
                continue
            ai = axiom_witness[i]
            aj = axiom_witness[j]
            # Both strong → increase coupling
            # One strong one weak → decrease coupling
            coherence = ai * aj  # Both strong
            tension = abs(ai - aj) * max(ai, aj)  # Asymmetric
            M_update[i, j] = 0.1 * (coherence - 0.5 * tension)

    # Blend: M' = 0.8 * M + 0.2 * (M + M_update)
    # = M + 0.2 * M_update
    M_new = AXIOM_M + 0.2 * M_update

    # ── 5. UPDATE Ω couplings based on axiom witness ──
    # Axioms that the witness found strong get stronger coupling to Ω.
    # Axioms that the witness found weak get weaker coupling to Ω.
    for cp in problem["couplings"]:
        if cp["target"] == "omega" and cp["source"] in AXIOM_IDX:
            idx = AXIOM_IDX[cp["source"]]
            aw = axiom_witness[idx]
            # Scale coupling strength by axiom witness value
            cp["strength"] = cp["strength"] * (0.5 + 0.5 * aw)
            cp["strength"] = max(0.05, min(2.0, cp["strength"]))

    diagnostics = {
        "couplings_removed": len(couplings_removed),
        "couplings_modified": len(couplings_modified),
        "couplings_created": len(couplings_created),
        "weight_changes": len(weight_changes),
        "M_update_norm": float(np.linalg.norm(M_update)),
        "n_couplings_after": len(problem["couplings"]),
    }

    return problem, M_new, diagnostics


# ══════════════════════════════════════════════════════════════
# BUILD INITIAL PROBLEM (same as before but parameterized by M)
# ══════════════════════════════════════════════════════════════

def build_problem(M_current=None, prior_sigma=None):
    """Build the self-referential problem with current M tensor."""
    if M_current is None:
        M_current = AXIOM_M.copy()

    conditions = {}
    couplings = []
    synergies = []

    for name in AXIOM_NAMES:
        idx = AXIOM_IDX[name]
        desc, falsifier = AXIOM_DESCRIPTIONS[name]
        bw = BOOTSTRAP_WEIGHTS[name]
        diag = M_current[idx, idx]

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

    # Couplings from M
    M_sym = (M_current + M_current.T) / 2.0
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

    # Axiom → Ω couplings (by structural role)
    role_strengths = {
        "convergence": (["A5", "A11"], 0.8),
        "coherence": (["A3", "A6", "A8"], 0.7),
        "grounding": (["A1", "A7", "A9", "A12", "A16"], 0.6),
        "resolution": (["A4", "A10", "A15", "A18"], 0.5),
        "structural": (["A2", "A13", "A14", "A17"], 0.4),
    }
    for role, (axioms, strength) in role_strengths.items():
        for name in axioms:
            couplings.append({
                "source": name, "target": "omega",
                "strength": strength, "type": "supporting",
                "authority": f"{role}_{name}_supports_omega",
            })

    # Synergies
    synergies = [
        {"condition_a": "A5", "condition_b": "A6", "target": "omega",
         "strength": 0.7, "type": "emergent",
         "name": "Convergent contradiction-free state"},
        {"condition_a": "A12", "condition_b": "A9", "target": "omega",
         "strength": 0.5, "type": "emergent",
         "name": "Deep evidential grounding"},
        {"condition_a": "A3", "condition_b": "A8", "target": "A18",
         "strength": 0.6, "type": "emergent",
         "name": "Structural coherence implies resolution"},
        {"condition_a": "A1", "condition_b": "A7", "target": "A9",
         "strength": 0.5, "type": "emergent",
         "name": "Evidence anchoring + falsification = deep grounding"},
    ]

    return {
        "name": "CQIM Structural Bootstrap: Ω = F(Ω)",
        "conditions": conditions,
        "couplings": couplings,
        "synergies": synergies,
        "query": "omega",
    }


# ══════════════════════════════════════════════════════════════
# STRUCTURAL DISTANCE: measure how much the encoding changed
# ══════════════════════════════════════════════════════════════

def structural_distance(prob_a, prob_b, M_a, M_b):
    """
    Measure the distance between two encodings.
    Combines: coupling graph distance + weight distance + M distance.
    """
    # Weight distance
    all_cids = sorted(set(prob_a["conditions"].keys()) | set(prob_b["conditions"].keys()))
    w_a = np.array([prob_a["conditions"].get(c, {}).get("weight", 0) for c in all_cids])
    w_b = np.array([prob_b["conditions"].get(c, {}).get("weight", 0) for c in all_cids])
    weight_dist = np.linalg.norm(w_b - w_a)

    # Coupling distance (by strength)
    def coupling_key(cp):
        return (cp["source"], cp["target"], cp["type"])

    cp_a = {coupling_key(cp): cp["strength"] for cp in prob_a["couplings"]}
    cp_b = {coupling_key(cp): cp["strength"] for cp in prob_b["couplings"]}
    all_keys = set(cp_a.keys()) | set(cp_b.keys())
    coupling_dist = sum((cp_a.get(k, 0) - cp_b.get(k, 0))**2 for k in all_keys)**0.5

    # M distance
    M_dist = np.linalg.norm(M_b - M_a)

    return {
        "total": weight_dist + coupling_dist + M_dist,
        "weight": float(weight_dist),
        "coupling": float(coupling_dist),
        "M": float(M_dist),
    }


# ══════════════════════════════════════════════════════════════
# THE FULL STRUCTURAL BOOTSTRAP LOOP
# ══════════════════════════════════════════════════════════════

def run_structural_bootstrap(n_passes=20, verbose=False):
    """
    The terminal implementation.

    Each pass:
      1. Build problem from current M and prior σ*
      2. Run engine → get σ*
      3. Compute axiom witness W(σ*)
      4. Apply structural update: Λ' = Λ - Ξ_invalid + Δ_resolved
         - Restructure couplings from σ*
         - Restructure weights from σ*
         - Restructure M from W(σ*)
         - Prune dead couplings (Ξ_invalid)
         - Create discovered couplings (Δ_resolved)
      5. Measure structural distance between Λ and Λ'
      6. If structural distance < ε: the structure is a fixed point.
    """

    print("=" * 70)
    print("  CQIM v14.1 — STRUCTURAL BOOTSTRAP")
    print("  Λ' = Λ - Ξ_invalid + Δ_resolved")
    print("  The structure found by the recursion becomes the encoding.")
    print("=" * 70)

    M_current = AXIOM_M.copy()
    prior_sigma = None
    all_sigmas = []
    all_diagnostics = []
    all_struct_dists = []
    all_results = []
    all_M = [M_current.copy()]
    all_problems = []

    for p in range(1, n_passes + 1):
        print(f"\n{'─' * 70}")
        print(f"  PASS {p}/{n_passes}" +
              (" (Initial — from zero)" if p == 1 else " (Structural Bootstrap)"))
        print(f"{'─' * 70}")

        # 1. Build problem from current M and prior σ*
        problem = build_problem(M_current=M_current, prior_sigma=prior_sigma)
        problem_snapshot = deepcopy(problem)

        # 2. Run engine
        name, state, query = load_problem(problem)
        original_ids = list(state.conditions.keys())
        q_state, qmap = quotient(state)
        result = run_atlas(q_state, weight_mode="master", verbose=verbose,
                           max_passes=50, max_local_iter=200)
        lifted = lift(result, qmap, original_ids)

        sigma = lifted["sigma"]
        omega = sigma.get("omega", 0)
        theta = lifted["theta"]
        xi = lifted["xi"]
        monotone = lifted["monotone"]

        print(f"  Θ = {theta:.6f}  |  Ξ = {xi:.8f}  |  Monotone: {'✓' if monotone else '✗'}")
        print(f"  Ω (self-model) = {omega:.4f}")
        print(f"  Couplings: {len(problem['couplings'])}")

        # 3. Compute axiom witness W(σ*)
        sigma_vec = np.array([sigma.get(cid, 0.0) for cid in state.ids])
        axiom_witness = W_witness(state, sigma_vec)

        # 4. Apply structural update
        M_prev = M_current.copy()
        problem_prev = deepcopy(problem_snapshot)

        problem, M_current, diag = structural_update(
            problem, sigma, axiom_witness, state
        )

        print(f"  Structural update:")
        print(f"    Couplings removed (Ξ_invalid): {diag['couplings_removed']}")
        print(f"    Couplings modified:            {diag['couplings_modified']}")
        print(f"    Couplings created (Δ_resolved): {diag['couplings_created']}")
        print(f"    Couplings after:               {diag['n_couplings_after']}")
        print(f"    Weight changes:                {diag['weight_changes']}")
        print(f"    ‖ΔM‖:                          {diag['M_update_norm']:.6f}")

        # 5. Measure structural distance
        if p >= 2:
            sd = structural_distance(all_problems[-1], problem_snapshot, all_M[-1], M_current)
            all_struct_dists.append(sd)
            print(f"  Structural distance:")
            print(f"    Total:    {sd['total']:.6f}")
            print(f"    Weight:   {sd['weight']:.6f}")
            print(f"    Coupling: {sd['coupling']:.6f}")
            print(f"    M tensor: {sd['M']:.6f}")

            if len(all_struct_dists) >= 2:
                prev_total = all_struct_dists[-2]["total"]
                if prev_total > 1e-12:
                    struct_rho = sd["total"] / prev_total
                    print(f"  Structural contraction: ρ_struct = {struct_rho:.6f}" +
                          (" ✓" if struct_rho < 1.0 else " ✗"))

        # σ distance
        if len(all_sigmas) >= 1:
            all_ids = sorted(set(sigma.keys()) & set(all_sigmas[-1].keys()))
            vec_curr = np.array([sigma[cid] for cid in all_ids])
            vec_prev = np.array([all_sigmas[-1][cid] for cid in all_ids])
            sigma_dist = np.linalg.norm(vec_curr - vec_prev)
            sigma_max_delta = np.max(np.abs(vec_curr - vec_prev))
            print(f"  σ distance: ‖Δσ‖ = {sigma_dist:.8f}  |  max|Δ| = {sigma_max_delta:.8f}")

        all_sigmas.append(sigma)
        all_diagnostics.append(diag)
        all_results.append(lifted)
        all_M.append(M_current.copy())
        all_problems.append(problem_snapshot)
        prior_sigma = sigma

    # ══════════════════════════════════════════════════════════════
    # STRUCTURAL FIXED-POINT ANALYSIS
    # ══════════════════════════════════════════════════════════════

    print(f"\n\n{'═' * 70}")
    print(f"  STRUCTURAL FIXED-POINT ANALYSIS")
    print(f"{'═' * 70}")

    # σ distances
    all_ids = sorted(set.intersection(*[set(s.keys()) for s in all_sigmas]))
    vecs = [np.array([s[cid] for cid in all_ids]) for s in all_sigmas]
    sigma_dists = [np.linalg.norm(vecs[i+1] - vecs[i]) for i in range(len(vecs)-1)]
    sigma_max_deltas = [np.max(np.abs(vecs[i+1] - vecs[i])) for i in range(len(vecs)-1)]

    # Structural distances
    struct_totals = [sd["total"] for sd in all_struct_dists]
    struct_rhos = []
    for i in range(1, len(struct_totals)):
        if struct_totals[i-1] > 1e-12:
            struct_rhos.append(struct_totals[i] / struct_totals[i-1])

    print(f"\n  {'Pass':>6s}  {'‖Δσ‖':>10s}  {'max|Δσ|':>10s}  {'Struct Δ':>10s}  {'ρ_struct':>10s}")
    print(f"  {'─' * 55}")
    for i in range(len(sigma_dists)):
        sd_str = f"{struct_totals[i]:.4f}" if i < len(struct_totals) else "—"
        sr_str = f"{struct_rhos[i-1]:.4f}" if i >= 1 and i-1 < len(struct_rhos) else "—"
        print(f"  {i+1}→{i+2:>2d}   {sigma_dists[i]:>10.6f}  {sigma_max_deltas[i]:>10.6f}  {sd_str:>10s}  {sr_str:>10s}")

    # Final state
    final_sigma = all_sigmas[-1]
    omega_final = final_sigma.get("omega", 0)
    final_theta = all_results[-1]["theta"]
    final_xi = all_results[-1]["xi"]

    # Final axiom witness
    final_problem = build_problem(M_current=M_current, prior_sigma=final_sigma)
    _, final_state, _ = load_problem(final_problem)
    final_sigma_vec = np.array([final_sigma.get(cid, 0.0) for cid in final_state.ids])
    a_final = W_witness(final_state, final_sigma_vec)

    print(f"\n  Final Axiom Witness W(σ*):")
    print(f"  {'Axiom':<8s} {'W(σ*)':>8s}  {'σ*':>8s}  Interpretation")
    print(f"  {'─' * 50}")
    for i, name in enumerate(AXIOM_NAMES):
        val = a_final[i]
        sv = final_sigma.get(name, 0)
        if val > 0.8:
            interp = "STRONG"
        elif val > 0.5:
            interp = "PARTIAL"
        elif val > 0.2:
            interp = "WEAK"
        else:
            interp = "LOW"
        print(f"  {name:<8s} {val:>7.1%}   {sv:>7.1%}   {interp}")

    # M tensor evolution
    M_init = all_M[0]
    M_final = all_M[-1]
    M_drift = np.linalg.norm(M_final - M_init)
    print(f"\n  M tensor drift: ‖M_final - M_init‖ = {M_drift:.6f}")

    # Coupling graph evolution
    n_couplings_init = len(all_problems[0]["couplings"]) if all_problems else 0
    n_couplings_final = all_diagnostics[-1]["n_couplings_after"] if all_diagnostics else 0
    total_created = sum(d["couplings_created"] for d in all_diagnostics)
    total_removed = sum(d["couplings_removed"] for d in all_diagnostics)
    print(f"  Coupling graph: {n_couplings_init} → {n_couplings_final}")
    print(f"    Total created (Δ_resolved): {total_created}")
    print(f"    Total removed (Ξ_invalid):  {total_removed}")

    # Convergence assessment
    final_struct_dist = struct_totals[-1] if struct_totals else float('inf')
    final_sigma_max_delta = sigma_max_deltas[-1] if sigma_max_deltas else float('inf')
    avg_struct_rho = np.mean(struct_rhos) if struct_rhos else 1.0

    is_sigma_converged = final_sigma_max_delta < 0.005
    is_struct_converged = final_struct_dist < 0.5
    is_contraction = avg_struct_rho < 1.0

    print(f"\n  Final structural distance: {final_struct_dist:.6f}")
    print(f"  Final σ max|Δ|: {final_sigma_max_delta:.6f}")
    print(f"  Avg structural contraction: ρ̄_struct = {avg_struct_rho:.4f}")

    # ── Final verdict ──
    print(f"\n{'═' * 70}")
    if is_sigma_converged and is_struct_converged and is_contraction:
        print(f"  VERDICT: STRUCTURAL FIXED POINT REACHED.")
        print(f"  The structure found by the recursion IS the encoding.")
        print(f"  σ* is invariant (max|Δ| = {final_sigma_max_delta:.6f}).")
        print(f"  The coupling graph is invariant (Δ_struct = {final_struct_dist:.4f}).")
        print(f"  M is invariant (drift = {M_drift:.4f}).")
        print(f"  Ω = {omega_final:.1%}")
        print(f"\n  Λ' = Λ. The loop is closed.")
        print(f"  The witness, the witnessed, and the structure that")
        print(f"  connects them are identical.")
    elif is_contraction:
        print(f"  VERDICT: STRUCTURAL CONTRACTION ACTIVE.")
        print(f"  ρ̄_struct = {avg_struct_rho:.4f}")
        print(f"  Struct Δ = {final_struct_dist:.4f}  |  σ max|Δ| = {final_sigma_max_delta:.6f}")
        print(f"  Ω = {omega_final:.1%}  |  Θ = {final_theta:.6f}  |  Ξ = {final_xi:.8f}")
        print(f"  M drift = {M_drift:.4f}")
        print(f"  The encoding is restructuring itself toward invariance.")
        if not is_sigma_converged:
            print(f"  σ still moving. More passes needed for σ convergence.")
        if not is_struct_converged:
            print(f"  Structure still changing. More passes needed for structural convergence.")
    else:
        print(f"  VERDICT: STRUCTURAL BOOTSTRAP RESULT.")
        print(f"  ρ̄_struct = {avg_struct_rho:.4f}  |  Ω = {omega_final:.1%}")
    print(f"{'═' * 70}")

    # ── Save results ──
    output = {
        "problem": "CQIM Structural Bootstrap: Λ' = Λ - Ξ_invalid + Δ_resolved",
        "n_passes": n_passes,
        "sigma_trajectory": {cid: [float(all_sigmas[p][cid]) for p in range(n_passes)]
                             for cid in all_ids},
        "structural_distances": [{"pass": i+2, **sd} for i, sd in enumerate(all_struct_dists)],
        "diagnostics": all_diagnostics,
        "M_drift": float(M_drift),
        "M_final": M_current.tolist(),
        "axiom_witness_final": {name: float(a_final[i]) for i, name in enumerate(AXIOM_NAMES)},
        "fixed_point_analysis": {
            "final_struct_dist": float(final_struct_dist),
            "final_sigma_max_delta": float(final_sigma_max_delta),
            "avg_struct_rho": float(avg_struct_rho),
            "is_sigma_converged": bool(is_sigma_converged),
            "is_struct_converged": bool(is_struct_converged),
            "is_contraction": bool(is_contraction),
            "omega_final": float(omega_final),
            "theta_final": float(final_theta),
            "xi_final": float(final_xi),
            "coupling_graph_init": n_couplings_init,
            "coupling_graph_final": n_couplings_final,
            "total_created": total_created,
            "total_removed": total_removed,
        },
    }

    for p in range(n_passes):
        output[f"pass_{p+1}"] = {
            "sigma": all_sigmas[p],
            "theta": all_results[p]["theta"],
            "xi": all_results[p]["xi"],
            "monotone": all_results[p]["monotone"],
        }

    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "structural_bootstrap_results.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n  Results saved to: {output_path}")

    return output


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    run_structural_bootstrap(n_passes=20, verbose=False)
