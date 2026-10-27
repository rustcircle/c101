# Trainability checks: shift rules and barren-plateau scan

One numpy script (no quantum SDK needed) that (1) checks parameter-shift rules against central
finite differences and (2) measures the variance of a gradient component against n for a
hardware-efficient ansatz with a global and a local cost. Runs in about 2 s.

```bash
uv run --python 3.13 --with numpy python bp_shift.py
```

```python
import numpy as np, math
rng = np.random.default_rng(1)

# ---------- parameter-shift checks ----------
X = np.array([[0, 1], [1, 0]], complex); Y = np.array([[0, -1j], [1j, 0]]); Z = np.diag([1., -1.]).astype(complex); I2 = np.eye(2)
def expm_herm(Hm, t):  # exp(-i t Hm)
    w, V = np.linalg.eigh(Hm); return (V * np.exp(-1j * t * w)) @ V.conj().T
def rand_state(d):
    v = rng.normal(size=d) + 1j * rng.normal(size=d); return v / np.linalg.norm(v)
def rand_herm(d):
    A = rng.normal(size=(d, d)) + 1j * rng.normal(size=(d, d)); return (A + A.conj().T) / 2
# two-term rule, gate exp(-i theta X/2) on qubit 0 of 2
psi, O = rand_state(4), rand_herm(4)
Gx = np.kron(X / 2, I2)
f = lambda t: np.real(np.vdot(expm_herm(Gx, t) @ psi, O @ expm_herm(Gx, t) @ psi))
th = 0.37; fd = (f(th + 1e-6) - f(th - 1e-6)) / 2e-6
ps2 = (f(th + np.pi / 2) - f(th - np.pi / 2)) / 2
print("two-term:", ps2, "finite diff:", fd, "diff", abs(ps2 - fd))
# four-term rule, controlled RX: generator |1><1| (x) X/2, eigenvalues {0,0,+1/2,-1/2}
Gc = np.kron(np.diag([0., 1.]), X / 2)
f = lambda t: np.real(np.vdot(expm_herm(Gc, t) @ psi, O @ expm_herm(Gc, t) @ psi))
fd = (f(th + 1e-6) - f(th - 1e-6)) / 2e-6
dp, dm = (math.sqrt(2) + 1) / (4 * math.sqrt(2)), (math.sqrt(2) - 1) / (4 * math.sqrt(2))
ps4 = dp * (f(th + np.pi / 2) - f(th - np.pi / 2)) - dm * (f(th + 3 * np.pi / 2) - f(th - 3 * np.pi / 2))
print("four-term:", ps4, "finite diff:", fd, "diff", abs(ps4 - fd))
ps2_wrong = (f(th + np.pi / 2) - f(th - np.pi / 2)) / 2
print("two-term applied to CRX (wrong):", ps2_wrong, "error", abs(ps2_wrong - fd))

# ---------- barren-plateau variance scan ----------
def ry_layer(psi, n, thetas):
    psi = psi.reshape([2] * n)
    for q in range(n):
        c, s = math.cos(thetas[q] / 2), math.sin(thetas[q] / 2)
        a = np.take(psi, 0, axis=q); b = np.take(psi, 1, axis=q)
        psi = np.stack([c * a - s * b, s * a + c * b], axis=q)
    return psi.reshape(-1)
def cz_ladder_diag(n):
    idx = np.arange(2 ** n); bits = (idx[:, None] >> (n - 1 - np.arange(n))) & 1   # qubit 0 = most significant
    sign = np.ones(2 ** n)
    for q in range(n - 1): sign *= 1 - 2 * (bits[:, q] & bits[:, q + 1])
    return sign, bits
def costs(theta, n, L, sign, bits):
    psi = np.zeros(2 ** n); psi[0] = 1.0
    th = theta.reshape(L, n)
    for l in range(L):
        psi = ry_layer(psi, n, th[l]); psi = sign * psi
    p = np.abs(psi) ** 2
    glob = 1 - p[0]                                   # 1 - |<0|psi>|^2
    loc = 1 - np.mean([(p * (1 - bits[:, q])).sum() for q in range(n)])  # 1 - (1/n) sum_j P(q_j = 0)
    return glob, loc
def grad_var(n, L, samples=200):
    sign, bits = cz_ladder_diag(n)
    g_glob, g_loc = [], []
    for _ in range(samples):
        th = rng.uniform(0, 2 * np.pi, n * L)
        k = 0  # first parameter (qubit 0, layer 0)
        tp, tm = th.copy(), th.copy(); tp[k] += np.pi / 2; tm[k] -= np.pi / 2
        cp_, cm_ = costs(tp, n, L, sign, bits), costs(tm, n, L, sign, bits)
        g_glob.append((cp_[0] - cm_[0]) / 2); g_loc.append((cp_[1] - cm_[1]) / 2)
    return np.var(g_glob), np.var(g_loc)
print("n  L  Var_global  Var_local")
for L_rule in ("L=n", "L=3"):
    for n in (2, 4, 6, 8, 10, 12):
        L = n if L_rule == "L=n" else 3
        vg, vl = grad_var(n, L)
        print(f"{n:2d} {L:2d}  {vg:.3e}  {vl:.3e}")
```

Recorded output:

```text
two-term: -0.5191373893709044 finite diff: -0.519137389409785 diff 3.888067645618776e-11
four-term: -0.1626000526172061 finite diff: -0.16260005256119037 diff 5.6015719840374345e-11
two-term applied to CRX (wrong): -0.2150560705690798 error 0.05245601800788943
n  L  Var_global  Var_local
 2  2  4.141e-02  3.175e-02
 4  4  3.582e-03  5.273e-03
 6  6  2.188e-04  1.558e-03
 8  8  1.338e-05  8.135e-04
10 10  1.581e-06  4.110e-04
12 12  2.813e-07  2.550e-04
 2  3  4.704e-02  3.044e-02
 4  3  2.703e-03  5.677e-03
 6  3  6.245e-04  2.247e-03
 8  3  9.154e-05  1.259e-03
10  3  7.563e-06  8.288e-04
12  3  4.562e-07  6.470e-04
```

## Reading the scan

| Quantity | Value | Interpretation |
|---|---|---|
| slope of log10 Var (global, L = 3), n = 4..12 | -0.47 per qubit | exponential decay, about 3x per qubit |
| slope of log10 Var (global, L = n), n = 4..12 | -0.51 per qubit | exponential decay |
| exponent of Var (local, L = 3) against n, n = 4..12 | about -2 | polynomial decay, trainable at this depth |
| shots per gradient component at n = 12, global | 1/Var = 2-4e6 | before any noise |

## Extending the scan

- Use the real initialisation distribution (small-angle, identity blocks, warm start) instead of
  uniform angles; the diagnostic must match how training starts.
- Add a noise channel after each layer (density matrix or trajectories) to see noise-induced
  plateaus: the variance then also decays with depth L at fixed n.
- Compute the dynamical Lie algebra dimension of the generator set (`qp.lie_closure` in
  PennyLane, or your own commutator closure over Pauli strings) and plot Var against 1/dim g.
- Keep the sample count at 200 or more: the variance estimate of a heavy-tailed gradient
  distribution is itself noisy (relative error about sqrt(2/(N - 1)) for Gaussian data, worse
  otherwise).
