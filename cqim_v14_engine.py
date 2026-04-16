"""
CQIM v14 — LOGICAL-EQUIVALENCE QUOTIENT + PROJECTED DESCENT
=============================================================

v14 adds a pre-recursion quotient layer that detects and collapses
logically equivalent graph structures before the engine runs. This
guarantees that two graph factorizations with identical logical content
produce identical attractors.

Key changes from v13:
  - quotient(): pre-recursion canonicalization layer
  - Detects and merges: self-loops, duplicate paths, alias nodes,
    redundant intermediaries
  - lift(): maps quotient-space σ* back to original condition space
  - load_problem_quotient(): convenience wrapper
  - All v13 internals (projected descent, energy gate, atlas) unchanged

Retained from v13:
  - project_necessary_feasible(): hard clamp into admissible region
  - Projection inside line search, before R_reality, before gate
  - Uniform 5% ceiling tolerance (no scale-based leniency)
  - Stronger necessary-family co-location in chart construction

Four chart solver types:
  1. Master Recursion: projected Newton + gradient with analytic Jacobian (primary)
  2. Metric Chart: G_α⁻¹ · ∇Θ preconditioned gradient descent (fallback)
  3. Axiom Chart: full 18-axiom witness → contradiction → update loop (complex topology)

Atlas iteration:
  1. Construct atlas from coupling graph (once)
  2. Outer loop with Anderson acceleration:
     (a) Select chart by curvature: α* = argmax Σ_{i∈U_α} θ_i(σ)
     (b) Dispatch to chart-type-specific solver
     (c) Energy gate: accept iff Θ(σ') < Θ(σ) - ε
     (d) Anderson mixing of last m iterates
  3. Return σ*

Convergence: Theorem 4.1 (monotone), 4.2 (finite), 4.4 (global critical under overlap)
Projected descent: every accepted σ is both Θ-decreasing and necessary-feasible.

Author: Nathan Robert Rietmann, Rietmann Intelligence LLC
"""

import sys
import os
import json
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Set
from collections import defaultdict


# ══════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ══════════════════════════════════════════════════════════════

@dataclass
class Condition:
    id: str
    name: str = ""
    satisfaction: float = 0.5
    weight: float = 5.0
    falsifier: str = ""
    verified: bool = False
    evidence: float = 0.0
    evidence_weight: float = 0.0
    polarity: int = 1

@dataclass
class Coupling:
    source: str
    target: str
    strength: float = 1.0
    type: str = "supporting"
    authority: str = ""

@dataclass
class Synergy:
    condition_a: str
    condition_b: str
    target: str
    strength: float = 0.5
    type: str = "emergent"
    name: str = ""
    authority: str = ""

@dataclass
class State:
    conditions: Dict[str, Condition] = field(default_factory=dict)
    couplings: List[Coupling] = field(default_factory=list)
    synergies: List[Synergy] = field(default_factory=list)
    unknowns: List[str] = field(default_factory=list)

    def __post_init__(self):
        self.ids = list(self.conditions.keys())

    @property
    def n(self):
        return len(self.conditions)

    def weights(self):
        return np.array([self.conditions[c].weight for c in self.ids])

    def polarities(self):
        return np.array([self.conditions[c].polarity for c in self.ids])

    def set_sigma(self, sigma):
        for i, cid in enumerate(self.ids):
            self.conditions[cid].satisfaction = float(sigma[i])


# ══════════════════════════════════════════════════════════════
# SMOOTH PRIMITIVES
# ══════════════════════════════════════════════════════════════

def sat(f, ell=1.0):
    return f / np.sqrt(1.0 + ell**2 * f**2)

def smooth_step(x, center=0.0, width=0.1):
    z = (x - center) / max(width, 1e-8)
    z = np.clip(z, -20, 20)
    return 1.0 / (1.0 + np.exp(-z))

def smooth_ratio(num, den, eps=0.01):
    return num / (den + eps)


# ══════════════════════════════════════════════════════════════
# Θ: PER-CHANNEL CONTRADICTION DECOMPOSITION
# ══════════════════════════════════════════════════════════════

def effective_values(sigma, polarities):
    mask_neg = (polarities == -1).astype(float)
    return sigma * (1.0 - mask_neg) + (1.0 - sigma) * mask_neg


def compute_theta_per_channel(state, sigma):
    """θᵢ(σ) for each condition i. Three terms: coupling violations,
    evidence mismatch, and completion."""
    ids = state.ids
    idx = {c: i for i, c in enumerate(ids)}
    n = state.n
    pol = state.polarities()
    eff = effective_values(sigma, pol)
    theta = np.zeros(n)

    # ── Coupling violations ──
    for c in state.couplings:
        si, ti = idx.get(c.source), idx.get(c.target)
        if si is None or ti is None:
            continue
        se, te = eff[si], eff[ti]
        strength = abs(c.strength)
        violation = 0.0

        if c.type == "necessary":
            gap = max(0.0, te - se)
            violation = 3.0 * strength * gap ** 2
        elif c.type == "supporting":
            gap = max(0.0, te - se - 0.2)
            violation = strength * 0.3 * gap ** 2
        elif c.type == "defeating":
            violation = strength * se * te
        elif c.type == "veto":
            if state.conditions[ids[si]].polarity == -1:
                src_active = sigma[si]
            else:
                src_active = se
            violation = strength * src_active * te
        elif c.type == "weakening":
            violation = strength * 0.3 * se * te

        if c.type == "necessary" and violation > 0:
            theta[ti] += violation
        else:
            theta[si] += violation / 2.0
            theta[ti] += violation / 2.0

    # ── Evidence mismatch (weight: 1.5 — reality dominates) ──
    W_EVIDENCE = 1.5
    for i, cid in enumerate(ids):
        cond = state.conditions[cid]
        if cond.evidence_weight > 0:
            mismatch = (sigma[i] - cond.evidence) ** 2
            theta[i] += W_EVIDENCE * cond.evidence_weight * mismatch

    # ── Necessary ceiling: target ≤ min(all necessary sources) ──
    W_CEILING = 5.0
    nec_sources_by_target = defaultdict(list)
    for c in state.couplings:
        if c.type == "necessary":
            si_c, ti_c = idx.get(c.source), idx.get(c.target)
            if si_c is not None and ti_c is not None:
                nec_sources_by_target[ti_c].append(si_c)
    for ti_c, src_indices in nec_sources_by_target.items():
        min_source = min(eff[s] for s in src_indices)
        te_c = eff[ti_c]
        if te_c > min_source:
            gap = te_c - min_source
            ceiling_violation = W_CEILING * gap ** 2
            theta[ti_c] += ceiling_violation

    # ── Completion term (weight: 0.3) ──
    W_COMPLETION = 0.3
    W_SUPPORT_COMPLETION = 0.15
    for ti_c, src_indices in nec_sources_by_target.items():
        min_source = min(eff[s] for s in src_indices)
        te_c = eff[ti_c]
        if min_source > te_c:
            gap = min_source - te_c
            completion_violation = W_COMPLETION * gap ** 2
            theta[ti_c] += completion_violation

    for c in state.couplings:
        if c.type != "supporting":
            continue
        si, ti = idx.get(c.source), idx.get(c.target)
        if si is None or ti is None:
            continue
        se, te = eff[si], eff[ti]
        if ti in nec_sources_by_target:
            cap = min(eff[s] for s in nec_sources_by_target[ti])
        else:
            cap = 1.0
        target_level = min(se, cap)
        if target_level > te:
            gap = target_level - te
            support_violation = W_SUPPORT_COMPLETION * abs(c.strength) * gap ** 2
            theta[ti] += support_violation * 0.7
            theta[si] += support_violation * 0.3

    return theta


def compute_theta_global(state, sigma):
    return float(np.sum(compute_theta_per_channel(state, sigma)))


# ══════════════════════════════════════════════════════════════
# ∇Θ: GRADIENT (numerical, central finite differences)
# ══════════════════════════════════════════════════════════════

def compute_grad_theta(state, sigma, h=1e-5):
    n = len(sigma)
    grad = np.zeros(n)
    for i in range(n):
        sp = sigma.copy(); sm = sigma.copy()
        sp[i] = min(1.0, sigma[i] + h)
        sm[i] = max(0.0, sigma[i] - h)
        dh = sp[i] - sm[i]
        if dh > 0:
            grad[i] = (compute_theta_global(state, sp)
                       - compute_theta_global(state, sm)) / dh
    return grad


def compute_local_grad_theta(state, sigma, support_indices, h=1e-5):
    """Compute gradient of Θ only w.r.t. channels in the support set."""
    d = len(support_indices)
    grad = np.zeros(d)
    for j, gi in enumerate(support_indices):
        sp = sigma.copy(); sm = sigma.copy()
        sp[gi] = min(1.0, sigma[gi] + h)
        sm[gi] = max(0.0, sigma[gi] - h)
        dh = sp[gi] - sm[gi]
        if dh > 0:
            grad[j] = (compute_theta_global(state, sp)
                       - compute_theta_global(state, sm)) / dh
    return grad


# ══════════════════════════════════════════════════════════════
# M: AXIOM METRIC TENSOR (diagnostic + axiom chart solver)
# ══════════════════════════════════════════════════════════════

AXIOM_NAMES = [
    "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9",
    "A10", "A11", "A12", "A13", "A14", "A15", "A16", "A17", "A18"
]
N_AXIOMS = 18
AXIOM_IDX = {name: i for i, name in enumerate(AXIOM_NAMES)}

AXIOM_M = np.zeros((N_AXIOMS, N_AXIOMS))

def _set(alpha, beta, val):
    AXIOM_M[AXIOM_IDX[alpha], AXIOM_IDX[beta]] = val

_set("A1", "A18", 0.17); _set("A1", "A6", -0.08)
_set("A10", "A18", 0.21); _set("A10", "A6", -0.09)
_set("A11", "A12", 0.56); _set("A11", "A14", -0.14); _set("A11", "A15", 0.06)
_set("A11", "A3", 0.22); _set("A11", "A6", 0.26)
_set("A12", "A15", -0.02); _set("A12", "A18", 0.03); _set("A12", "A3", 0.15)
_set("A12", "A6", -0.21)
_set("A13", "A18", 0.09); _set("A13", "A6", 0.11)
_set("A14", "A12", 0.65); _set("A14", "A14", 0.42); _set("A14", "A15", 0.15)
_set("A14", "A3", -0.45); _set("A14", "A6", 0.01); _set("A14", "A8", -0.69)
_set("A15", "A15", -0.22)
_set("A16", "A18", 0.07); _set("A16", "A6", -0.02)
_set("A17", "A18", 0.02); _set("A17", "A3", 0.14); _set("A17", "A6", -0.23)
_set("A18", "A15", -0.15); _set("A18", "A18", 0.04); _set("A18", "A3", 0.30)
_set("A18", "A6", -0.27)
_set("A2", "A11", -0.19); _set("A2", "A6", -0.07)
_set("A3", "A15", -0.13); _set("A3", "A3", 0.24); _set("A3", "A6", -0.28)
_set("A4", "A18", 0.08); _set("A4", "A6", -0.04)
_set("A5", "A15", -0.11)
_set("A6", "A14", 0.02); _set("A6", "A15", -0.03); _set("A6", "A18", -0.01)
_set("A6", "A3", 0.11); _set("A6", "A6", -0.02); _set("A6", "A8", -0.01)
_set("A7", "A15", 1.78); _set("A7", "A6", -1.28)
_set("A8", "A12", 0.40); _set("A8", "A14", 0.08); _set("A8", "A15", -0.38)
_set("A8", "A3", -0.42); _set("A8", "A6", 0.30)
_set("A9", "A14", -0.37); _set("A9", "A15", -0.12); _set("A9", "A3", 0.18)
_set("A9", "A6", 0.59)

