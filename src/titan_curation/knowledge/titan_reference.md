# TITAN Curation Reference (condensed)

TITAN is a two-factor hidden Markov model for tumor sequencing data that jointly
models read depth/log-ratio and allelic counts at germline heterozygous loci.
It infers segmental copy-number alteration (CNA), loss of heterozygosity (LOH),
tumor purity, average ploidy, and cellular prevalence of clonal populations.

Interpretation principles:
- TITAN's numerical optimum (lowest S_Dbw) is evidence, not a final truth.
- Compare the top statistically close candidates, particularly those with
  approximately twofold ploidy differences (classic 2N-high-purity vs
  4N-low-purity ambiguity).
- Purity is 1 - normal contamination when normal contamination is reported.
- Prefer coherent logR centering (copy-neutral population at logR ≈ 0), clean
  segment boundaries, and agreement between CNA states and BAF/LOH patterns.
- Copy-neutral LOH (NLOH) should show allelic imbalance/BAF skew without a
  large logR shift.
- Gains/losses should show compatible logR and BAF patterns.
- Extra subclonal clusters with nearly identical cellular prevalences may
  indicate overfit; prefer the simpler solution.
- Very high segment counts or very high subclonal genome fractions
  (e.g. >50-60%) warrant scrutiny — often a symptom of wrong ploidy/purity
  rather than true biology.
- Ploidy below 1.5 or above 5 requires explicit justification unless external
  evidence supports it.
- If independent purity or ploidy estimates exist, use them as supporting
  evidence, not as an automatic override.
- A statistically "best" S_Dbw pick that also has a markedly worse
  log-likelihood than its peers, a shifted/non-zero logR baseline for its
  claimed neutral state, or a much higher fraction of genome altered/segment
  count than similar candidates should be treated with suspicion rather than
  accepted at face value.
