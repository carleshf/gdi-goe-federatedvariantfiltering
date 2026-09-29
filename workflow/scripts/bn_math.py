"""Balding-Nichols beta-binomial likelihood. Standard library only."""
import math


def betaln(a, b):
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


def betabinomial_logpmf(k, n, alpha, beta_param):
    if n == 0: return 0.0 if k == 0 else -math.inf
    log_binom = math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
    return log_binom + betaln(k + alpha, n - k + beta_param) - betaln(alpha, beta_param)


def balding_nichols_log_likelihood(local_ac, local_an, global_p, fst):
    if global_p <= 0.0: return 0.0 if local_ac == 0 else -math.inf
    if global_p >= 1.0: return 0.0 if local_ac == local_an else -math.inf
    theta = (1.0 - fst) / fst
    return betabinomial_logpmf(local_ac, local_an, global_p * theta, (1.0 - global_p) * theta)