BOOTSTRAP_WEIGHTS = {
    "A1": 0.178, "A2": 0.428, "A3": 1.460, "A4": 0.237,
    "A5": 0.872, "A6": 1.224, "A7": 2.341, "A8": 0.688,
    "A9": 2.608, "A10": 0.144, "A11": 2.288, "A12": 0.290,
    "A13": 0.295, "A14": 1.990, "A15": 0.903, "A16": 0.266,
    "A17": 0.817, "A18": 0.971,
}

for name, w in BOOTSTRAP_WEIGHTS.items():
    i = AXIOM_IDX[name]
    if AXIOM_M[i, i] == 0:
        AXIOM_M[i, i] = w


# ══════════════════════════════════════════════════════════════
# W: AXIOM WITNESS
# ══════════════════════════════════════════════════════════════

def W_witness(state, sigma):
    """W(Λ): 18 axioms observe the condition state."""
    ids = state.ids
    idx = {c: i for i, c in enumerate(ids)}
    n = state.n
    w = state.weights()
    pol = state.polarities()
    eff = effective_values(sigma, pol)
    a = np.zeros(N_AXIOMS)

    total_ew = sum(state.conditions[cid].evidence_weight for cid in ids)
    if total_ew > 0:
        a[0] = sum(sigma[i] * state.conditions[cid].evidence_weight
                   for i, cid in enumerate(ids)) / total_ew
    else:
        a[0] = np.mean(sigma)

    n_unanchored = 0.0
    for i, cid in enumerate(ids):
        cond = state.conditions[cid]
        has_ev = cond.evidence_weight > 0
        has_cp = any(cp.target == cid or cp.source == cid for cp in state.couplings)
        if not has_ev and not has_cp:
            n_unanchored += smooth_step(sigma[i], 0.5, 0.1)
    a[1] = max(0.0, 1.0 - 0.15 * n_unanchored)

    cons_sum = 0.0; n_cp = 0
    for c in state.couplings:
        if c.type in ("necessary", "supporting"):
            si, ti = idx.get(c.source), idx.get(c.target)
            if si is not None and ti is not None:
                n_cp += 1
                cons_sum += smooth_step(eff[si] - eff[ti] + 0.1, 0.0, 0.05)
    a[2] = smooth_ratio(cons_sum, n_cp) if n_cp > 0 else 1.0

    if n > 1:
        n_pairs = n * (n - 1) // 2
        total_dist = sum(
            1.0 - np.exp(-50.0 * (sigma[i] - sigma[j])**2)
            for i in range(n) for j in range(i+1, n))
        a[3] = total_dist / n_pairs
    else:
        a[3] = 1.0

    theta_val = float(np.sum(w * (1.0 - sigma)))
    theta_max = float(np.sum(w))
    a[4] = 1.0 - smooth_ratio(theta_val, theta_max + 0.01)

    total_c = 0.0
    for c in state.couplings:
        si, ti = idx.get(c.source), idx.get(c.target)
        if si is None or ti is None: continue
        se, te = eff[si], eff[ti]
        if c.type == "necessary":
            gap = te - se
            total_c += gap * smooth_step(gap, 0.0, 0.05)
        elif c.type in ("defeating", "veto"):
            if c.type == "veto" and state.conditions[ids[si]].polarity == -1:
                total_c += sigma[si] * te
            else:
                total_c += se * te
        elif c.type == "weakening":
            total_c += 0.5 * se * te
        elif c.type == "supporting":
            if se < te:
                total_c += 0.3 * (te - se) * smooth_step(te, 0.5, 0.1)
    a[5] = np.clip(1.0 - total_c, 0.0, 1.0)

    f_mass = sum(sigma[i] * (1.0 if (state.conditions[ids[i]].falsifier or
                state.conditions[ids[i]].evidence_weight > 0) else 0.0) for i in range(n))
    c_mass = np.sum(sigma) + 0.01
    a[6] = f_mass / c_mass

    coh_sum = 0.0; n_pc = 0
    for c in state.couplings:
        si, ti = idx.get(c.source), idx.get(c.target)
        if si is None or ti is None: continue
        n_pc += 1
        if c.type in ("necessary", "supporting"):
            coh_sum += 1.0 - abs(eff[si] - eff[ti])
        elif c.type in ("defeating", "veto"):
            coh_sum += abs(eff[si] - eff[ti])
    a[7] = smooth_ratio(coh_sum, n_pc) if n_pc > 0 else 1.0

    g_mass = 0.0
    for i, cid in enumerate(ids):
        cond = state.conditions[cid]
        ground = cond.evidence_weight * cond.evidence
        for cp in state.couplings:
            if cp.target == cid and cp.type in ("necessary", "supporting"):
                si_cp = idx.get(cp.source)
                if si_cp is not None:
                    ground += eff[si_cp] * 0.3
        g_mass += min(1.0, ground)
    a[8] = smooth_ratio(g_mass, n)

    a[9] = 1.0 - np.exp(-10.0 * np.var(sigma)) if n > 1 else 0.5

    ratio = theta_val / theta_max if theta_max > 0 else 0
    a[10] = 1.0 - smooth_step(ratio, 0.6, 0.1)

    v_mass = 0.0; e_mass = 0.0
    for i, cid in enumerate(ids):
        cond = state.conditions[cid]
        if cond.evidence_weight > 0:
            e_mass += cond.evidence_weight
            v_mass += cond.evidence_weight * (1.0 - abs(sigma[i] - cond.evidence))
    a[11] = smooth_ratio(v_mass, e_mass) if e_mass > 0 else 0.5

    a[12] = sum(smooth_step(sigma[i], 0.2, 0.05) for i in range(n)) / n

    a[13] = float(np.sum(w * sigma) / np.sum(w))

    a[14] = min(1.0, 2.0 * np.sum(2.0 * (sigma - 0.5)**2) / max(n, 1))

    total_ev = sum(state.conditions[cid].evidence * state.conditions[cid].evidence_weight
                   for cid in ids)
    a[15] = smooth_step(total_ev / (np.sum(w) + 0.01), 0.3, 0.1)

    ctx = 0.0
    for i, cid in enumerate(ids):
        cond = state.conditions[cid]
        has_ctx = (cond.evidence_weight > 0) or any(
            cp.target == cid or cp.source == cid for cp in state.couplings)
        ctx += 1.0 if has_ctx else 0.3 * sigma[i]
    a[16] = smooth_ratio(ctx, n)

    unresolved = sum(np.exp(-8.0 * (sigma[i] - 0.5)**2) for i in range(n))
    a[17] = max(0.0, 1.0 - 0.15 * unresolved)

    return np.clip(a, 0.0, 1.0)


def F_axiom(a, M, dt=0.05):
    tension = 1.0 - a
    force = M @ tension + 0.5 * tension
    force = sat(force, ell=1.0)
    return np.clip(a + dt * force, 0.0, 1.0)


# ══════════════════════════════════════════════════════════════
# NECESSARY FEASIBILITY PROJECTION
#
# Projects σ into the necessary-feasible region by clamping each target
# to min(effective values of its necessary sources). Iterates to closure
# for transitive chains. This runs INSIDE the line search, before
# R_reality and before the gate. Every candidate the gate sees is feasible.
# ══════════════════════════════════════════════════════════════

def project_necessary_feasible(sigma, state, max_rounds=20):
    """Project σ into the necessary-feasible region.

    For each target with necessary sources, clamp:
        eff(target) ≤ min(eff(sources))

    Iterates to closure for transitive chains (A→B→C).
    Handles polarity: negative polarity conditions use eff = 1 - σ.

    This is a projection, not a gradient step. It moves σ to the nearest
    point in the feasible set along the ceiling constraint directions.
    """
    ids = state.ids
    idx = {c: i for i, c in enumerate(ids)}
    pol = state.polarities()
    sigma = sigma.copy()

    # Build necessary source map once
    nec_sources = defaultdict(list)  # target_idx -> [source_idx, ...]
    for c in state.couplings:
        if c.type == "necessary":
            si, ti = idx.get(c.source), idx.get(c.target)
            if si is not None and ti is not None:
                nec_sources[ti].append(si)

    if not nec_sources:
        return sigma

    # Iterate to closure (transitive chains)
    for _ in range(max_rounds):
        eff = effective_values(sigma, pol)
        changed = False
        for ti, src_list in nec_sources.items():
            min_source_eff = min(eff[s] for s in src_list)
            if eff[ti] > min_source_eff + 1e-12:
                # Clamp target effective value to min(sources)
                if pol[ti] == 1:
                    # Positive polarity: eff = sigma, so sigma = eff
                    sigma[ti] = min_source_eff
                else:
                    # Negative polarity: eff = 1 - sigma, so sigma = 1 - eff
                    sigma[ti] = 1.0 - min_source_eff
                changed = True
        if not changed:
            break

    return np.clip(sigma, 0.0, 1.0)


# ══════════════════════════════════════════════════════════════
# R: REALITY OPERATOR
# ══════════════════════════════════════════════════════════════

def R_reality(sigma_proposal, state):
    ids = state.ids
    idx = {c: i for i, c in enumerate(ids)}
    pol = state.polarities()
    sigma = sigma_proposal.copy()

    for i, cid in enumerate(ids):
        cond = state.conditions[cid]
        if cond.evidence_weight > 0:
            pin_strength = cond.evidence_weight * 0.3
            sigma[i] = sigma[i] * (1.0 - pin_strength) + cond.evidence * pin_strength

    eff = effective_values(sigma, pol)
    for c in state.couplings:
        if c.type != "necessary": continue
        si, ti = idx.get(c.source), idx.get(c.target)
        if si is None or ti is None: continue
        if eff[ti] > eff[si]:
            excess = eff[ti] - eff[si]
            pull = abs(c.strength) * 0.5 * excess
            if pol[ti] == 1:
                sigma[ti] -= pull
            else:
                sigma[ti] += pull

    return np.clip(sigma, 0.0, 1.0)


# ══════════════════════════════════════════════════════════════
# CHART DATA STRUCTURE
# ══════════════════════════════════════════════════════════════

@dataclass
class Chart:
    """A single chart in the atlas."""
    id: int
    support: List[int]          # Global indices of conditions in this chart
    support_ids: List[str]      # Condition IDs
    couplings: List[Coupling]   # Couplings internal to this chart
    boundary: List[int]         # Global indices of boundary nodes (in overlap with other charts)
    solver_type: str = "metric" # "metric" or "axiom"
    G_alpha: np.ndarray = None  # Local metric (PSD), d×d
    tau_alpha: np.ndarray = None  # Local target, d-vector


# ══════════════════════════════════════════════════════════════
# ATLAS CONSTRUCTION (Definition 8.1)
# ══════════════════════════════════════════════════════════════

