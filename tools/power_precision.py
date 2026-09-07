#!/usr/bin/env python3
"""Prospective arithmetic checks, NOT empirical CrossLLM measurements.
Requires scipy. Normal paired-binary planning and exact lineage sign-test power
are distinct calculations and should not be interchanged.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from scipy.stats import binom, binomtest, norm

def sign_power(lineages: int, win_probability: float, alpha: float) -> float:
    """Exact two-sided binomial sign test under independent non-tied lineages."""
    return float(sum(binom.pmf(k,lineages,win_probability)
                     for k in range(lineages+1)
                     if binomtest(k,lineages,.5).pvalue <= alpha))

def compute() -> dict:
    ci=binomtest(1,6).proportion_ci(method='exact')
    precision=[]
    for rho in [0,.05,.10,.20]:
        de=1+9*rho
        precision.append({'illustrative_n':120,'cases_per_lineage':10,'ICC':rho,
                          'design_effect':de,'effective_n':120/de,
                          'normal_half_width_at_p_0_8':float(norm.ppf(.975)*(.8*.2*de/120)**.5)})
    paired=[]
    for alpha in [.05,.01]:
        n=(norm.ppf(1-alpha/2)+norm.ppf(.8))**2*(.30-.15**2)/.15**2
        paired.append({'alpha':alpha,'power_target':.8,'difference':.15,
                       'discordance':.30,'normal_independent_pairs':float(n),
                       'illustrative_design_effect_1_9_pairs':float(n*1.9),
                       'note':'Not exact power and not the lineage sign-test calculation'})
    return {'status':'PLANNING_CALCULATIONS_AND_SOURCE_ARITHMETIC_ONLY',
            'old_one_miss_in_six_independent_binomial_CI':[ci.low,ci.high],
            'old_twelve_pair_exact_wilcoxon_minimum_two_sided_p':2/2**12,
            'minimum_after_bonferroni_15_under_that_interpretation':15*2/2**12,
            'zero_event_upper_one_sided_95':[
                {'independent_trials':n,'bound':1-.05**(1/n)} for n in [12,20,60,120]],
            'illustrative_precision':precision,'illustrative_paired_binary_planning':paired,
            'lineage_sign_test_power_no_ties':[
                {'lineages':n,'positive_lineage_probability':p,'per_test_alpha':.01,
                 'power':sign_power(n,p,.01)}
                for n in [12,20,24,30,40] for p in [.7,.8,.9]],
            'assumptions':'Independent lineages; no ties in sign-test simulation; '
                          'development estimates needed for the actual design; no inference on real runs.'}

def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path)
    args=parser.parse_args()
    text=json.dumps(compute(),indent=2)
    if args.out:args.out.write_text(text+'\n',encoding='utf-8')
    else:print(text)

if __name__ == '__main__':main()
