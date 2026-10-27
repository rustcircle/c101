# Certificate and interval scripts

Runnable with one self-contained command (no venv activation; cwd does not persist between calls):

```bash
uv run -q --python 3.13 --with cvxpy --with sympy --with numpy --with scipy --with mpmath \
  --with python-flint python -I <out_dir>/nesbitt_check.py
```

Checked October 2026 with cvxpy 1.9.3 (solvers CLARABEL, SCS, HIGHS, OSQP installed by default),
sympy 1.14.0, mpmath 1.3.0, python-flint 0.9.0, numpy 2.5, scipy 1.18.

## 1. Gram-matrix SOS with exact rounding and projection

```python
import itertools, cvxpy as cp, numpy as np, sympy as sp

def gram_setup(expr, gens, half_deg):
    P = sp.Poly(sp.expand(expr), *gens)
    hom = all(sum(e) == P.total_degree() for e in P.monoms())
    half = [e for e in itertools.product(range(half_deg + 1), repeat=len(gens))
            if (sum(e) == half_deg if hom else sum(e) <= half_deg)]
    pairs = {}
    for i, j in itertools.product(range(len(half)), repeat=2):
        pairs.setdefault(tuple(u + v for u, v in zip(half[i], half[j])), []).append((i, j))
    missing = [e for e in P.as_dict() if e not in pairs]
    assert not missing, f"monomials {missing} cannot be produced: raise half_deg"
    return P, half, pairs

def solve_gram(P, half, pairs, objective="trace"):
    G = cp.Variable((len(half), len(half)), symmetric=True)
    coeffs = dict(P.terms())
    cons = [G >> 0] + [sum(G[i, j] for i, j in ij) == float(coeffs.get(e, 0)) for e, ij in pairs.items()]
    obj = cp.Minimize(cp.trace(G)) if objective == "trace" else cp.Maximize(cp.lambda_min(G))
    prob = cp.Problem(obj, cons); prob.solve(solver=cp.CLARABEL)
    return prob.status, G.value

def round_project(Gv, P, pairs, den):
    """Round to multiples of 1/den, then project exactly onto the coefficient constraints
    (Peyrl-Parrilo). Pair sets of different monomials are disjoint, so the orthogonal projection
    spreads each monomial's residual evenly over its pairs."""
    n = Gv.shape[0]
    G = sp.Matrix(n, n, lambda i, j: sp.Rational(round(Gv[i, j] * den), den))
    G = (G + G.T) / 2
    coeffs = dict(P.terms())
    for e, ij in pairs.items():
        r = sum(G[i, j] for i, j in ij) - sp.Rational(coeffs.get(e, 0))
        for i, j in ij:
            G[i, j] -= r / len(ij)
    return G

def certify(expr, gens, half_deg, dens=(1, 2, 4, 10, 100), objective="trace"):
    P, half, pairs = gram_setup(expr, gens, half_deg)
    status, Gv = solve_gram(P, half, pairs, objective)
    m = sp.Matrix([sp.Mul(*[g**k for g, k in zip(gens, e)]) for e in half])
    for den in dens:
        G = round_project(Gv, P, pairs, den)
        if sp.expand((m.T * G * m)[0] - P.as_expr()) == 0 and G.is_positive_semidefinite:
            return status, den, G, m          # exact certificate: p = m^T G m, G PSD over Q
    return status, None, None, m
```

Rounding strategy (measured):

| Polynomial | Objective | den = 2 | den = 10 | den = 1000 |
|---|---|---|---|---|
| Nesbitt P(x², y², z²) (has zeros, Gram necessarily singular) | min trace | exact, PSD | residual 0 but not PSD | residual 0 but not PSD |
| x⁴ + y⁴ + 1 - x²y - xy² + x² + y² (strictly positive) | max λ_min (0.43) | — | exact, PSD | exact, PSD |

- Strictly positive polynomial: maximise λ_min to get an interior Gram matrix; any reasonable
  rounding then survives the projection.
- Polynomial with real zeros: every feasible Gram matrix is singular (G m(v) = 0 at each zero v).
  Minimise the trace and round coarsely, or remove the monomials forced to vanish (facial
  reduction) and re-solve on the smaller basis.
- `G.is_positive_semidefinite` is exact over ℚ (SymPy); for large matrices an exact LDLᵀ with
  `fractions.Fraction` is faster.
- An explicit decomposition is optional once G is certified; for reading, factor G = Lᵀ D L
  (`G.LDLdecomposition()` needs G positive definite; for singular G restrict to its column space).

## 2. Nesbitt end to end