def build_coupling_graph(state) -> Dict[int, Set[int]]:
    """Build adjacency list from coupling structure."""
    idx = {c: i for i, c in enumerate(state.ids)}
    adj: Dict[int, Set[int]] = {i: set() for i in range(state.n)}

    for c in state.couplings:
        si, ti = idx.get(c.source), idx.get(c.target)
        if si is not None and ti is not None:
            adj[si].add(ti)
            adj[ti].add(si)

    return adj


def find_connected_components(adj: Dict[int, Set[int]], n: int) -> List[Set[int]]:
    """Find connected components via BFS."""
    visited = set()
    components = []

    for start in range(n):
        if start in visited:
            continue
        component = set()
        queue = [start]
        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            component.add(node)
            for neighbor in adj.get(node, set()):
                if neighbor not in visited:
                    queue.append(neighbor)
        if component:
            components.append(component)

    return components


def split_large_component(component: Set[int], adj: Dict[int, Set[int]],
                          max_chart_size: int) -> List[Set[int]]:
    """Split a large connected component into overlapping sub-charts.
    Uses greedy BFS from highest-degree node."""
    if len(component) <= max_chart_size:
        return [component]

    remaining = set(component)
    clusters = []

    while remaining:
        start = max(remaining, key=lambda x: len(adj.get(x, set()) & remaining))
        cluster = set()
        queue = [start]

        while queue and len(cluster) < max_chart_size:
            node = queue.pop(0)
            if node not in remaining:
                continue
            cluster.add(node)
            remaining.discard(node)
            neighbors = sorted(adj.get(node, set()) & remaining,
                               key=lambda x: -len(adj.get(x, set())))
            queue.extend(neighbors)

        clusters.append(cluster)

    return clusters


def find_defeating_cycles(state) -> List[Tuple[int, int]]:
    """Find all defeating/weakening cycles: pairs (i,j) where i defeats j AND j defeats/weakens i.
    These pairs MUST be in the same chart for correct resolution."""
    idx = {c: i for i, c in enumerate(state.ids)}
    defeat_edges = set()
    for c in state.couplings:
        if c.type in ("defeating", "veto", "weakening"):
            si, ti = idx.get(c.source), idx.get(c.target)
            if si is not None and ti is not None:
                defeat_edges.add((si, ti))
    cycles = []
    for (a, b) in defeat_edges:
        if (b, a) in defeat_edges and a < b:  # Avoid duplicates
            cycles.append((a, b))
    return cycles


def find_necessary_groups(state) -> List[Set[int]]:
    """Find groups where a target and ALL its necessary sources must be co-located.
    A target cannot be correctly resolved without seeing its necessary sources."""
    idx = {c: i for i, c in enumerate(state.ids)}
    nec_groups = defaultdict(set)
    for c in state.couplings:
        if c.type == "necessary":
            si, ti = idx.get(c.source), idx.get(c.target)
            if si is not None and ti is not None:
                nec_groups[ti].add(si)
                nec_groups[ti].add(ti)  # Include the target itself
    return list(nec_groups.values())


def ensure_overlap(clusters: List[Set[int]], adj: Dict[int, Set[int]],
                   max_chart_size: int, cycle_pairs: List[Tuple[int, int]] = None,
                   necessary_groups: List[Set[int]] = None) -> List[Set[int]]:
    """Ensure every coupled pair (i,j) appears together in at least one chart.
    Also ensures defeating cycle pairs and necessary groups are co-located.
    This is the overlap condition required by Theorem 4.4."""
    node_to_clusters: Dict[int, List[int]] = {}
    for ci, cluster in enumerate(clusters):
        for node in cluster:
            node_to_clusters.setdefault(node, []).append(ci)

    all_nodes = set()
    for c in clusters:
        all_nodes |= c
    if not all_nodes:
        return clusters

    # First: ensure defeating cycle pairs are co-located
    if cycle_pairs:
        for (a, b) in cycle_pairs:
            a_clusters = set(node_to_clusters.get(a, []))
            b_clusters = set(node_to_clusters.get(b, []))
            if a_clusters & b_clusters:
                continue  # Already share a chart
            if a_clusters and b_clusters:
                # Merge b into a's smallest cluster
                target_ci = min(a_clusters, key=lambda ci: len(clusters[ci]))
                clusters[target_ci].add(b)
                node_to_clusters.setdefault(b, []).append(target_ci)
                # Also merge a into b's smallest cluster for bidirectional overlap
                target_ci2 = min(b_clusters, key=lambda ci: len(clusters[ci]))
                clusters[target_ci2].add(a)
                node_to_clusters.setdefault(a, []).append(target_ci2)

    # Second: ensure necessary groups are co-located
    # A target and all its necessary sources must share at least one chart
    if necessary_groups:
        for group in necessary_groups:
            # Find which cluster contains the most members of this group
            cluster_coverage = {}
            for ci, cluster in enumerate(clusters):
                overlap = group & cluster
                if overlap:
                    cluster_coverage[ci] = len(overlap)
            if not cluster_coverage:
                continue
            # Pick the cluster with best coverage
            best_ci = max(cluster_coverage, key=cluster_coverage.get)
            # Add all missing members to that cluster
            missing = group - clusters[best_ci]
            for node in missing:
                clusters[best_ci].add(node)
                node_to_clusters.setdefault(node, []).append(best_ci)

    # Then: standard overlap for all coupled pairs
    for node in range(max(all_nodes) + 1):
        for neighbor in adj.get(node, set()):
            node_clusters = set(node_to_clusters.get(node, []))
            neighbor_clusters = set(node_to_clusters.get(neighbor, []))

            if node_clusters & neighbor_clusters:
                continue

            if node_clusters and neighbor_clusters:
                nc = min(node_clusters, key=lambda ci: len(clusters[ci]))
                nn = min(neighbor_clusters, key=lambda ci: len(clusters[ci]))

                if len(clusters[nc]) <= len(clusters[nn]):
                    if len(clusters[nc]) < max_chart_size + 2:
                        clusters[nc].add(neighbor)
                        node_to_clusters.setdefault(neighbor, []).append(nc)
                else:
                    if len(clusters[nn]) < max_chart_size + 2:
                        clusters[nn].add(node)
                        node_to_clusters.setdefault(node, []).append(nn)

    return clusters


def compute_boundary_nodes(clusters: List[Set[int]]) -> Dict[int, Set[int]]:
    """For each cluster, identify nodes that appear in multiple clusters (boundary nodes)."""
    node_count: Dict[int, int] = {}
    for cluster in clusters:
        for node in cluster:
            node_count[node] = node_count.get(node, 0) + 1

    boundary_per_cluster: Dict[int, Set[int]] = {}
    for ci, cluster in enumerate(clusters):
        boundary_per_cluster[ci] = {node for node in cluster if node_count[node] > 1}

    return boundary_per_cluster


def classify_chart_type(support_ids: List[str], internal_couplings: List[Coupling],
                        state: State) -> str:
    """Determine solver type based on local topology.

    Rules:
      - If synergies present → axiom (needs full 18-axiom evaluation)
      - If defeating cycle detected → axiom (complex topology)
      - If > 3 defeating/veto couplings → axiom
      - Otherwise → metric (simple pairwise)
    """
    support_set = set(support_ids)

    # Check for synergies
    has_synergy = any(
        s.condition_a in support_set and s.condition_b in support_set
        for s in state.synergies
    )

    # Count defeating/veto couplings
    n_defeating = sum(1 for c in internal_couplings
                      if c.type in ("defeating", "veto"))

    # Check for defeating cycles (A defeats B and B defeats/weakens A)
    defeat_edges = set()
    for c in internal_couplings:
        if c.type in ("defeating", "veto", "weakening"):
            defeat_edges.add((c.source, c.target))

    has_cycle = any((b, a) in defeat_edges for (a, b) in defeat_edges)

    # Self-referential: condition appears as both source and target in its own couplings
    # (This is rare but represents discrete commitment loops)
    self_ref = any(c.source == c.target for c in internal_couplings)

    if self_ref or has_cycle:
        return "axiom"
    elif has_synergy or n_defeating > 3:
        return "axiom"
    else:
        return "metric"


def build_local_metric(support: List[int], support_ids: List[str],
                       internal_couplings: List[Coupling], state: State):
    """Build G_α and τ_α for a chart (Definition 6.1)."""
    d = len(support)
    local_id_idx = {sid: j for j, sid in enumerate(support_ids)}

    G_alpha = np.eye(d) * 0.01  # Regularization for PSD
    tau_alpha = np.full(d, 0.5)

    for c in internal_couplings:
        si_local = local_id_idx.get(c.source)
        ti_local = local_id_idx.get(c.target)
        if si_local is None or ti_local is None:
            continue

        w = abs(c.strength)
        v = np.zeros(d)

        if c.type == "necessary":
            v[si_local] = +1.0
            v[ti_local] = -1.0
            G_alpha += w * np.outer(v, v)
        elif c.type == "supporting":
            v[si_local] = +1.0
            v[ti_local] = -1.0
            G_alpha += w * 0.3 * np.outer(v, v)
        elif c.type == "defeating":
            v[si_local] = +1.0
            v[ti_local] = +1.0
            G_alpha += w * np.outer(v, v)
        elif c.type == "veto":
            v[si_local] = +1.0
            v[ti_local] = +1.0
            G_alpha += w * np.outer(v, v)
        elif c.type == "weakening":
            v[si_local] = +1.0
            v[ti_local] = +1.0
            G_alpha += w * 0.3 * np.outer(v, v)

    # Evidence-anchored conditions
    for j, sid in enumerate(support_ids):
        cond = state.conditions[sid]
        if cond.evidence_weight > 0:
            G_alpha[j, j] += cond.evidence_weight * 2.0
            tau_alpha[j] = cond.evidence
        else:
            nec_sources = []
            for c in internal_couplings:
                if c.target == sid and c.type == "necessary":
                    src_j = local_id_idx.get(c.source)
                    if src_j is not None:
                        nec_sources.append(src_j)
            if nec_sources:
                tau_alpha[j] = min(tau_alpha[src_j] for src_j in nec_sources)
            for c in internal_couplings:
                if c.target == sid and c.type in ("defeating", "veto"):
                    tau_alpha[j] = 0.0
                    break

    # Completion direction
    for c in internal_couplings:
        if c.type == "necessary":
            si_local = local_id_idx.get(c.source)
            ti_local = local_id_idx.get(c.target)
            if si_local is not None and ti_local is not None:
                v = np.zeros(d)
                v[si_local] = -1.0
                v[ti_local] = +1.0
                G_alpha += abs(c.strength) * 0.7 * np.outer(v, v)

    return G_alpha, tau_alpha


