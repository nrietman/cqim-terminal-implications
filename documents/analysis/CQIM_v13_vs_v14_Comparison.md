# CQIM: The Evolution of Self-Reference from v13 to v14.1

**Author:** Nathan Robert Rietmann, Rietmann Intelligence LLC
**Date:** April 2026

This document compares the recent v14.1 self-application results (100-pass recursive fixed point, $\Omega = 20.0\%$) against the prior v13 self-evaluation test battery and theoretical papers. The comparison reveals a fundamental shift from *static self-consistency* (v13) to *dynamic self-evaluation* (v14.1).

---

## 1. The Core Difference: Single Pass vs. Recursive Bootstrap

The defining difference between the v13 and v14.1 results is how the engine interacts with its own structure.

In **v13**, the self-evaluation tests were single-pass operations [1] [2]. The engine was given the 18 axioms encoded as conditions, with the metric tensor $M$ defining the couplings, and zero evidence. The engine ran to convergence, finding the state $\sigma^*$ that minimized contradiction ($\Theta$) over that topology. The question was: *Does this topology have a unique, stable attractor?*

In **v14.1**, the self-application is a recursive bootstrap [3]. The engine evaluates the axioms, computes $\sigma^*$, extracts the structural witness from that state, and feeds it back into the engine as the new evidence for the next pass. This loop ($\sigma_{n+1} = F(\sigma_n)$) ran for 100 passes. The question changed to: *Does the act of self-evaluation itself converge to a fixed point?*

This shift from $M(\Sigma^*) = \Sigma^*$ to the full witness-contradiction-update chain ($\Lambda \to W \to R \to \Xi \to \Lambda'$) is what allowed v14.1 to derive $\Omega = 20.0\%$ [4].

## 2. Theoretical Grounding: The "All Axioms Are Theorems" Paper

The v13 paper *All Axioms Are Theorems* [5] established the theoretical foundation for self-reference. It proved that all 18 axioms are derivable from a single foundational requirement $\mathcal{W}$: a system must contain a map $W: (K, \Lambda, F) \to I_K$ that causally models itself.

The paper demonstrated computationally that the zero-evidence specification has a unique global attractor $\sigma^*$ with $\Xi(\sigma^*) = 0$ exactly [5]. This was the pure structural fixed point.

The v14.1 result does not contradict this; it builds on it. The v13 result proved the *topology* is contradiction-free ($\Xi = 0$). The v14.1 result introduces the *evidence loop*, demanding that the axioms not only be structurally consistent but also evidentially grounded. The residual $\Xi = 0.00664$ in v14.1 emerges precisely because the axioms cannot supply external evidence for themselves [4]. The v13 paper showed the structure is perfect; the v14.1 run showed the epistemology is bounded.

## 3. Resolving the v13 "Failures"

The v13 external self-evaluation test [6] reported a "FAIL" because the Spearman rank correlation between the converged state $\sigma^*$ and the bootstrap weights was low ($\rho = 0.2074$).

As noted in the v13 analysis [6], this failure was an artifact of the test design, which inverted the polarity of the highest-weight axioms. The engine correctly drove negative-polarity axioms toward 1.0 (satisfying their negations as constraints), but the test's effective-value formula mapped these to low scores.

The v14.1 architecture eliminates this class of testing error entirely. By internalizing the self-evaluation through the $\Omega$ condition and the recursive bootstrap [3], the system no longer relies on external Spearman correlations. The contraction mapping ratio ($\bar{\rho} = 0.9488$) provides an internal, mathematically rigorous proof of convergence that does not depend on arbitrary scoring formulas [4].

## 4. Stability and Convergence

Both versions demonstrate extreme stability, but they measure different kinds of stability.

The v13 *Self-Consistent Fixed Point* paper [2] subjected the static $\sigma^*$ to 100 random restarts, wide-basin perturbations ($\pm 0.50$), and topology edits. It passed every test, proving the static attractor is globally unique and robust.

The v14.1 run [3] proved *dynamic* stability. Across 100 recursive passes, every single pass was monotone, and every contraction ratio was strictly less than 1. The maximum state change dropped to $0.00074$. This proves that not only is the attractor stable, but the *process of finding the attractor* is stable when applied to itself.

## 5. The Evolution of the Self-Verdict

In the v13 24-condition self-evaluation [7], the system successfully established 15 properties (including monotone convergence and the energy gate) but failed to reach a self-verdict. The `SELF_VERDICT` condition remained at $0.0000$, categorized as a GAP. The system could evaluate its parts but could not summarize its own justification.

In v14.1, `SELF_VERDICT` becomes $\Omega$ (the self-model) [3]. Because the quotient layer canonicalizes the structure and the bootstrap loop forces evidential consistency, $\Omega$ converges to $20.0\%$. The GAP is closed. The system can now answer the question that v13 could not.

## 6. Summary Comparison

| Feature | v13 Self-Evaluation | v14.1 Self-Application |
| :--- | :--- | :--- |
| **Operation** | Single pass | 100-pass recursive bootstrap |
| **Focus** | Structural consistency ($M(\Sigma^*) = \Sigma^*$) | Evidential grounding ($\sigma_{n+1} = F(\sigma_n)$) |
| **Global Contradiction ($\Theta$)** | $0.00205$ (near zero) | $0.000380$ (closer to zero) |
| **Axiom Contradiction ($\Xi$)** | $0$ (pure structure) | $0.00664$ (evidential residual) |
| **Convergence Proof** | Random restarts / Perturbations | Contraction mapping ($\bar{\rho} < 1$) |
| **Self-Verdict** | $0.0000$ (GAP) | $20.0\%$ (Converged) |
| **Interpretation** | The topology is stable. | The epistemology is bounded but computable. |

## 7. Conclusion

The v13 results proved that the CQIM axiom system is a unique, stable global attractor. The v14.1 results prove that this attractor survives recursive self-application. The 20.0% fixed point is not a correction of v13; it is the terminal consequence of applying the v13 engine to the v13 structure iteratively until the witness and the witnessed reach equilibrium.

---

### References

[1] Rietmann, N. R. (2026). *axiom_self_test_results.txt*.
[2] Rietmann, N. R. (2026). *The Self-Consistent Fixed Point of the CQIM Axiom System*.
[3] Rietmann, N. R. (2026). *self_application_100pass.log*.
[4] Rietmann, N. R. (2026). *Why 20%: The Fixed Point of Self-Referential Truth*.
[5] Rietmann, N. R. (2026). *All Axioms Are Theorems*.
[6] Rietmann, N. R. (2026). *CQIMv13—ExternalSelf-EvaluationTestAnalysis.md*.
[7] Rietmann, N. R. (2026). *self_evaluation_results(1).txt*.