```python
import sympy as sp
a, b, c = sp.symbols("a b c", positive=True)
lhs = a/(b + c) + b/(c + a) + c/(a + b) - sp.Rational(3, 2)
sos = sp.Rational(1, 2)*sum((u - v)**2/((u + w)*(v + w)) for u, v, w in ((a, b, c), (b, c, a), (c, a, b)))
assert sp.simplify(lhs - sos) == 0                               # SOS identity
P = sp.numer(sp.together(lhs))                                   # 2Σa³ - Σ_sym a²b
assert sp.expand(P - sum((u + v)*(u - v)**2 for u, v in ((a, b), (b, c), (c, a)))) == 0
x, y, z = sp.symbols("x y z", real=True)
status, den, G, m = certify(P.subs({a: x**2, b: y**2, c: z**2}, simultaneous=True), (x, y, z), 3)
print(status, den, G.rank())                                     # optimal 1 6 (integer Gram matrix)
```

## 3. Interval branch-and-bound with a keep-out disc

```python
from mpmath import iv, mpf
iv.dps = 20
E = mpf(1) / 3
def P2(a, b):                       # Nesbitt numerator on a + b + c = 1
    c = 1 - a - b
    return 2*(a**3 + b**3 + c**3) - (a*a*b + a*a*c + b*b*a + b*b*c + c*c*a + c*c*b)
def disc(r):
    return lambda a0, a1, b0, b1: all((u - E)**2 + (v - E)**2 < r*r for u in (a0, a1) for v in (b0, b1))
# bb() as in SKILL.md section 9
for r in ("0.05", "0.02"):
    print(r, bb(P2, disc(mpf(r))))  # (2016, 0, 157) and (12136, 0, 450): certified, failed, excluded
```

Measured on an Apple-silicon laptop: 0.1 s and 0.8 s. With radius 0.01 and minimum width 2^-12,
3054 boxes fail: they lie so close to the zero that the dependency effect of naive interval
evaluation dominates. Remedies, cheapest first: a larger keep-out disc covered by the exact SOS
argument; the mean-value form F(m) + ∇F(X)·(X - m) on small boxes; Taylor models.

python-flint version of one box evaluation (ball arithmetic, rigorous radius tracking):

```python
from flint import arb, ctx
ctx.dps = 30
def P(a, b):
    c = 1 - a - b
    return 2*(a**3 + b**3 + c**3) - (a*a*b + a*a*c + b*b*a + b*b*c + c*c*a + c*c*b)
for (ma, mb), rad in (((0.6, 0.2), 0.01), ((0.3, 0.4), 0.01), ((0.3, 0.4), 0.001)):
    v = P(arb(ma, rad), arb(mb, rad))
    print((ma, mb), rad, v > 0, v.lower(), v.upper())
# (0.6, 0.2) 0.01  True   lower 0.1979  upper 0.3141
# (0.3, 0.4) 0.01  False  (the ball's radius 0.069 swamps the true value 0.014: subdivide)
# (0.3, 0.4) 0.001 True
```

`arb(mid, rad)` builds a ball; `x.lower()`, `x.upper()`, `x.mid()`, `x.rad()` read it back.
Comparisons are three-valued in effect: `x > 0` and `x < 0` are both False for a ball containing 0.
Do not read certification off the printed string: `str(v)` is a decimal enclosure that can be much
looser than the ball (the first ball above prints as `[+/- 0.315]` although it is [0.198, 0.314]).

## 4. Lean file for the polynomial form

```lean
import Mathlib

theorem nesbitt_poly (a b c : ℝ) (ha : 0 ≤ a) (hb : 0 ≤ b) (hc : 0 ≤ c) :
    a^2*b + a^2*c + b^2*a + b^2*c + c^2*a + c^2*b ≤ 2*(a^3 + b^3 + c^3) := by
  nlinarith [mul_nonneg (add_nonneg ha hb) (sq_nonneg (a - b)),
             mul_nonneg (add_nonneg hb hc) (sq_nonneg (b - c)),
             mul_nonneg (add_nonneg hc ha) (sq_nonneg (c - a))]

#print axioms nesbitt_poly
```

Compile under the scratch project described in `lean4-mathlib-formalization`
(`lake env lean Scratch/Nesbitt.lean`); the snippet was not compiled in the session that wrote this
file, so report it as Proved (formal) only after the build succeeds.

## 5. Counterexample hunt template

```python
import numpy as np
from scipy.optimize import minimize
def shapiro(x):
    n = len(x); return sum(x[i]/(x[(i+1) % n] + x[(i+2) % n]) for i in range(n)) - n/2
rng = np.random.default_rng(1)
best = min((minimize(lambda u: shapiro(np.exp(u)), rng.normal(size=14), method="Nelder-Mead",
            options=dict(maxiter=20000, xatol=1e-10, fatol=1e-14)) for _ in range(200)), key=lambda r: r.fun)
print(best.fun)          # about -3.5e-4: candidate; rationalise best.x and recheck with Fraction
```

Then rationalise the point (`fractions.Fraction(float(v)).limit_denominator(10**6)` per
coordinate) and evaluate exactly; only an exact negative value earns the label False. For n = 14 the
rationalised minimiser gives exactly -3.47e-4 < 0 (Fraction arithmetic): False, counterexample.