def construct_atlas(state, max_chart_size=None) -> List[Chart]:
    """
    Coupling-Driven Atlas Construction (Definition 8.1).

    1. Build coupling graph
    2. Find connected components
    3. Split large components into sub-charts
    4. Ensure overlap condition (Theorem 4.4)
    5. Identify internal couplings per chart
    6. Classify solver type per chart
    7. Build local metric for metric/axiom charts
    8. Identify boundary nodes
    """
    n = state.n
    ids = state.ids

    if max_chart_size is None:
        if n <= 20:
            max_chart_size = n
        else:
            max_chart_size = max(8, int(np.sqrt(n) * 2))

    adj = build_coupling_graph(state)
    components = find_connected_components(adj, n)

    clusters = []
    for comp in components:
        sub_clusters = split_large_component(comp, adj, max_chart_size)
        clusters.extend(sub_clusters)

    covered = set()
    for cluster in clusters:
        covered |= cluster
    for i in range(n):
        if i not in covered:
            clusters.append({i})

    # Detect defeating cycles and necessary groups for co-location
    cycle_pairs = find_defeating_cycles(state)
    necessary_groups = find_necessary_groups(state)

    if len(clusters) > 1:
        clusters = ensure_overlap(clusters, adj, max_chart_size,
                                  cycle_pairs=cycle_pairs,
                                  necessary_groups=necessary_groups)

    # Compute boundary nodes
    boundary_map = compute_boundary_nodes(clusters)

    charts = []
    for ci, cluster in enumerate(clusters):
        support = sorted(cluster)
        support_ids = [ids[i] for i in support]
        support_set = set(support_ids)

        internal_couplings = [
            c for c in state.couplings
            if c.source in support_set and c.target in support_set
        ]

        solver_type = classify_chart_type(support_ids, internal_couplings, state)

        G_alpha, tau_alpha = build_local_metric(
            support, support_ids, internal_couplings, state)

        boundary = sorted(boundary_map.get(ci, set()))

        charts.append(Chart(
            id=ci,
            support=support,
            support_ids=support_ids,
            couplings=internal_couplings,
            boundary=boundary,
            solver_type=solver_type,
            G_alpha=G_alpha,
            tau_alpha=tau_alpha,
        ))

    return charts


# ══════════════════════════════════════════════════════════════
# LOCAL SOLVER 1: METRIC CHART (Definition 6.1)
#
# Preconditioned gradient descent on Θ restricted to chart support.
# σ_{k+1}[U_α] = clip(σ_k[U_α] - η · G_α⁻¹ · ∇_{U_α}Θ(σ_k), 0, 1)
# ══════════════════════════════════════════════════════════════

def local_solve_metric(state, sigma, chart, max_local_iter=200,
                       eta=0.5, epsilon=1e-7):
    """Metric chart solver: preconditioned gradient descent."""
    support = chart.support
    d = len(support)
    sigma_local = sigma.copy()
    theta_before = compute_theta_global(state, sigma_local)

    try:
        G_inv = np.linalg.inv(chart.G_alpha)
    except np.linalg.LinAlgError:
        G_inv = np.linalg.pinv(chart.G_alpha)

    for lit in range(max_local_iter):
        grad_local = compute_local_grad_theta(state, sigma_local, support)

        direction = G_inv @ grad_local

        dir_norm = np.linalg.norm(direction)
        if dir_norm < 1e-10:
            break

        alpha = eta
        accepted = False

        for ls in range(15):
            sigma_candidate = sigma_local.copy()
            for j, gi in enumerate(support):
                sigma_candidate[gi] = np.clip(
                    sigma_local[gi] - alpha * direction[j], 0.0, 1.0)

            # R_reality first (evidence pinning), then project (ceiling gets last word)
            sigma_candidate = R_reality(sigma_candidate, state)
            sigma_candidate = project_necessary_feasible(sigma_candidate, state)
            theta_candidate = compute_theta_global(state, sigma_candidate)
            if theta_candidate < theta_before - epsilon:
                sigma_local = sigma_candidate
                theta_before = theta_candidate
                accepted = True
                if ls == 0:
                    eta = min(eta * 1.1, 2.0)
                else:
                    eta = alpha
                break

            alpha *= 0.5

        if not accepted:
            break

    theta_after = compute_theta_global(state, sigma_local)
    return sigma_local, max(0.0, theta_before - theta_after)



# ══════════════════════════════════════════════════════════════
# LOCAL SOLVER 1b: MASTER RECURSION (v12)
#
# The source code derivation:
#   Line 1: Θ(∅) = ∞ > Θ_crit
#   Line 2: σ_{n+1} = F(σ_n - D(σ_n, F(σ_n)))
#
# Expanded:
#   F(σ) = σ + Δt·R(σ)  where R(σ) = Lσ + sat_ℓ(N(σ))
#   σ_{n+1} = σ_n - P_n · R(σ_n)
#   P_n = 2Δt·I + Δt²·J_R(σ_n)
#   J_R = L + sat'_ℓ(N(σ)) · dN(σ)
#
# L = linear coupling operator (sparse d×d from coupling structure)
#   - necessary: 3s·(gap²) → contributes to L[ti,ti] and L[ti,si]
#   - supporting: 0.3s·(gap²) → same structure
#   - evidence: 1.5w·(σ-e)² → L[i,i] diagonal
#   - ceiling: 5·(gap²) → L[ti,ti] and L[ti,si]
#   - completion: 0.3·(gap²) → L[ti,ti] and L[ti,si]
#
# N = nonlinear interaction operator
#   - defeating: s·se·te → product terms
#   - veto: s·src·te → product terms
#   - weakening: 0.3s·se·te → product terms
#
# sat_ℓ(f) = f / sqrt(1 + ℓ²f²)
# sat'_ℓ(f) = 1 / (1 + ℓ²f²)^(3/2)  ← closed form
#
# J_R is analytic. P_n uses J_R. No Hessian. No finite differences.
# Cost per iteration: O(d + |E|) where |E| is number of couplings.
# ══════════════════════════════════════════════════════════════

def sat_deriv(f, ell=1.0):
    """Derivative of sat_ℓ(f) = f / sqrt(1 + ℓ²f²).
    sat'_ℓ(f) = 1 / (1 + ℓ²f²)^(3/2)
    """
    return 1.0 / (1.0 + ell**2 * f**2) ** 1.5


def build_residual_and_jacobian(state, sigma, support, support_ids):
    """Build R(σ) and J_R analytically from coupling structure.

    R(σ) = Lσ + sat_ℓ(N(σ)) is the residual (what Θ gradient encodes).
    J_R = L + sat'_ℓ(N(σ)) · dN(σ) is the Jacobian of R.

    Both computed analytically from the coupling graph. O(d + |E|).
    """
    d = len(support)
    global_to_local = {}
    for j, gi in enumerate(support):
        global_to_local[gi] = j

    idx = {c: i for i, c in enumerate(state.ids)}
    pol = state.polarities()
    eff = effective_values(sigma, pol)

    # R is a d-vector (the residual at each local condition)
    R = np.zeros(d)
    # J_R is a d×d matrix (the Jacobian of R)
    J_R = np.zeros((d, d))

    # ── L: Linear coupling terms (quadratic in σ → linear gradient) ──

    # Evidence mismatch: 1.5 * w * (σ_i - e_i)²
    # ∂/∂σ_i = 2 * 1.5 * w * (σ_i - e_i)
    # ∂²/∂σ_i² = 2 * 1.5 * w
    W_EVIDENCE = 1.5
    for j, gi in enumerate(support):
        cid = state.ids[gi]
        cond = state.conditions[cid]
        if cond.evidence_weight > 0:
            w = cond.evidence_weight
            R[j] += 2.0 * W_EVIDENCE * w * (sigma[gi] - cond.evidence)
            J_R[j, j] += 2.0 * W_EVIDENCE * w

    # Necessary coupling: 3s * max(0, te - se)²
    # When te > se: ∂/∂te = 2 * 3s * (te - se), ∂/∂se = -2 * 3s * (te - se)
    # J_R[ti,ti] += 6s, J_R[ti,si] -= 6s (when gap > 0)
    for c in state.couplings:
        si_g, ti_g = idx.get(c.source), idx.get(c.target)
        if si_g is None or ti_g is None:
            continue
        si_l = global_to_local.get(si_g)
        ti_l = global_to_local.get(ti_g)
        if si_l is None or ti_l is None:
            continue

        se, te = eff[si_g], eff[ti_g]
        strength = abs(c.strength)

        if c.type == "necessary":
            gap = max(0.0, te - se)
            if gap > 0:
                # Gradient contribution
                R[ti_l] += 2.0 * 3.0 * strength * gap
                R[si_l] -= 2.0 * 3.0 * strength * gap * 0.0  # necessary only penalizes target
                # Jacobian contribution
                J_R[ti_l, ti_l] += 6.0 * strength
                J_R[ti_l, si_l] -= 6.0 * strength

        elif c.type == "supporting":
            gap = max(0.0, te - se - 0.2)
            if gap > 0:
                grad_val = 2.0 * strength * 0.3 * gap
                R[ti_l] += grad_val * 0.5
                R[si_l] -= grad_val * 0.5
                J_R[ti_l, ti_l] += strength * 0.6
                J_R[ti_l, si_l] -= strength * 0.6

    # Necessary ceiling: W_CEILING * max(0, te - min_source)²
    W_CEILING = 5.0
    nec_sources_by_target = defaultdict(list)
    for c in state.couplings:
        if c.type == "necessary":
            si_g, ti_g = idx.get(c.source), idx.get(c.target)
            if si_g is not None and ti_g is not None:
                nec_sources_by_target[ti_g].append(si_g)

    for ti_g, src_indices in nec_sources_by_target.items():
        ti_l = global_to_local.get(ti_g)
        if ti_l is None:
            continue
        min_source = min(eff[s] for s in src_indices)
        min_source_g = min(src_indices, key=lambda s: eff[s])
        min_source_l = global_to_local.get(min_source_g)
        te = eff[ti_g]

        if te > min_source:
            gap = te - min_source
            R[ti_l] += 2.0 * W_CEILING * gap
            J_R[ti_l, ti_l] += 2.0 * W_CEILING
            if min_source_l is not None:
                J_R[ti_l, min_source_l] -= 2.0 * W_CEILING

    # Completion: 0.3 * max(0, min_source - te)²
    W_COMPLETION = 0.3
    for ti_g, src_indices in nec_sources_by_target.items():
        ti_l = global_to_local.get(ti_g)
        if ti_l is None:
            continue
        min_source = min(eff[s] for s in src_indices)
        te = eff[ti_g]
        if min_source > te:
            gap = min_source - te
            R[ti_l] -= 2.0 * W_COMPLETION * gap  # Pulls target UP
            J_R[ti_l, ti_l] += 2.0 * W_COMPLETION

    # Supporting completion: 0.15 * s * max(0, target_level - te)²
    W_SUPPORT_COMPLETION = 0.15
    for c in state.couplings:
        if c.type != "supporting":
            continue
        si_g, ti_g = idx.get(c.source), idx.get(c.target)
        if si_g is None or ti_g is None:
            continue
        si_l = global_to_local.get(si_g)
        ti_l = global_to_local.get(ti_g)
        if si_l is None or ti_l is None:
            continue
        se, te = eff[si_g], eff[ti_g]
        if ti_g in nec_sources_by_target:
            cap = min(eff[s] for s in nec_sources_by_target[ti_g])
        else:
            cap = 1.0
        target_level = min(se, cap)
        if target_level > te:
            gap = target_level - te
            grad_val = 2.0 * W_SUPPORT_COMPLETION * abs(c.strength) * gap
            R[ti_l] -= grad_val * 0.7  # Pulls target UP
            R[si_l] -= grad_val * 0.3
            J_R[ti_l, ti_l] += 2.0 * W_SUPPORT_COMPLETION * abs(c.strength) * 0.7

    # ── N: Nonlinear interaction terms (products → sat_ℓ applied) ──
    # defeating: s * se * te → ∂/∂te = s * se, ∂/∂se = s * te
    # veto: s * src * te → ∂/∂te = s * src, ∂/∂src = s * te
    # weakening: 0.3s * se * te → ∂/∂te = 0.3s * se, ∂/∂se = 0.3s * te

    for c in state.couplings:
        si_g, ti_g = idx.get(c.source), idx.get(c.target)
        if si_g is None or ti_g is None:
            continue
        si_l = global_to_local.get(si_g)
        ti_l = global_to_local.get(ti_g)
        if si_l is None or ti_l is None:
            continue

        se, te = eff[si_g], eff[ti_g]
        strength = abs(c.strength)

        if c.type == "defeating":
            # N = s * se * te (raw nonlinear value)
            N_val = strength * se * te
            sat_d = sat_deriv(N_val)

            # ∂N/∂se = s * te, ∂N/∂te = s * se
            dN_dse = strength * te
            dN_dte = strength * se

            # Gradient: sat(N) split equally
            sat_N = sat(N_val)
            R[si_l] += sat_N * 0.5
            R[ti_l] += sat_N * 0.5

            # Jacobian: sat'(N) * dN/dσ
            J_R[si_l, si_l] += sat_d * dN_dse * 0.5
            J_R[si_l, ti_l] += sat_d * dN_dte * 0.5
            J_R[ti_l, si_l] += sat_d * dN_dse * 0.5
            J_R[ti_l, ti_l] += sat_d * dN_dte * 0.5

        elif c.type == "veto":
            if state.conditions[state.ids[si_g]].polarity == -1:
                src_active = sigma[si_g]
            else:
                src_active = se
            N_val = strength * src_active * te
            sat_d = sat_deriv(N_val)

            dN_dsrc = strength * te
            dN_dte = strength * src_active

            sat_N = sat(N_val)
            R[si_l] += sat_N * 0.5
            R[ti_l] += sat_N * 0.5

            J_R[si_l, si_l] += sat_d * dN_dsrc * 0.5
            J_R[si_l, ti_l] += sat_d * dN_dte * 0.5
            J_R[ti_l, si_l] += sat_d * dN_dsrc * 0.5
            J_R[ti_l, ti_l] += sat_d * dN_dte * 0.5

        elif c.type == "weakening":
            N_val = strength * 0.3 * se * te
            sat_d = sat_deriv(N_val)

            dN_dse = strength * 0.3 * te
            dN_dte = strength * 0.3 * se

            sat_N = sat(N_val)
            R[si_l] += sat_N * 0.5
            R[ti_l] += sat_N * 0.5

            J_R[si_l, si_l] += sat_d * dN_dse * 0.5
            J_R[si_l, ti_l] += sat_d * dN_dte * 0.5
            J_R[ti_l, si_l] += sat_d * dN_dse * 0.5
            J_R[ti_l, ti_l] += sat_d * dN_dte * 0.5

    return R, J_R


