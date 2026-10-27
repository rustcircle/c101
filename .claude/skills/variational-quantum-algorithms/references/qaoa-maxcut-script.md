# QAOA MaxCut worked example: script and output

Exact statevector QAOA on `networkx.random_regular_graph(3, 10, seed=7)` with brute force,
Goemans-Williamson (cvxpy) and simulated-annealing baselines. Runs in about 3 s on a laptop.

```bash
uv run --python 3.13 --with numpy --with scipy --with networkx --with cvxpy python qaoa_maxcut.py
```

Versions used for the recorded output: numpy 2.x, scipy, networkx 3.7, cvxpy 1.9.3 (SCS solver).
A different networkx version may generate a different graph for the same seed; check the edge
count and the brute-force optimum first.

```python
import itertools, math, time
import numpy as np, networkx as nx, cvxpy as cp
from scipy.optimize import minimize

G = nx.random_regular_graph(3, 10, seed=7)
n, E = G.number_of_nodes(), list(G.edges())
print("edges", len(E))

# cost diagonal: number of cut edges for every bitstring (qubit i = bit i of the index)
idx = np.arange(2**n)
bits = (idx[:, None] >> np.arange(n)) & 1
C = np.zeros(2**n)
for i, j in E:
    C += bits[:, i] ^ bits[:, j]
Cmax = C.max(); n_opt = int((C == Cmax).sum())
print("brute-force max cut", Cmax, "optimal strings", n_opt)

def apply_mixer(psi, beta):
    # e^{-i beta X} on every qubit = cos(beta) I - i sin(beta) X
    psi = psi.reshape([2] * n)
    c, s = math.cos(beta), -1j * math.sin(beta)
    for q in range(n):
        ax = n - 1 - q
        a = np.take(psi, 0, axis=ax); b = np.take(psi, 1, axis=ax)
        psi = np.stack([c * a + s * b, s * a + c * b], axis=ax)
    return psi.reshape(-1)

def state(params):
    p = len(params) // 2
    g, b = params[:p], params[p:]
    psi = np.full(2**n, 2 ** (-n / 2), dtype=complex)
    for l in range(p):
        psi = np.exp(-1j * g[l] * C) * psi
        psi = apply_mixer(psi, b[l])
    return psi

def F(params):
    psi = state(params)
    return float(np.real(np.vdot(psi, C * psi)))

# p = 1 grid search
gs = np.linspace(0, np.pi, 121); bs = np.linspace(0, np.pi / 2, 61)
grid = np.array([[F([g, b]) for b in bs] for g in gs])
k = np.unravel_index(grid.argmax(), grid.shape)
x0 = np.array([gs[k[0]], bs[k[1]]])
res = minimize(lambda x: -F(x), x0, method="BFGS")
best = {1: res.x}
def report(p, x):
    psi = state(x); prob = np.abs(psi) ** 2
    Fp = F(x); P_opt = prob[C == Cmax].sum()
    shots99 = math.ceil(math.log(0.01) / math.log(1 - P_opt))
    print(f"p={p} gamma={np.round(x[:p],4)} beta={np.round(x[p:],4)} F={Fp:.4f} ratio={Fp/Cmax:.4f} P(opt)={P_opt:.4f} shots_99={shots99}")
report(1, res.x)

def interp(v):
    p = len(v); out = np.zeros(p + 1)
    for i in range(1, p + 2):  # 1-based as in Zhou et al. 2020
        left = v[i - 2] if i - 2 >= 0 else 0.0
        right = v[i - 1] if i - 1 < p else 0.0
        out[i - 1] = (i - 1) / p * left + (p - i + 1) / p * right
    return out

for p in (2, 3):
    prev = best[p - 1]; q = p - 1
    x0 = np.concatenate([interp(prev[:q]), interp(prev[q:])])
    res = minimize(lambda x: -F(x), x0, method="BFGS")
    best[p] = res.x
    report(p, res.x)

# Goemans-Williamson SDP
X = cp.Variable((n, n), PSD=True)
obj = cp.Maximize(sum(0.5 * (1 - X[i, j]) for i, j in E))
prob = cp.Problem(obj, [cp.diag(X) == 1])
prob.solve()
print("GW SDP bound", round(prob.value, 4), "solver", prob.solver_stats.solver_name)
w, V = np.linalg.eigh(X.value); w = np.clip(w, 0, None)
L = V * np.sqrt(w)
rng = np.random.default_rng(7)
cuts = []
for _ in range(1000):
    r = rng.normal(size=n); s = np.sign(L @ r); s[s == 0] = 1
    cuts.append(sum(s[i] != s[j] for i, j in E))
cuts = np.array(cuts)
print("GW rounding: mean cut", cuts.mean().round(3), "best", cuts.max(), "P(hit optimum)", (cuts == Cmax).mean())

# simulated annealing baseline (single spin flip, Metropolis)
def sa(seed, sweeps=200, T0=2.0, T1=0.05):
    rng = np.random.default_rng(seed)
    s = rng.integers(0, 2, n); nbrs = [list(G.neighbors(v)) for v in range(n)]
    cut = sum(s[i] != s[j] for i, j in E); best = cut
    for t in range(sweeps):
        T = T0 * (T1 / T0) ** (t / (sweeps - 1))
        for v in rng.permutation(n):
            d = sum(1 if s[v] == s[u] else -1 for u in nbrs[v])  # change in cut if v flips
            if d >= 0 or rng.random() < math.exp(d / T):
                s[v] ^= 1; cut += d; best = max(best, cut)
    return best
sa_best = [sa(s) for s in range(100)]
print("SA: best", max(sa_best), "fraction of 100 restarts hitting optimum", np.mean(np.array(sa_best) == Cmax))
```

Recorded output:

```text
edges 15
brute-force max cut 13.0 optimal strings 2
p=1 gamma=[0.5882] beta=[0.3651] F=10.0783 ratio=0.7753 P(opt)=0.0378 shots_99=120
p=2 gamma=[0.5083 0.9205] beta=[0.5077 0.2815] F=11.0634 ratio=0.8510 P(opt)=0.1389 shots_99=31
p=3 gamma=[0.4358 0.8697 1.0026] beta=[0.5386 0.4085 0.2306] F=11.7161 ratio=0.9012 P(opt)=0.3135 shots_99=13
GW SDP bound 13.1015 solver SCS
GW rounding: mean cut 12.164 best 13 P(hit optimum) 0.515
SA: best 13 fraction of 100 restarts hitting optimum 1.0
```

## Notes for adapting it

- Qubit i is bit i of the basis-state index (little-endian, as in Qiskit). `C` is the diagonal of
  the cost operator, so `exp(-1j * g * C) * psi` is the whole phase-separation layer.
- The mixer applies cos(b) I - i sin(b) X on each qubit by slicing the state tensor; it is
  exact for any n that fits in memory (16 bytes x 2^n).
- `interp` implements INTERP with 1-based indices exactly as in Zhou et al. (PRX 2020).
- `shots_99` is the number of samples needed to see an optimal string with probability 0.99
  given the exact per-sample probability; with hardware noise P(opt) drops and the count rises.
- For a weighted graph, multiply each edge term in `C` by its weight and rescale the gamma grid;
  the gamma period is no longer 2pi unless all weights are integers.
- Swap `nx.random_regular_graph` for `nx.petersen_graph()` to check the p = 1 triangle-free
  formula: F(arctan(1/sqrt 2), pi/8) = 10.3868 = 15 x 0.6925 (max cut 12).
