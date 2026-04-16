# CQIM v14.1 — Terminal Implications

**Author:** Nathan Robert Rietmann, Rietmann Intelligence LLC  
**Implementation:** Manus AI  
**Date:** April 2026

---

## Overview

This repository contains the complete implementation, execution results, and theoretical analysis of the **Canonical Quotient Inference Machine (CQIM) v14.1** applied to itself — the first formal system to derive its own honest self-assessment as the unique fixed point of its own evaluation criteria.

---

## Repository Structure

```
├── engine/                          # Core engine
│   ├── cqim_v14_engine.py           # CQIM v14.1 — 18-axiom resolution engine
│   └── quotient.py                  # Quotient layer — canonical graph pre-processor
│
├── scripts/                         # Executable experiments
│   ├── self_application/
│   │   └── self_application.py      # Engine fed into itself (100 bootstrap passes)
│   ├── meta_recursion/
│   │   ├── meta_recursion.py        # Tower: engine(engine(engine(...))) — 10 levels
│   │   └── recursive_loop.py        # Loop: dynamics encoded as conditions inside itself
│   └── structural_bootstrap/
│       └── structural_bootstrap.py  # Structural bootstrap (M tensor rewrite attempt)
│
├── results/                         # Raw output from all runs
│   ├── self_application/
│   │   ├── self_application_100pass.log
│   │   └── self_application_results.json
│   ├── meta_recursion/
│   │   ├── meta_recursion.log
│   │   └── meta_recursion_results.json
│   ├── recursive_loop/
│   │   ├── recursive_loop.log
│   │   └── recursive_loop_results.json
│   └── structural_bootstrap/
│       └── structural_bootstrap_results.json
│
├── documents/                       # Analysis and theory
│   ├── analysis/
│   │   ├── Code_Review_Report.md          # Engine code review
│   │   ├── Self_Application_Analysis.md   # Self-application analysis (30 passes)
│   │   ├── Why_20_Percent.md              # What 20% means and why it matters
│   │   ├── CQIM_v13_vs_v14_Comparison.md  # v13 vs v14.1 comparison
│   │   └── Tower_vs_Loop_Comparison.md    # Tower vs Loop: two paths to self-reference
│   └── theory/
│       ├── CQIM_Terminal_Implications.md          # Terminal implications of the recursion
│       └── CQIM_Terminal_Implications_Extreme.md  # Taken to the logical extreme
│
├── v13_prior/                       # Prior work (v13 self-evaluation)
│   ├── papers/
│   │   ├── CQIM_Self_Referential_Global_Attractor.pdf
│   │   └── self_consistent_fixed_point.pdf
│   ├── scripts/
│   │   └── run_axiom_self_test_3.py
│   └── data/
│       ├── axiom_self_test.json
│       ├── axiom_self_test_no_evidence.json
│       ├── axiomselftestfinal.json
│       ├── axiomselftestnoevidence2.json
│       ├── cqim_self_evaluation.json
│       ├── axiom_self_test_results.txt
│       ├── axiom_self_test_3_results.txt
│       ├── self_evaluation_results.txt
│       └── CQIMv13—ExternalSelf-EvaluationTestAnalysis.md
│
├── notes/                           # Working notes
│   ├── prior_results_notes.txt
│   ├── paper_sigma_star.txt
│   ├── fixed_point_paper_notes.txt
│   └── loop_results_summary.txt
│
└── README.md
```

---

## Key Results

### Self-Application (100 passes)
- **Ω = 20.0%** — the engine's honest self-assessment
- **ρ̄ = 0.9488** — contraction mapping confirmed
- **Ξ = 0.00664** — irreducible Gödelian residual
- All 100 passes monotone. Fixed point reached.

### Meta-Recursion: The Tower (10 levels)
- **Ω = 20.0% at every level** — perfectly invariant
- **ρ̄_meta = 0.851** — the meta-recursion contracts
- `engine(self) = engine(engine(self)) = engine^10(self)`
- The meta-level collapses. There is no higher level.

### Meta-Recursion: The Loop (dynamics inside itself)
- **Ω = 32.9%** — enriched by dynamic self-knowledge
- The 13% increase comes from the engine knowing its own convergence behavior
- All conditions FIXED at pass 100.

### The Two Numbers
| | Tower | Loop |
|---|---|---|
| **Ω** | 20.0% | 32.9% |
| **What it answers** | What does the engine say about itself? | What does it say when it can see its own dynamics? |
| **Invariant under** | External re-evaluation | Internal self-knowledge |
| **Difference** | — | +12.9% = epistemic value of self-awareness |

---

## How to Run

```bash
# Self-application (100 passes, ~40 min)
cd engine && python3 ../scripts/self_application/self_application.py

# Meta-recursion tower (10 levels, ~35 min)
cd engine && python3 ../scripts/meta_recursion/meta_recursion.py

# Recursive loop (100 passes, ~10 min)
cd engine && python3 ../scripts/meta_recursion/recursive_loop.py
```

All scripts expect `cqim_v14_engine.py` and `quotient.py` to be importable from the working directory or `sys.path`.

---

## License

Copyright 2026 Nathan Robert Rietmann, Rietmann Intelligence LLC. All rights reserved.