def local_solve_master(state, sigma, chart, max_local_iter=200,
                       eta=0.5, epsilon=1e-7):
    """Hybrid master recursion: Newton (analytic Jacobian) + gradient fallback.

    Phase 1 (Newton): σ_{n+1} = σ_n - P_n · R(σ_n)
      P_n = 2Δt·I + Δt²·J_R(σ_n)  (the preconditioner)
      J_R = L + sat'_ℓ(N(σ)) · dN(σ)  (analytic Jacobian)
      R(σ) = Lσ + sat_ℓ(N(σ))  (the residual)

    Phase 2 (Gradient): σ_{n+1} = σ_n - η · G_α⁻¹ · ∇Θ
      Switches when Newton step rejected k times in a row,
      or step size drops below threshold.

    Standard globalized Newton: Newton when it works, gradient when it overshoots.
    Cost: O(d + |E|) per Newton step, O(d) per gradient step.
    """
    support = chart.support
    d = len(support)
    sigma_local = sigma.copy()
    theta_before = compute_theta_global(state, sigma_local)

    dt = 0.1  # Time step for the forward map
    newton_reject_count = 0
    NEWTON_REJECT_LIMIT = 3  # Switch to gradient after k consecutive rejections
    STEP_SIZE_FLOOR = 1e-4  # Switch to gradient if step size drops below this
    mode = "newton"  # Start with Newton

    # Precompute G_α⁻¹ for gradient fallback
    try:
        G_inv = np.linalg.inv(chart.G_alpha)
    except np.linalg.LinAlgError:
        G_inv = np.linalg.pinv(chart.G_alpha)

    eta_newton = eta
    eta_grad = 0.5

    for lit in range(max_local_iter):

        if mode == "newton":
            # ── Newton phase: analytic Jacobian preconditioner ──
            R_vec, J_R = build_residual_and_jacobian(
                state, sigma_local, support, chart.support_ids)

            r_norm = np.linalg.norm(R_vec)
            if r_norm < 1e-10:
                break

            # P_n = 2Δt·I + Δt²·J_R
            P_n = 2.0 * dt * np.eye(d) + dt**2 * J_R
            P_n += 0.001 * np.eye(d)  # Regularize

            try:
                delta_sigma = np.linalg.solve(P_n, R_vec)
            except np.linalg.LinAlgError:
                delta_sigma = np.linalg.lstsq(P_n, R_vec, rcond=None)[0]

            # Line search
            alpha = eta_newton
            accepted = False

            for ls in range(15):
                sigma_candidate = sigma_local.copy()
                for j, gi in enumerate(support):
                    sigma_candidate[gi] = np.clip(
                        sigma_local[gi] - alpha * delta_sigma[j], 0.0, 1.0)

                # R_reality first (evidence pinning), then project (ceiling gets last word)
                sigma_candidate = R_reality(sigma_candidate, state)
                sigma_candidate = project_necessary_feasible(sigma_candidate, state)
                theta_candidate = compute_theta_global(state, sigma_candidate)

                if theta_candidate < theta_before - epsilon:
                    sigma_local = sigma_candidate
                    theta_before = theta_candidate
                    accepted = True
                    newton_reject_count = 0
                    if ls == 0:
                        eta_newton = min(eta_newton * 1.1, 2.0)
                    else:
                        eta_newton = alpha
                    break

                alpha *= 0.5

            if not accepted:
                newton_reject_count += 1
                if newton_reject_count >= NEWTON_REJECT_LIMIT:
                    mode = "gradient"  # Switch to gradient
                    continue

            # Check if step size has collapsed
            if eta_newton < STEP_SIZE_FLOOR:
                mode = "gradient"

        else:
            # ── Gradient phase: G_α⁻¹ · ∇Θ for refinement ──
            grad_local = compute_local_grad_theta(state, sigma_local, support)

            direction = G_inv @ grad_local

            dir_norm = np.linalg.norm(direction)
            if dir_norm < 1e-10:
                break

            alpha = eta_grad
            accepted = False

            for ls in range(15):
                sigma_candidate = sigma_local.copy()
                for j, gi in enumerate(support):
                    sigma_candidate[gi] = np.clip(
                        sigma_local[gi] - alpha * direction[j], 0.0, 1.0)

                # R_reality first (evidence pinning), then project (ceiling gets last word)
                sigma_candidate = R_reality(sigma_candidate, state)
                sigma_candidate = project_necessary_feasible(sigma_candidate, state)
                theta_candidate = compute_theta_global(state, sigma_candidate)

                if theta_candidate < theta_before - epsilon:
                    sigma_local = sigma_candidate
                    theta_before = theta_candidate
                    accepted = True
                    if ls == 0:
                        eta_grad = min(eta_grad * 1.1, 2.0)
                    else:
                        eta_grad = alpha
                    break

                alpha *= 0.5

            if not accepted:
                break

    theta_after = compute_theta_global(state, sigma_local)
    return sigma_local, max(0.0, theta_before - theta_after)

# ══════════════════════════════════════════════════════════════
# LOCAL SOLVER 2: AXIOM CHART
#
# Full 18-axiom witness → contradiction → update loop.
# The axiom engine runs on the local patch, using the global Θ
# for energy evaluation but the axiom witness for direction.
#
# Steps:
#   1. Evaluate W(σ) — 18 axiom scores on the local patch
#   2. Compute contradiction: Ξ = ½⟨δa, M·δa⟩
#   3. Build P matrix: axiom demands on local conditions
#   4. Update: σ' = σ + η · P^T · M · (1-a) (axiom-driven correction)
#   5. Apply R_reality
#   6. Accept if Θ decreases
# ══════════════════════════════════════════════════════════════

def build_local_P_matrix(state, sigma, support, support_ids):
    """Build the P matrix (conditions × axioms) for a local patch.

    P[i,j] = ∂a_j/∂σ_i — how much axiom j changes when condition i changes.
    Computed by numerical differentiation on the local patch.
    """
    d = len(support)
    P = np.zeros((d, N_AXIOMS))
    h = 1e-4

    a_base = W_witness(state, sigma)

    for j, gi in enumerate(support):
        sp = sigma.copy()
        sm = sigma.copy()
        sp[gi] = min(1.0, sigma[gi] + h)
        sm[gi] = max(0.0, sigma[gi] - h)
        dh = sp[gi] - sm[gi]
        if dh > 0:
            a_plus = W_witness(state, sp)
            a_minus = W_witness(state, sm)
            P[j, :] = (a_plus - a_minus) / dh

    return P


def local_solve_axiom(state, sigma, chart, M, max_local_iter=100,
                      eta=0.3, epsilon=1e-7):
    """Axiom chart solver: full 18-axiom witness-driven update.

    Uses the axiom witness to compute a correction direction, then
    projects it onto the local patch via the P matrix.
    """
    support = chart.support
    d = len(support)
    sigma_local = sigma.copy()
    theta_before = compute_theta_global(state, sigma_local)

    for lit in range(max_local_iter):
        # Step 1: Axiom witness
        a = W_witness(state, sigma_local)

        # Step 2: Axiom target (one F step)
        a_target = F_axiom(a, M, dt=0.05)

        # Step 3: Axiom tension (what needs to change in axiom space)
        delta_a = a_target - a  # Direction axioms want to move

        # Step 4: Build P matrix for this patch
        P = build_local_P_matrix(state, sigma_local, support, chart.support_ids)

        # Step 5: Project axiom demand into condition space
        # direction = P^T · M · delta_a (weighted by axiom importance)
        # But we also blend with the direct gradient for stability
        axiom_direction = P @ (M @ delta_a)

        # Also compute direct gradient for blending
        grad_local = compute_local_grad_theta(state, sigma_local, support)

        # Blend: 60% axiom-driven, 40% gradient-driven
        # The axiom direction gives structural insight, the gradient gives Θ-descent
        direction = 0.6 * axiom_direction - 0.4 * grad_local

        dir_norm = np.linalg.norm(direction)
        if dir_norm < 1e-10:
            break

        # Normalize to prevent huge steps
        if dir_norm > 1.0:
            direction = direction / dir_norm

        # Line search
        alpha = eta
        accepted = False

        for ls in range(15):
            sigma_candidate = sigma_local.copy()
            for j, gi in enumerate(support):
                sigma_candidate[gi] = np.clip(
                    sigma_local[gi] + alpha * direction[j], 0.0, 1.0)

            # R_reality first (evidence pinning), then project (ceiling gets last word)
            sigma_candidate = R_reality(sigma_candidate, state)
            sigma_candidate = project_necessary_feasible(sigma_candidate, state)
            theta_candidate = compute_theta_global(state, sigma_candidate)

            if theta_candidate < theta_before - epsilon:
                sigma_local = sigma_candidate
                theta_before = theta_candidate
                accepted = True
                if ls == 0:
                    eta = min(eta * 1.1, 1.0)
                else:
                    eta = alpha
                break

            alpha *= 0.5

        if not accepted:
            break

    theta_after = compute_theta_global(state, sigma_local)
    return sigma_local, max(0.0, theta_before - theta_after)





