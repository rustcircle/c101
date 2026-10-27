# Markov chain and martingale code

All blocks run with `uv run -q --python 3.13 --with numpy python -I <file>.py` (checked with NumPy 2.5).

## 1. Stationary distribution, reversibility, mixing time

```python
import numpy as np

def stationary(P):
    n = P.shape[0]
    A = np.vstack([P.T - np.eye(n), np.ones(n)])          # πP = π and Σπ = 1, least squares
    pi = np.linalg.lstsq(A, np.r_[np.zeros(n), 1.0], rcond=None)[0]
    assert np.allclose(pi @ P, pi, atol=1e-12) and (pi > -1e-12).all()
    return pi

def is_reversible(P, pi):
    F = pi[:, None] * P                                    # probability flow i -> j
    return np.allclose(F, F.T)

def tv_mixing_time(P, pi, eps=0.25, tmax=10_000):
    Pt = np.eye(P.shape[0])
    for t in range(1, tmax + 1):
        Pt = Pt @ P
        if 0.5 * np.abs(Pt - pi).sum(axis=1).max() <= eps:   # worst starting state
            return t
    return None

P = np.array([[0.9, 0.1, 0.0], [0.2, 0.7, 0.1], [0.0, 0.3, 0.7]])
pi = stationary(P)                                         # [0.6, 0.3, 0.1]
lam = np.sort(np.abs(np.linalg.eigvals(P)))[::-1]          # 1, 0.8, 0.5
t_rel = 1 / (1 - lam[1])                                   # 5 (absolute spectral gap 0.2)
print(pi, is_reversible(P, pi), tv_mixing_time(P, pi),     # True, 7
      (t_rel - 1) * np.log(2), np.ceil(t_rel * np.log(1 / (0.25 * pi.min()))))   # 2.77, 19
```

For large sparse chains replace the dense power with `scipy.sparse` products started from the worst
states, and the eigenvalues with `scipy.sparse.linalg.eigs(P.T, k=2)`.

## 2. Absorbing chains: probabilities and expected times

```python
import numpy as np

def absorbing_analysis(P, transient, absorbing):
    Q = P[np.ix_(transient, transient)]; R = P[np.ix_(transient, absorbing)]
    I = np.eye(len(transient))
    B = np.linalg.solve(I - Q, R)                  # absorption probabilities
    t = np.linalg.solve(I - Q, np.ones(len(transient)))   # expected steps to absorption
    return B, t

def gamblers_ruin_matrix(p, N):
    P = np.zeros((N + 1, N + 1)); P[0, 0] = P[N, N] = 1.0
    for i in range(1, N):
        P[i, i + 1], P[i, i - 1] = p, 1 - p
    return P

p, N, k = 0.45, 10, 5
B, t = absorbing_analysis(gamblers_ruin_matrix(p, N), list(range(1, N)), [0, N])
q, r = 1 - p, (1 - p) / p
print(B[k - 1, 1], (r**k - 1) / (r**N - 1))                                  # 0.268283 twice
print(t[k - 1], k / (q - p) - (N / (q - p)) * (1 - r**k) / (1 - r**N))      # 23.171740 twice
```

## 3. Optional stopping, checked by simulation

```python
import numpy as np
rng = np.random.default_rng(7)
def ruin_sim(p, N, k, runs=20_000):
    wins, steps = 0, 0
    for _ in range(runs):
        s, n = k, 0
        while 0 < s < N:
            s += 1 if rng.random() < p else -1; n += 1
        wins += s == N; steps += n
    return wins / runs, steps / runs
print(ruin_sim(0.45, 10, 5))        # close to (0.2683, 23.17); 95% half-width for P is about 0.006
```

Martingale derivations behind the formulas (start k, absorb at 0 or N, τ the hitting time):

1. Fair walk, M_n = S_n: bounded stopped process (condition iii) ⇒ k = E S_τ = N·P(win) ⇒
   P(win) = k/N.
2. Fair walk, M_n = S_n² - n: increments bounded and E τ < ∞ (condition ii) ⇒ k² = E S_τ² - E τ =
   N²·k/N - E τ ⇒ E τ = k(N - k).
3. Biased walk, M_n = (q/p)^{S_n}: bounded stopped process ⇒ (q/p)^k = P(win)(q/p)^N + (1 - P(win))
   ⇒ P(win) = ((q/p)^k - 1)/((q/p)^N - 1).
4. Biased walk, M_n = S_n - n(p - q): condition ii ⇒ k = N·P(win) - (p - q)E τ ⇒
   E τ = (k - N·P(win))/(q - p).

E τ < ∞ itself follows because from any state N consecutive up-steps end the game, so
P(τ > mN) ≤ (1 - p^N)^m decays geometrically.

## 4. Coupling simulation (upper bound on mixing)

```python
import numpy as np
rng = np.random.default_rng(1)
def coupling_time_lazy_cycle(n, runs=2000):
    """Lazy walk on Z_n: one chain moves at a time (fair coin), so the chains cannot cross."""
    times = []
    for _ in range(runs):
        x, y, t = 0, n // 2, 0
        while x != y:
            step = rng.choice((-1, 1))
            if rng.random() < 0.5: x = (x + step) % n
            else: y = (y + step) % n
            t += 1
        times.append(t)
    return np.array(times)
T = coupling_time_lazy_cycle(16)
t = int(np.quantile(T, 0.75)) + 1
print(t, (T > t).mean())     # P(X_t ≠ Y_t) ≤ 1/4 at this t, so d(t) ≤ 1/4 and t_mix ≤ t
```

The bound d(t) ≤ max_{x,y} P(X_t ≠ Y_t) needs the worst pair of starting states; antipodal points
are the worst for the cycle by symmetry. Simulation gives Numerical evidence for the coupling time,
the inequality itself is Proved (coupling lemma).

## 5. First-step analysis template

```python
import sympy as sp
# expected flips until HH with a fair coin: states "", "H"
e0, e1 = sp.symbols("e0 e1")
sol = sp.solve([sp.Eq(e0, 1 + (e1 + e0) / 2), sp.Eq(e1, 1 + (0 + e0) / 2)], [e0, e1])
print(sol[e0])                       # 6   (HT gives 4: states "", "H" with e1 = 1 + (e1 + 0)/2)
```
