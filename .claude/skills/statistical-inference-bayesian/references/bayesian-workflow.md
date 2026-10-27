# Bayesian workflow templates

Checked October 2026: PyMC 6.3.2, ArviZ 1.3, NumPyro 0.22, CmdStanPy 1.3 (CmdStan itself must be
installed separately, `cmdstanpy.install_cmdstan()`, and was not run here). One self-contained
command per run, for example
`uv run -q --python 3.13 --with pymc --with arviz --with matplotlib python -I <out_dir>/ab_pymc.py`.

## 1. PyMC (6.x; the model code is unchanged from 5.x)

```python
import arviz as az, numpy as np, pymc as pm
with pm.Model() as model:
    p = pm.Beta("p", alpha=1.0, beta=1.0, shape=2)               # arm A = 0, arm B = 1
    pm.Binomial("y", n=np.array([2400, 2400]), p=p, observed=np.array([120, 150]))
    pm.Deterministic("diff", p[1] - p[0])
    pm.Deterministic("lift", p[1] / p[0] - 1)
    idata = pm.sample_prior_predictive(draws=500, random_seed=1)
    idata.update(pm.sample(1000, tune=1000, chains=4, random_seed=1, target_accept=0.9))
    pm.sample_posterior_predictive(idata, extend_inferencedata=True, random_seed=1)
    pm.stats.compute_log_likelihood(idata)                       # for loo / psense
    pm.stats.compute_log_prior(idata)                            # for psense

print(az.summary(idata, var_names=["p", "diff", "lift"], ci_prob=0.95, ci_kind="hdi"))
ok, report = az.diagnose(idata, return_diagnostics=True, show_diagnostics=False)
divergences = int(idata.sample_stats["diverging"].sum())
p_b_better = float((idata.posterior["diff"] > 0).mean())         # 0.966 with this seed
```

- PyMC 6 returns an xarray `DataTree` (groups `prior`, `prior_predictive`, `posterior`,
  `sample_stats`, `observed_data`, ...); `idata.update(...)` merges groups. PyMC 5 returned
  `arviz.InferenceData` (use `idata.extend(...)` there).
- `pm.sample(..., nuts_sampler="numpyro" | "nutpie" | "blackjax")` swaps the NUTS backend.
- Divergences: increase `target_accept` (0.9 → 0.95 → 0.99) and, for hierarchical models, use the
  non-centred form `theta = mu + tau * z`, `z ~ Normal(0, 1)` instead of `theta ~ Normal(mu, tau)`.

## 2. NumPyro

```python
import arviz as az, jax, jax.numpy as jnp, numpyro, numpyro.distributions as dist
from numpyro.infer import MCMC, NUTS
numpyro.set_host_device_count(4)                                 # before JAX initialises devices
def model(n, y=None):
    p = numpyro.sample("p", dist.Beta(jnp.ones(2), jnp.ones(2)))
    numpyro.sample("y", dist.Binomial(total_count=n, probs=p), obs=y)
    numpyro.deterministic("diff", p[1] - p[0])
mcmc = MCMC(NUTS(model, target_accept_prob=0.9), num_warmup=1000, num_samples=1000, num_chains=4)
mcmc.run(jax.random.PRNGKey(0), jnp.array([2400, 2400]), y=jnp.array([120, 150]))
idata = az.from_numpyro(mcmc)
divergences = int(mcmc.get_extra_fields()["diverging"].sum())
print(az.summary(idata, var_names=["diff"]))                     # P(diff > 0) ≈ 0.973 with this key
```

## 3. CmdStanPy (Stan)

```stan
// ab.stan
data {
  array[2] int<lower=0> n;
  array[2] int<lower=0> y;
}
parameters {
  vector<lower=0, upper=1>[2] p;
}
model {
  p ~ beta(1, 1);
  y ~ binomial(n, p);
}
generated quantities {
  real diff = p[2] - p[1];
  array[2] int y_rep = binomial_rng(n, p);
}
```

```python
from cmdstanpy import CmdStanModel
import arviz as az
model = CmdStanModel(stan_file="ab.stan")
fit = model.sample(data={"n": [2400, 2400], "y": [120, 150]}, chains=4, iter_warmup=1000,
                   iter_sampling=1000, seed=1, adapt_delta=0.9)
print(fit.diagnose())                         # divergences, tree depth, E-BFMI, R-hat, ESS
print(fit.summary())
idata = az.from_cmdstanpy(posterior=fit, posterior_predictive="y_rep")
```

## 4. Diagnostics: what the numbers mean

| Diagnostic | Threshold | If violated |
|---|---|---|
| R-hat (rank-normalised, split) | ≤ 1.01 | chains disagree: run longer, fix multimodality or bad initialisation, reparametrise |
| bulk ESS, tail ESS | ≥ 400 in total (100 per chain for 4 chains) | estimates of centres or intervals are noisy: run longer, reparametrise |
| divergent transitions | 0 | biased posterior in high-curvature regions: raise target_accept, non-centre, rescale |
| max tree depth hits | ≈ 0 | sampler is inefficient (often strong correlations): reparametrise |
| E-BFMI | > 0.3 | poor energy exploration (heavy tails, funnels) |
| MCSE of a reported quantity | ≪ the precision you report | more draws |
| Pareto k (LOO) | < 0.7 | LOO unreliable for those points: moment matching (`az.loo(..., moment_match=True)` needs the model) or K-fold |

## 5. Simulation-based calibration (SBC)

Draw θ̃ from the prior, simulate ỹ, fit, and record the rank of θ̃ among L posterior draws. If the
fitting code is right, the ranks are uniform on {0, ..., L}. Template with an exact (conjugate)
posterior; replace `posterior_draws` with the real sampler call (and thin to roughly independent
draws) to test MCMC code:

```python
import numpy as np
from scipy import stats as st
rng = np.random.default_rng(0)
n, L, sims = 50, 99, 1000
def posterior_draws(y, size):                    # exact Beta(1 + y, 1 + n - y) posterior
    return rng.beta(1 + y, 1 + n - y, size)
ranks = []
for _ in range(sims):
    theta = rng.beta(1, 1)                      # prior draw
    y = rng.binomial(n, theta)                  # simulated data
    ranks.append(int((posterior_draws(y, L) < theta).sum()))
counts = np.bincount(ranks, minlength=L + 1).reshape(20, 5).sum(axis=1)   # 20 bins of 5 ranks
print(st.chisquare(counts).pvalue)              # uniform ranks: p not small (0.63 with this seed)
```

A ∪-shaped rank histogram means the posterior is too narrow (under-dispersed), a ∩ shape too wide,
a slope means bias. ArviZ 1.x plots SBC ranks with `az.plot_ecdf_pit` (default group
`"prior_sbc"`; see its docstring for the expected layout).

## 6. Prior choice checklist

- Put priors on interpretable scales (rates on the log or logit scale, effects in units of the
  outcome's sd) and check them with the prior predictive distribution, not by intuition about the
  parameter alone.
- Weakly informative defaults: Normal(0, 2.5) on standardised regression coefficients, Exponential or
  half-Normal on scales, LKJ(2) on correlation matrices.
- Report a sensitivity analysis whenever the conclusion is close to a decision threshold:
  `az.psense_summary` (power-scaling) or refits under two alternative priors.