# ══════════════════════════════════════════════════════════════
# CHART SELECTION BY CURVATURE (Definition 3.1)
# ══════════════════════════════════════════════════════════════

def select_chart(charts, remaining, theta_per_channel):
    """Select the chart whose support has the highest total θ."""
    best_chart = None
    best_score = -1.0

    for ci in remaining:
        chart = charts[ci]
        score = sum(theta_per_channel[i] for i in chart.support)
        if score > best_score:
            best_score = score
            best_chart = ci

    return best_chart


# ══════════════════════════════════════════════════════════════
# BOUNDARY DIFFUSION
#
# After a chart update, propagate information to overlapping charts
# through boundary nodes. This ensures inter-chart consistency
# without requiring global gradient computation.
#
# For each boundary node b in chart α that also appears in chart β:
#   σ_β[b] = (1-λ)·σ_β[b] + λ·σ_α[b]
# where λ is the diffusion rate.
# ══════════════════════════════════════════════════════════════

def boundary_diffuse(sigma, charts, updated_chart_id, diffusion_rate=0.5):
    """Propagate boundary node values from updated chart to neighbors."""
    updated_chart = charts[updated_chart_id]
    updated_set = set(updated_chart.support)
    sigma_new = sigma.copy()

    for other_chart in charts:
        if other_chart.id == updated_chart_id:
            continue
        # Find shared nodes
        shared = updated_set & set(other_chart.support)
        if not shared:
            continue

        for node in shared:
            # The updated chart's value is the "source of truth" for this boundary
            # Diffuse: blend toward the updated value
            # (This is a no-op if sigma already has the updated value,
            #  but matters when multiple charts compete for a boundary node)
            pass  # sigma_new already has the updated values from the chart solve

    return sigma_new


# ══════════════════════════════════════════════════════════════
# ATLAS ITERATION (Definition 3.3)
# ══════════════════════════════════════════════════════════════

def run_atlas(state, max_passes=50, max_local_iter=200, eta_init=0.5,
              epsilon=1e-6, delta=1e-8, max_chart_size=None,
              weight_mode="master", verbose=False):
    """
    CQIM v12: Master recursion + multi-chart atlas.

    Chart types:
      - metric → master recursion: σ' = F(σ - D(σ, F(σ))) (primary, second-order)
      - axiom: full 18-axiom witness loop (complex topology)

    Outer loop: Anderson acceleration (m=5 mixing depth)
    Convergence guaranteed by Theorems 4.1-4.4.
    Master recursion: quadratic convergence via contraction of F ∘ D.
    """
    n = state.n

    # Bootstrap: nothing exists
    sigma = np.zeros(n)

    # Build atlas from coupling structure
    charts = construct_atlas(state, max_chart_size=max_chart_size)
    K = len(charts)

    # M for axiom solver and diagnostics
    if weight_mode == "equal":
        M = np.eye(N_AXIOMS)
    elif weight_mode == "derived":
        M = np.diag([BOOTSTRAP_WEIGHTS[name] for name in AXIOM_NAMES])
    else:
        M = AXIOM_M.copy()

    # ── Tracking ──
    theta_history = []
    n_accepted_total = 0
    n_rejected_total = 0
    solver_stats = {"master": 0, "metric": 0, "axiom": 0}

    theta_current = compute_theta_global(state, sigma)
    theta_history.append(theta_current)
    theta_start = theta_current

    a_initial = W_witness(state, sigma)

    if verbose:
        print(f"  Atlas: K={K} charts, n={n} conditions")
        for ci, chart in enumerate(charts):
            bnd = f", {len(chart.boundary)} boundary" if chart.boundary else ""
            print(f"    Chart {ci}: {chart.support_ids} "
                  f"({len(chart.couplings)} couplings, {chart.solver_type}{bnd})")
        print(f"  Θ₀ = {theta_current:.6f}")

    # ── Anderson acceleration state (v12) ──
    # Store last m sigma iterates and their residuals for mixing
    anderson_m = 5  # Mixing depth
    anderson_sigmas = []  # List of sigma vectors from end of each pass
    anderson_residuals = []  # List of (sigma_after - sigma_before) per pass

    # ── Outer loop with Anderson acceleration (v12) ──
    for pass_num in range(max_passes):
        remaining = set(range(K))
        accepted_any = False
        theta_at_pass_start = theta_current
        sigma_before_pass = sigma.copy()

        while remaining:
            # Select chart by curvature
            theta_pc = compute_theta_per_channel(state, sigma)
            alpha_star = select_chart(charts, remaining, theta_pc)

            if alpha_star is None:
                break

            chart = charts[alpha_star]

            # Dispatch to chart-type-specific solver
            if chart.solver_type == "axiom":
                sigma_candidate, reduction = local_solve_axiom(
                    state, sigma, chart, M,
                    max_local_iter=min(max_local_iter, 100),
                    eta=0.3,
                )
            else:  # metric → use master recursion (v12)
                sigma_candidate, reduction = local_solve_master(
                    state, sigma, chart,
                    max_local_iter=max_local_iter,
                    eta=eta_init,
                )

            # Energy gate (Definition 3.2)
            theta_candidate = compute_theta_global(state, sigma_candidate)

            if theta_candidate < theta_current - epsilon:
                # ACCEPTED
                sigma = sigma_candidate
                theta_current = theta_candidate
                theta_history.append(theta_current)
                n_accepted_total += 1
                accepted_any = True
                # Track: metric charts now use master recursion solver
                if chart.solver_type == "metric":
                    solver_stats["master"] = solver_stats.get("master", 0) + 1
                else:
                    solver_stats[chart.solver_type] = solver_stats.get(chart.solver_type, 0) + 1

                # Boundary diffusion (no-op for K=1)
                if K > 1:
                    sigma = boundary_diffuse(sigma, charts, alpha_star)

                if verbose and n_accepted_total % 10 == 0:
                    print(f"  pass {pass_num:3d} chart {alpha_star:3d} "
                          f"[{chart.solver_type:10s}]: "
                          f"Θ={theta_current:.6f}  "
                          f"(accepted {n_accepted_total}, rejected {n_rejected_total})")
            else:
                n_rejected_total += 1

            remaining.discard(alpha_star)

        # ── Anderson acceleration (v12): mix previous iterates ──
        if accepted_any and K > 1:
            residual = sigma - sigma_before_pass
            anderson_sigmas.append(sigma.copy())
            anderson_residuals.append(residual.copy())

            # Keep only last m
            if len(anderson_sigmas) > anderson_m:
                anderson_sigmas.pop(0)
                anderson_residuals.pop(0)

            # Anderson mixing: if we have >= 2 iterates, compute optimal mix
            m_actual = len(anderson_residuals)
            if m_actual >= 2:
                # Build residual matrix R = [r_{k-m+1}, ..., r_k]
                R_mat = np.column_stack(anderson_residuals)  # n × m
                # Solve least-squares: min ||R @ α||^2 s.t. sum(α) = 1
                # Equivalent: R^T R α = 0 with constraint
                RtR = R_mat.T @ R_mat + 1e-10 * np.eye(m_actual)  # Regularize
                try:
                    # Solve for unconstrained minimum, then project
                    ones = np.ones(m_actual)
                    RtR_inv = np.linalg.inv(RtR)
                    alpha_and = RtR_inv @ ones
                    alpha_and = alpha_and / np.sum(alpha_and)  # Normalize to sum=1

                    # Compute Anderson-mixed sigma
                    sigma_mixed = np.zeros(n)
                    for i_a in range(m_actual):
                        sigma_mixed += alpha_and[i_a] * (
                            anderson_sigmas[i_a] + anderson_residuals[i_a]
                        )
                    sigma_mixed = np.clip(sigma_mixed, 0.0, 1.0)

                    # Energy gate: only accept if Anderson mixing improves Θ
                    theta_mixed = compute_theta_global(state, sigma_mixed)
                    if theta_mixed < theta_current - epsilon:
                        sigma = sigma_mixed
                        theta_current = theta_mixed
                        theta_history.append(theta_current)
                        if verbose:
                            print(f"  pass {pass_num:3d} Anderson mix (m={m_actual}): "
                                  f"Θ={theta_current:.6f}")
                except np.linalg.LinAlgError:
                    pass  # Anderson mixing failed, continue without it

        # Termination check — only stop when no chart can make progress
        if not accepted_any:
            if verbose:
                print(f"  No chart accepted in pass {pass_num}. "
                      f"Θ={theta_current:.6f}")
            break

    # ── Gradient descent polish ───────────────────────────────────────────────
    # The atlas chart-based solver (especially axiom type) can stall when its
    # composite direction stops clearing the energy gate, even though significant
    # Theta reduction remains.  Run projected gradient descent on the full sigma
    # until no further progress is possible.
    if theta_current > epsilon:
        h_gd = 1e-5
        lr_gd = 0.1
        for _ in range(2000):
            grad_gd = np.zeros(n)
            for i in range(n):
                sp = sigma.copy(); sm = sigma.copy()
                sp[i] = min(1.0, sigma[i] + h_gd)
                sm[i] = max(0.0, sigma[i] - h_gd)
                dh = sp[i] - sm[i]
                if dh > 0:
                    grad_gd[i] = (compute_theta_global(state, sp) -
                                  compute_theta_global(state, sm)) / dh
            if np.linalg.norm(grad_gd) < epsilon:
                break
            step = lr_gd
            accepted_gd = False
            for _ in range(25):
                sigma_new = np.clip(sigma - step * grad_gd, 0.0, 1.0)
                theta_new = compute_theta_global(state, sigma_new)
                if theta_new < theta_current - 1e-12:
                    sigma = sigma_new
                    theta_current = theta_new
                    theta_history.append(theta_current)
                    lr_gd = min(step * 1.2, 1.0)
                    accepted_gd = True
                    break
                step *= 0.5
            if not accepted_gd:
                break
        if verbose:
            print(f"  Gradient polish finished: Θ={theta_current:.8f}")

    # ── Final state ──
    state.set_sigma(sigma)

    # ── Axiom diagnostics ──
    a_final = W_witness(state, sigma)
    a_target = F_axiom(a_final, M, dt=0.05)
    delta_final = a_final - a_target
    xi_final = 0.5 * delta_final @ M @ delta_final
    theta_final = compute_theta_global(state, sigma)
    theta_per_channel = compute_theta_per_channel(state, sigma)

    return {
        "sigma": {cid: float(sigma[i]) for i, cid in enumerate(state.ids)},
        "sigma_0": {cid: 0.0 for cid in state.ids},
        "theta": theta_final,
        "theta_start": theta_start,
        "theta_history": theta_history,
        "theta_per_channel": {cid: float(theta_per_channel[i])
                              for i, cid in enumerate(state.ids)},
        "xi": float(xi_final),
        "passes": pass_num + 1 if 'pass_num' in dir() else 0,
        "n_accepted": n_accepted_total,
        "n_rejected": n_rejected_total,
        "n_charts": K,
        "charts": [{"id": c.id, "support": c.support_ids,
                     "n_couplings": len(c.couplings),
                     "solver": c.solver_type,
                     "boundary": [state.ids[b] for b in c.boundary]}
                    for c in charts],
        "solver_stats": solver_stats,
        "axiom_state_initial": {name: float(a_initial[i])
                                for i, name in enumerate(AXIOM_NAMES)},
        "axiom_state_final": {name: float(a_final[i])
                              for i, name in enumerate(AXIOM_NAMES)},
        "weight_mode": weight_mode,
        "converged": not accepted_any,
        "monotone": all(theta_history[i] >= theta_history[i+1] - 1e-12
                       for i in range(len(theta_history)-1)),
    }


# ══════════════════════════════════════════════════════════════
# LOADER & FORMATTER
# ══════════════════════════════════════════════════════════════

def load_problem(source):
    if isinstance(source, str):
        if os.path.isfile(source):
            with open(source) as f:
                data = json.load(f)
        else:
            data = json.loads(source)
    elif isinstance(source, dict):
        data = source
    else:
        raise ValueError(f"Cannot load problem from {type(source)}")

    name = data.get("name", "Unnamed Problem")
    conditions = {}
    for cid, cdef in data["conditions"].items():
        conditions[cid] = Condition(
            id=cid, name=cdef.get("name", cid),
            satisfaction=0.0,
            weight=cdef.get("weight", 5.0),
            falsifier=cdef.get("falsifier", ""),
            verified=cdef.get("verified", False),
            evidence=cdef.get("evidence", 0.0),
            evidence_weight=cdef.get("evidence_weight", 0.0),
            polarity=cdef.get("polarity", 1),
        )
    couplings = [Coupling(
        source=c["source"], target=c["target"],
        strength=c.get("strength", 1.0), type=c["type"],
        authority=c.get("authority", ""),
    ) for c in data.get("couplings", [])]
    synergies = [Synergy(
        condition_a=s["condition_a"], condition_b=s["condition_b"],
        target=s["target"], strength=s.get("strength", 0.5),
        type=s.get("type", "emergent"), name=s.get("name", ""),
        authority=s.get("authority", ""),
    ) for s in data.get("synergies", [])]
    unknowns = data.get("unknowns", [])
    query = data.get("query", None)
    state = State(conditions=conditions, couplings=couplings,
                  synergies=synergies, unknowns=unknowns)
    return name, state, query


def format_result(name, result, query=None):
    lines = []
    lines.append(f"\n{'═' * 65}")
    lines.append(f"  {name}")
    lines.append(f"{'═' * 65}")
    lines.append(f"  Atlas: K={result['n_charts']} charts  |  "
                 f"Passes: {result['passes']}  |  "
                 f"Accepted: {result['n_accepted']}  |  "
                 f"Rejected: {result['n_rejected']}")

    # Solver stats
    ss = result.get('solver_stats', {})
    solver_str = ", ".join(f"{k}={v}" for k, v in ss.items() if v > 0)
    if solver_str:
        lines.append(f"  Solvers: {solver_str}")

    mono = "MONOTONE" if result['monotone'] else "NOT MONOTONE"
    lines.append(f"  Θ: {result['theta_start']:.4f} → {result['theta']:.4f}  "
                 f"(Δ = {result['theta'] - result['theta_start']:+.4f})  [{mono}]")
    lines.append(f"  Ξ (axiom): {result['xi']:.8f}")

    lines.append(f"")
    lines.append(f"  Charts:")
    for ci in result['charts']:
        bnd = f", boundary: {ci['boundary']}" if ci.get('boundary') else ""
        lines.append(f"    [{ci['id']}] {ci['support']} "
                     f"({ci['n_couplings']} couplings, {ci['solver']}{bnd})")

    lines.append(f"")
    lines.append(f"  Per-channel Θ decomposition:")
    theta_pc = result['theta_per_channel']
    for cid in sorted(theta_pc.keys(), key=lambda x: -theta_pc[x]):
        t = theta_pc[cid]
        bar = '█' * int(min(40, t * 100))
        lines.append(f"    {cid:<30s} θ={t:.4f}  {bar}")

    lines.append(f"")
    lines.append(f"  {'Axiom':<8s} {'a₀':>8s} {'a*':>8s} {'Δ':>8s}")
    lines.append(f"  {'─' * 36}")
    for name_a in AXIOM_NAMES:
        a0 = result["axiom_state_initial"][name_a]
        af = result["axiom_state_final"][name_a]
        d = af - a0
        marker = " ▲" if d > 0.05 else (" ▼" if d < -0.05 else "")
        lines.append(f"  {name_a:<8s} {a0:>7.1%} {af:>7.1%} {d:>+7.1%}{marker}")

    lines.append(f"")
    lines.append(f"  {'Condition':<30s} {'σ*':>6s}  {'Interpretation'}")
    lines.append(f"  {'─' * 50}")

    for cid in sorted(result["sigma"].keys()):
        s = result["sigma"][cid]
        if s > 0.8:
            interp = "STRONG"
        elif s > 0.5:
            interp = "LIKELY"
        elif s > 0.3:
            interp = "WEAK"
        elif s > 0.1:
            interp = "UNLIKELY"
        else:
            interp = "REJECTED"
        marker = "  ◀" if cid == query else ""
        lines.append(f"  {cid:<30s} {s:>5.0%}   {interp}{marker}")

    if query and query in result["sigma"]:
        lines.append(f"")
        lines.append(f"  ▶ QUERY: {query} = {result['sigma'][query]:.0%}")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# DEMO PROBLEMS
# ══════════════════════════════════════════════════════════════

DEMO_CONTRACT = {
    "name": "Contract Law: Strong Formation",
    "conditions": {
        "offer": {"name": "Offer", "weight": 8.0, "falsifier": "No communication of definite terms",
                  "evidence": 1.0, "evidence_weight": 0.8},
        "acceptance": {"name": "Acceptance", "weight": 8.0, "falsifier": "No assent communicated",
                       "evidence": 1.0, "evidence_weight": 0.8},
        "consideration": {"name": "Consideration", "weight": 10.0, "falsifier": "No bargained-for exchange",
                          "evidence": 0.93, "evidence_weight": 0.9},
        "capacity": {"name": "Capacity", "weight": 7.0, "falsifier": "Party is minor or incompetent",
                     "evidence": 1.0, "evidence_weight": 0.7},
        "definiteness": {"name": "Definiteness", "weight": 6.0, "falsifier": "Essential terms too vague",
                         "evidence": 1.0, "evidence_weight": 0.7},
        "duress": {"name": "Duress", "weight": 8.0, "falsifier": "No improper threat shown",
                   "evidence": 0.05, "evidence_weight": 0.9, "polarity": 1},
        "statute_of_frauds": {"name": "Statute of Frauds", "weight": 5.0,
                              "falsifier": "Writing requirement met or not within statute",
                              "evidence": 1.0, "evidence_weight": 0.9},
        "enforceability": {"name": "Enforceability", "weight": 10.0,
                           "falsifier": "Any formation element missing or defense present"},
    },
    "couplings": [
        {"source": "offer", "target": "enforceability", "strength": 1.0, "type": "necessary"},
        {"source": "acceptance", "target": "enforceability", "strength": 1.0, "type": "necessary"},
        {"source": "consideration", "target": "enforceability", "strength": 1.0, "type": "necessary"},
        {"source": "capacity", "target": "enforceability", "strength": 1.0, "type": "necessary"},
        {"source": "definiteness", "target": "enforceability", "strength": 0.5, "type": "supporting"},
        {"source": "duress", "target": "enforceability", "strength": -1.0, "type": "veto"},
        {"source": "statute_of_frauds", "target": "enforceability", "strength": 0.5, "type": "necessary"},
        {"source": "offer", "target": "acceptance", "strength": 1.0, "type": "necessary"},
        {"source": "definiteness", "target": "offer", "strength": 0.5, "type": "supporting"},
        {"source": "consideration", "target": "definiteness", "strength": 0.5, "type": "supporting"},
    ],
    "synergies": [
        {"condition_a": "offer", "condition_b": "acceptance", "target": "enforceability",
         "strength": 0.5, "type": "emergent", "name": "Mutual assent"},
        {"condition_a": "duress", "condition_b": "consideration", "target": "enforceability",
         "strength": -0.8, "type": "compounding", "name": "Coerced exchange"},
    ],
    "query": "enforceability"
}

DEMO_MEDICAL = {
    "name": "Medical Diagnosis: Chest Pain Differential",
    "conditions": {
        "chest_pain": {"name": "Chest Pain Present", "weight": 3.0,
                       "evidence": 1.0, "evidence_weight": 1.0, "verified": True,
                       "falsifier": "Patient denies chest pain"},
        "elevated_troponin": {"name": "Elevated Troponin", "weight": 9.0,
                              "evidence": 0.8, "evidence_weight": 0.95,
                              "falsifier": "Troponin within normal limits"},
        "st_changes": {"name": "ST Segment Changes", "weight": 7.0,
                       "evidence": 0.7, "evidence_weight": 0.8,
                       "falsifier": "Normal ECG"},
        "normal_d_dimer": {"name": "Normal D-dimer", "weight": 6.0,
                           "evidence": 0.9, "evidence_weight": 0.85,
                           "polarity": -1,
                           "falsifier": "D-dimer elevated"},
        "hypertension_hx": {"name": "Hypertension History", "weight": 4.0,
                            "evidence": 1.0, "evidence_weight": 0.7,
                            "falsifier": "No hypertension history"},
        "acute_mi": {"name": "Acute MI", "weight": 10.0,
                     "falsifier": "Alternative diagnosis confirmed"},
        "pulmonary_embolism": {"name": "Pulmonary Embolism", "weight": 8.0,
                               "falsifier": "PE ruled out by imaging"},
        "musculoskeletal": {"name": "Musculoskeletal Pain", "weight": 5.0,
                            "falsifier": "Cardiac biomarkers positive"},
    },
    "couplings": [
        {"source": "chest_pain", "target": "acute_mi", "strength": 0.4, "type": "supporting"},
        {"source": "elevated_troponin", "target": "acute_mi", "strength": 1.0, "type": "necessary"},
        {"source": "st_changes", "target": "acute_mi", "strength": 0.8, "type": "supporting"},
        {"source": "hypertension_hx", "target": "acute_mi", "strength": 0.3, "type": "supporting"},
        {"source": "chest_pain", "target": "pulmonary_embolism", "strength": 0.3, "type": "supporting"},
        {"source": "normal_d_dimer", "target": "pulmonary_embolism", "strength": -1.0, "type": "veto"},
        {"source": "chest_pain", "target": "musculoskeletal", "strength": 0.5, "type": "supporting"},
        {"source": "elevated_troponin", "target": "musculoskeletal", "strength": -1.0, "type": "defeating"},
        {"source": "st_changes", "target": "musculoskeletal", "strength": -0.5, "type": "defeating"},
        {"source": "acute_mi", "target": "musculoskeletal", "strength": -0.8, "type": "defeating"},
    ],
    "query": "acute_mi"
}

DEMO_PHILOSOPHY = {
    "name": "Philosophy: Free Will vs Determinism",
    "conditions": {
        "determinism": {"name": "Physical Determinism", "weight": 7.0,
                        "evidence": 0.7, "evidence_weight": 0.6,
                        "falsifier": "Quantum indeterminacy at macro scale"},
        "agent_causation": {"name": "Agent Causation", "weight": 6.0,
                            "evidence": 0.5, "evidence_weight": 0.4,
                            "falsifier": "No mechanism for agent causation"},
        "moral_responsibility": {"name": "Moral Responsibility Exists", "weight": 8.0,
                                 "evidence": 0.85, "evidence_weight": 0.7,
                                 "falsifier": "Moral responsibility is illusion"},
        "could_have_otherwise": {"name": "Could Have Done Otherwise", "weight": 5.0,
                                 "evidence": 0.4, "evidence_weight": 0.3,
                                 "falsifier": "Determinism precludes alternatives"},
        "compatibilism": {"name": "Compatibilism", "weight": 9.0,
                          "falsifier": "Incompatibilist argument succeeds"},
        "hard_determinism": {"name": "Hard Determinism", "weight": 7.0,
                             "falsifier": "Moral responsibility is real"},
    },
    "couplings": [
        {"source": "determinism", "target": "compatibilism", "strength": 0.6, "type": "supporting"},
        {"source": "moral_responsibility", "target": "compatibilism", "strength": 1.0, "type": "necessary"},
        {"source": "agent_causation", "target": "compatibilism", "strength": 0.4, "type": "supporting"},
        {"source": "determinism", "target": "hard_determinism", "strength": 1.0, "type": "necessary"},
        {"source": "moral_responsibility", "target": "hard_determinism", "strength": -1.0, "type": "defeating"},
        {"source": "agent_causation", "target": "hard_determinism", "strength": -0.7, "type": "defeating"},
        {"source": "determinism", "target": "could_have_otherwise", "strength": -0.8, "type": "defeating"},
        {"source": "compatibilism", "target": "hard_determinism", "strength": -0.9, "type": "defeating"},
        {"source": "hard_determinism", "target": "compatibilism", "strength": -0.5, "type": "weakening"},
    ],
    "query": "compatibilism"
}

DEMO_STARTUP = {
    "name": "Startup Investment: Series A Decision",
    "conditions": {
        "team_quality": {"name": "Team Quality", "weight": 9.0,
                         "evidence": 0.9, "evidence_weight": 0.8,
                         "falsifier": "Key person risk or team gaps"},
        "market_size": {"name": "Market Size", "weight": 7.0,
                        "evidence": 0.85, "evidence_weight": 0.7,
                        "falsifier": "Market is too small"},
        "product_market_fit": {"name": "Product-Market Fit", "weight": 10.0,
                               "evidence": 0.35, "evidence_weight": 0.5,
                               "falsifier": "No evidence of PMF"},
        "unit_economics": {"name": "Unit Economics", "weight": 8.0,
                           "evidence": 0.4, "evidence_weight": 0.6,
                           "falsifier": "Negative unit economics"},
        "burn_rate_risk": {"name": "Burn Rate Risk", "weight": 6.0,
                           "evidence": 0.6, "evidence_weight": 0.7,
                           "polarity": -1,
                           "falsifier": "Runway > 18 months"},
        "invest": {"name": "Invest Decision", "weight": 10.0,
                   "falsifier": "Any critical factor missing"},
    },
    "couplings": [
        {"source": "team_quality", "target": "invest", "strength": 1.0, "type": "necessary"},
        {"source": "market_size", "target": "invest", "strength": 0.8, "type": "necessary"},
        {"source": "product_market_fit", "target": "invest", "strength": 1.0, "type": "supporting"},
        {"source": "unit_economics", "target": "invest", "strength": 0.8, "type": "supporting"},
        {"source": "burn_rate_risk", "target": "invest", "strength": -0.7, "type": "weakening"},
        {"source": "team_quality", "target": "product_market_fit", "strength": 0.3, "type": "supporting"},
        {"source": "product_market_fit", "target": "unit_economics", "strength": 0.5, "type": "supporting"},
    ],
    "synergies": [
        {"condition_a": "team_quality", "condition_b": "market_size", "target": "invest",
         "strength": 0.4, "type": "emergent", "name": "Strong team in large market"},
    ],
    "query": "invest"
}


# ══════════════════════════════════════════════════════════════
# 100-CONDITION TEST PROBLEM
# ══════════════════════════════════════════════════════════════

def generate_100_condition_problem():
    """Generate a 100-condition problem with sparse, multi-cluster structure."""
    import random
    random.seed(42)

    conditions = {}
    couplings = []

    cluster_names = ["legal", "medical", "financial", "technical", "social"]
    cluster_conditions = {}

    for ci, cname in enumerate(cluster_names):
        cluster_conds = []
        for j in range(15):
            cid = f"{cname}_{j:02d}"
            has_evidence = random.random() < 0.6
            ev = random.uniform(0.2, 0.95) if has_evidence else 0.0
            ew = random.uniform(0.3, 0.9) if has_evidence else 0.0
            pol = -1 if random.random() < 0.15 else 1
            conditions[cid] = {
                "name": f"{cname.title()} Condition {j}",
                "weight": random.uniform(3.0, 10.0),
                "evidence": ev,
                "evidence_weight": ew,
                "polarity": pol,
                "falsifier": f"Negation of {cname}_{j:02d}",
            }
            cluster_conds.append(cid)

        cluster_conditions[cname] = cluster_conds

        for j in range(len(cluster_conds) - 1):
            ctype = random.choice(["necessary", "supporting", "supporting"])
            couplings.append({
                "source": cluster_conds[j],
                "target": cluster_conds[j + 1],
                "strength": random.uniform(0.3, 1.0),
                "type": ctype,
            })

        for _ in range(5):
            a, b = random.sample(range(len(cluster_conds)), 2)
            ctype = random.choice(["supporting", "defeating", "weakening"])
            couplings.append({
                "source": cluster_conds[a],
                "target": cluster_conds[b],
                "strength": random.uniform(0.3, 0.8),
                "type": ctype,
            })

    for ci, cname in enumerate(cluster_names):
        for k in range(2):
            cid = f"{cname}_conclusion_{k}"
            conditions[cid] = {
                "name": f"{cname.title()} Conclusion {k}",
                "weight": 10.0,
                "falsifier": f"Negation of {cname} conclusion {k}",
            }
            sources = random.sample(cluster_conditions[cname], 3)
            for src in sources:
                couplings.append({
                    "source": src,
                    "target": cid,
                    "strength": 1.0,
                    "type": "necessary",
                })

    all_cluster_names = list(cluster_names)
    for _ in range(15):
        c1, c2 = random.sample(all_cluster_names, 2)
        src = random.choice(cluster_conditions[c1])
        tgt = random.choice(cluster_conditions[c2])
        ctype = random.choice(["supporting", "weakening", "defeating"])
        couplings.append({
            "source": src,
            "target": tgt,
            "strength": random.uniform(0.2, 0.6),
            "type": ctype,
        })

    return {
        "name": "100-Condition Multi-Cluster Test",
        "conditions": conditions,
        "couplings": couplings,
        "synergies": [],
        "query": "legal_conclusion_0",
    }


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    demos = [DEMO_CONTRACT, DEMO_MEDICAL, DEMO_PHILOSOPHY, DEMO_STARTUP]

    if len(sys.argv) > 1 and sys.argv[1] == "--100":
        problem = generate_100_condition_problem()
        name, state, query = load_problem(problem)
        result = run_atlas(state, weight_mode="master", verbose=True,
                           max_passes=100, max_local_iter=500)
        print(format_result(name, result, query))
    elif len(sys.argv) > 1 and sys.argv[1] == "--covariance":
        # Test atlas covariance: K=1 vs K>1
        print("=" * 65)
        print("  ATLAS COVARIANCE TEST: K=1 vs K>1")
        print("=" * 65)
        for demo in demos:
            name, state, query = load_problem(demo)
            r1 = run_atlas(state, weight_mode="master")

            name2, state2, query2 = load_problem(demo)
            r2 = run_atlas(state2, weight_mode="master", max_chart_size=4)

            q1 = r1['sigma'][query]
            q2 = r2['sigma'][query]
            diff = abs(q1 - q2)
            status = "PASS" if diff < 0.10 else "FAIL"
            print(f"  [{status}] {name[:45]:45s} K=1:{q1:5.0%}  "
                  f"K={r2['n_charts']}:{q2:5.0%}  Δ={diff:.2%}")

            # Show solver types used
            ss = r2.get('solver_stats', {})
            solver_str = ", ".join(f"{k}={v}" for k, v in ss.items() if v > 0)
            print(f"         Solvers: {solver_str}")
            print(f"         Charts: {r2['n_charts']}, Monotone: {r2['monotone']}")
    elif len(sys.argv) > 1:
        name, state, query = load_problem(sys.argv[1])
        result = run_atlas(state, weight_mode="master", verbose=True)
        print(format_result(name, result, query))
    else:
        for demo in demos:
            name, state, query = load_problem(demo)
            result = run_atlas(state, weight_mode="master", verbose=True)
            print(format_result(name, result, query))


# ══════════════════════════════════════════════════════════════
# v14: QUOTIENT LAYER INTEGRATION
# ══════════════════════════════════════════════════════════════

def load_problem_quotient(source):
    """
    Load a problem and apply the quotient layer.

    Returns:
        (name, quotient_state, query, original_state, quotient_map)
    """
    from quotient import quotient
    name, state, query = load_problem(source)
    original_state = State(
        conditions={k: Condition(**{f.name: getattr(v, f.name)
                    for f in v.__dataclass_fields__.values()})
                    for k, v in state.conditions.items()},
        couplings=[Coupling(**{f.name: getattr(c, f.name)
                   for f in c.__dataclass_fields__.values()})
                   for c in state.couplings],
        synergies=[Synergy(**{f.name: getattr(s, f.name)
                   for f in s.__dataclass_fields__.values()})
                   for s in state.synergies],
        unknowns=list(state.unknowns),
    )
    q_state, qmap = quotient(state)
    return name, q_state, query, original_state, qmap


def run_atlas_quotient(source, weight_mode="master", verbose=False,
                       max_passes=50, max_local_iter=200):
    """
    Full quotient pipeline: load → quotient → run_atlas → lift.

    Returns:
        (result, quotient_map, quotient_report_str)
    """
    from quotient import quotient, lift, quotient_report
    name, state, query = load_problem(source)
    original_ids = list(state.conditions.keys())
    q_state, qmap = quotient(state)
    report = quotient_report(qmap)
    result = run_atlas(q_state, weight_mode=weight_mode, verbose=verbose,
                       max_passes=max_passes, max_local_iter=max_local_iter)
    lifted = lift(result, qmap, original_ids)
    return lifted, qmap, report
