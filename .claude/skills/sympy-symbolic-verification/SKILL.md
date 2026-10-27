---
name: sympy-symbolic-verification
description: "SymPy for derivations and verification: assumptions, simplification strategies, solveset/nonlinsolve/rsolve/dsolve, calculus and series, exact linear algebra, lambdify and code generation, a rigorous protocol for checking identities, plus mpmath high precision and PSLQ, interval/ball arithmetic, and Z3 for finite or real-arithmetic checks. Load when deriving, simplifying or machine-checking a formula."
when_to_use: "Derive or simplify a closed form; check that two expressions agree or find an exact point where they differ; solve equations, recurrences or ODEs exactly; compute limits, series, sums or integrals with their conditions; do exact linear algebra; turn a formula into numpy, JAX or C code and test it; recognise a numerical constant; or certify an inequality on a box with interval arithmetic or Z3."
---

# SymPy symbolic verification

A computer-algebra result is only as strong as the protocol behind it:

| Evidence | Hub label |
|---|---|
| simplification to 0 under assumptions that match the problem | Proved (CAS-checked), with the assumptions listed |
| a nonzero exact value at an exact point | False, with the point quoted |
| floating-point or sampled agreement | Numerical evidence |

Never upgrade a label. Everything below was run with SymPy 1.14.0 and mpmath 1.3.0.

## 1. Isolated environment and versions

```bash
uv run --python 3.13 --with "sympy==1.14.*" --with mpmath --with python-flint --with z3-solver python check.py
```

- **Print versions** at the top of every script:
  `import sympy, mpmath; print(sympy.__version__, mpmath.__version__)`. Inside a project, add
  dependencies with `uv add --dev sympy`, never pip.
- **SymPy ≥ 1.13: Float and Rational no longer compare equal.** `Float(2.0) == Integer(2)` and
  `S(0.5) == Rational(1, 2)` are both False. Compare with `.equals`, or convert explicitly.
- **Keep Python floats out of symbolic work.** Write `Rational(1, 3)` or `S(1)/3`, never `1/3`.
- **Exact matrices.** `Matrix.to_DM()` gives the fast DomainMatrix (available in 1.14).

## 2. Assumptions

```python
from sympy import symbols, sqrt, log, exp, refine, Q, ask
x = symbols("x"); xr = symbols("x", real=True); xp = symbols("x", positive=True)
sqrt(x**2), sqrt(xr**2), sqrt(xp**2)        # sqrt(x**2), Abs(x), x
log(exp(x)), log(exp(xr))                   # log(exp(x)), x
refine(sqrt(x**2), Q.positive(x))           # x
n = symbols("n", integer=True); ask(Q.even(2*n))   # True
ask(Q.positive(x**2))                       # None: x may be complex, or 0
```

- **Symbols are complex by default.** So sqrt(x²) ≠ x (try x = −1), and log(exp(x)) ≠ x (try
  x = 2πi).
- **Two assumption systems.** The old one, `symbols(..., positive=True)`, drives automatic
  simplification. The new one (`Q`, `ask`, `refine`, `assuming`) is used only by refine and ask,
  not by simplify.
- **Match the problem's domain.** n ∈ ℕ → `integer=True, nonnegative=True`; lengths →
  `positive=True`; real parameters → `real=True`. Assumptions stronger than the problem's domain
  "prove" statements that fail on the excluded part.
- **`posify(expr)`** swaps in positive dummy symbols and returns the map that undoes it.

## 3. Simplification toolbox

| Function | Does | Use when |
|---|---|---|
| `expand` | multiplies out | polynomial identities (canonical for polynomials) |
| `factor` | factors over ℚ; `extension=`, `gaussian=True`, `modulus=p` | roots, sign analysis |
| `cancel` | p/q in lowest terms, expanded | rational functions (canonical: a − b → 0 iff a = b) |
| `apart` | partial fractions | integrals, inverse Laplace, generating functions |
| `together` | one fraction, no cancelling | before `cancel` |
| `trigsimp`, `fu` | trigonometric identities | trigonometric expressions |
| `powsimp`, `powdenest`, `expand_power_base` | combine or split powers | exponents (`force=True` ignores assumptions) |
| `logcombine`, `expand_log` | log a + log b ↔ log ab | valid for positive a, b only |
| `radsimp`, `sqrtdenest` | rationalise; √(5 + 2√6) → √2 + √3 | radicals |
| `gammasimp`, `combsimp` | factorials, binomials, gamma | sums, hypergeometric terms |
| `hyperexpand` | hypergeometric → elementary | after summation or integration |
| `nsimplify` | guesses an exact form for a float | a guess that still needs proof |
| `simplify` | heuristic mix, slow, not canonical | last resort |

- **`force=True` is unsound off the positive reals.** `logcombine(log(x) + log(y), force=True)`
  gives log(xy), but at x = y = −1 the left side is 2πi and log 1 = 0.
  `powsimp(x**a*y**a, force=True)` fails at x = y = −1, a = 1/2.
- **Zero-equivalence is undecidable** for expressions with exp, sin and abs (Richardson). Only
  polynomials (expand) and rational functions (cancel) have canonical forms. A nonzero simplify
  result is therefore not a disproof.

## 4. Solving

- **`solveset` vs `solve`.** `solveset(eq, x, domain=S.Reals)` returns a complete set: an ImageSet
  for periodic families, and a ConditionSet when it gives up. `solve` returns a list and may drop
  solutions: `solve(sin(x), x)` gives [0, pi], while solveset gives {2nπ} ∪ {2nπ + π}.
  `solveset(exp(x) - x - 2, x, S.Reals)` is a ConditionSet: no closed form, so use `nsolve` or
  rewrite with LambertW yourself.
- **`linsolve(eqs, vars)`** returns a parametric FiniteSet; **`nonlinsolve`** handles polynomial
  systems.
- **`groebner(polys, *gens, order="lex")`** triangularises a polynomial system, so the last element
  is univariate. G = [1] proves there is no complex solution (Nullstellensatz). For example,
  x² + y² − 1 and x − y give [x − y, 2y² − 1].
- **Recurrences and ODEs.** `rsolve` for recurrences; `dsolve(eq, f(x), ics=...)` followed by
  `checkodesol(eq, sol)` for ODEs.
- **Substitute every solution back:** `[simplify(eq.subs(x, s)) for s in sols]`.

## 5. Calculus

- **`limit` defaults to dir="+".** `limit(1/x, x, 0)` is oo, `dir="-"` gives −oo, and `dir="+-"`
  gives zoo (no two-sided real limit). Compute both sides whenever the side matters.
- **`series(expr, x, x0, n)`** includes O(x**n). n is an order, not a number of terms; call
  `.removeO()` before reading coefficients.
- **Check `integrate` by differentiating back:** `simplify(diff(F, x) - f) == 0`. Definite
  integrals may come back as Piecewise with convergence conditions: `integrate(exp(-a*x), (x, 0, oo))`
  gives Piecewise((1/a, abs(arg(a)) < pi/2), (Integral(...), True)). Declare
  `a = symbols("a", positive=True)`, or pass `conds="none"` and justify the condition yourself.
- **Sums and products.** `Sum(1/k**2, (k, 1, oo)).doit()` gives pi**2/6; use `summation` for closed
  forms, `Product(...).doit()`, and `Sum(...).is_convergent()`.
- **Interchanges are unchecked.** Swapping a limit, sum and integral needs a theorem (dominated or
  monotone convergence, Fubini), and SymPy does not check it.

## 6. Exact linear algebra

```python
from sympy import Matrix
M = Matrix([[1, 2, 3], [4, 5, 6], [7, 8, 10]])
M.rref()                      # (identity, (0, 1, 2))
M.nullspace()                 # []
M.charpoly().as_expr()        # lambda**3 - 16*lambda**2 - 12*lambda + 3
M.det(method="bareiss")       # -3
dM = M.to_DM(); dM.domain     # ZZ: DomainMatrix is much faster for large exact matrices
```

- Enter data as Integer or Rational. With Float entries, `rref` and `nullspace` pivot on rounding
  noise.
- Exact eigendecompositions are practical only for small sizes, since they need the roots of the
  characteristic polynomial. Use numpy/scipy for numerical matrices
  (`matrix-decompositions-conditioning`).
- DomainMatrix over ZZ, QQ or a polynomial ring keeps intermediate entries small.

## 7. Identity-checking protocol

To show a = b:

1. Declare assumptions that match the problem's domain (section 2).
2. Set d = a − b. Try the canonical route first: `expand(d)` for polynomials, `cancel(d)` for
   rational functions. Otherwise try `simplify(d)`, `trigsimp`, `d.rewrite(exp)`, or
   `expand(d, complex=True)` for the real and imaginary parts.
3. `simplify(d) == 0` proves the identity under the declared assumptions. Label it Proved
   (CAS-checked) and list the assumptions.
4. A nonzero result proves nothing. `d.equals(0)` returns True, False or None, and None means
   undecided: `sqrt(x**2).equals(x)` is None for complex x.
5. Substitute exact random rationals, `d.subs({x: Rational(p, q), ...})`, and evaluate exactly. A
   nonzero value at an exact point disproves the identity (label False; quote the point). A float
   value is only a hint.
6. Evaluation can also be a proof:
   - univariate: if d = P/Q with deg P ≤ D, vanishing at D + 1 distinct points where Q ≠ 0
     proves d ≡ 0;
   - multivariate polynomial with degree ≤ D_i in x_i: vanishing on a grid S_1 × ... × S_k with
     |S_i| ≥ D_i + 1 proves P ≡ 0;
   - Schwartz-Zippel: for P ≢ 0 of total degree D and points drawn uniformly from S^k,
     Pr[P(r) = 0] ≤ D/|S|, so t independent zero results leave error probability ≤ (D/|S|)^t.
     Label this "probabilistic check (error ≤ ...)", never Proved.

## 8. Code generation

```python
from sympy import lambdify, cse, ccode, fcode, symbols, sin, cos
x = symbols("x")
f = lambdify(x, sin(x)**2 + cos(x)*sin(x), modules="numpy")   # modules="jax" also works (JaxPrinter)
cse([sin(x)**2 + cos(x)*sin(x), cos(x)*sin(x)])               # ([(x0, sin(x)), (x1, x0*cos(x))], [x0**2 + x1, x1])
ccode(sin(x)**2, assign_to="y")                                # 'y = pow(sin(x), 2);'
fcode(sin(x)**2, standard=2003, source_format="free")          # 'sin(x)**2'
```

- **Test generated code against the expression.** Evaluate `expr.evalf(30, subs={x: v})` at random
  v and compare with an rtol justified by conditioning (`numerical-error-analysis`).
- **lambdify divides in floating point.** With n = 10, (n(n+1)/2)² returns 3025.0. That is exact
  only below 2⁵³; for exact checks use `modules="sympy"` or integer arithmetic.
- **Whole routines.** `sympy.utilities.codegen.codegen` emits complete C or Fortran routines with
  headers.

## 9. Performance

- **Expression swell.** Keep polynomials as `Poly(expr, x, domain="QQ")` or in sparse rings
  (`from sympy import ring, QQ; R, x, y = ring("x,y", QQ)`); both are far faster than Expr
  arithmetic.
- **Targeted calls.** Use `cancel`, `factor` or `expand`, not `simplify`, and never call simplify
  inside a loop. Lambdify once instead of calling `subs` in a loop. Avoid symbolic matrices of
  floats.
- **Time-box risky calls** (integrate, simplify, solve) in a subprocess. macOS has no GNU `timeout`.
  With the spawn start method (macOS, Windows), run this under `if __name__ == "__main__":`.

```python
import multiprocessing as mp
def _work(q, s):
    from sympy import integrate, sympify, Symbol
    q.put(str(integrate(sympify(s), Symbol("x"))))
def with_timeout(s, seconds=30):
    q = mp.Queue(); p = mp.Process(target=_work, args=(q, s)); p.start(); p.join(seconds)
    if p.is_alive():
        p.terminate(); return None        # report "timed out", never "no closed form"
    return q.get()                        # fine for results up to a few kB
```

## 10. High precision and constant recognition

```python
from mpmath import mp, quad, log, pi, pslq, identify, nsum, inf
mp.dps = 50
v = quad(lambda t: log(1 + t)/(1 + t**2), [0, 1])
pslq([v, pi*log(2)], maxcoeff=1000, maxsteps=10**5)    # [-8, 1], i.e. 8v = pi*log(2)
identify(v, ["pi*log(2)"])                              # '((1/8)*pi*log(2))'
identify(nsum(lambda k: 1/k**2, [1, inf]), ["pi**2"])   # '((1/6)*pi**2)'
```

- **Two precisions.** Compute at mp.dps = 50 and again at 80. A real relation persists with the same
  small coefficients; one that changes, or has coefficients near maxcoeff, is noise.
- **Label.** "Numerical evidence (PSLQ at 80 digits, coefficients ≤ 10³)". The example happens to be
  a theorem: ∫₀¹ log(1+t)/(1+t²) dt = (π/8) log 2, proved with t = tan θ and θ → π/4 − θ. Without
  such a proof, the PSLQ result stays evidence.
- **Inputs from strings:** `mpf("0.1")`, never float literals.

## 11. Rigorous numerics and solvers

Proof by interval bisection that eˣ − x² − x > 0 on [0, 2] (closes with 21 boxes):

```python
from mpmath import iv
iv.dps = 20
F = lambda X: iv.exp(X) - X**2 - X
def positive_on(lo, hi, depth=0):
    if F(iv.mpf([lo, hi])).a > 0:           # .a is the lower end of the enclosure
        return True
    if depth >= 40:
        return False                         # unresolved: report the box, not a counterexample
    mid = (lo + hi) / 2
    return positive_on(lo, mid, depth + 1) and positive_on(mid, hi, depth + 1)
positive_on(0, 2)                            # True: proved, modulo the interval library
```

- **Overestimation.** Natural interval extensions overestimate (the dependency problem: X − X ≠ 0),
  so tight inequalities need many boxes or a better form (mean-value form, Taylor models). Where
  equality holds (a tangency), bisection never closes: prove that neighbourhood separately, by hand
  or by monotonicity.
- **python-flint `arb`** gives rigorous high precision: `from flint import arb, ctx; ctx.prec = 200`.
  Comparisons are True only when certain, so False means "not proved".
- **Z3** handles bounded integers and polynomial real arithmetic:

```python
from z3 import Real, Int, Solver, And
x = Real("x"); s = Solver(); s.add(x**2 - x + 1 <= 0); s.check()     # unsat: x^2 - x + 1 > 0 on R
n = Int("n"); s = Solver(); s.add(And(n >= 0, n <= 100), n*n + n + 41 == 41*43)
s.check(), s.model()                                                   # sat, [n = 41]
```

  Assert the negation of the claim. unsat proves the encoded statement (nlsat is complete for
  polynomial real arithmetic). sat returns a model to recheck exactly. unknown means unknown; it is
  typical for nonlinear integer arithmetic, which is undecidable. Z3's Real is exact real
  arithmetic, not floating point.
- **OEIS lookup** (handles both JSON shapes of the API):

```bash
curl -s "https://oeis.org/search?q=1,1,2,5,14,42,132,429&fmt=json" | python3 -c "import json,sys; d=json.load(sys.stdin); r=d.get('results') if isinstance(d,dict) else d; print([('A%06d' % x['number'], x['name']) for x in (r or [])[:3]])"
```

## 12. Worked example: Σ_{k=1}^n k³ = (n(n+1)/2)²

1. **Derive.**

```python
from sympy import symbols, summation, factor, simplify, lambdify
k, n = symbols("k n", integer=True, positive=True)
S = summation(k**3, (k, 1, n)); factor(S)            # n**2*(n + 1)**2/4
assert simplify((n*(n + 1)/2)**2 - ((n - 1)*n/2)**2 - n**3) == 0   # the induction step
```

2. **Prove by degree.** S(n) = Σ_{k≤n} k³ is a polynomial of degree 4 in n (its forward difference
   (n+1)³ is a cubic; Faulhaber), and so is (n(n+1)/2)². Their difference has degree ≤ 4 and
   vanishes at the 5 points n = 0..4 in exact integer arithmetic, so it is identically 0. The
   5-point check is a proof only together with the degree argument. The induction step above, with
   base case n = 1, is a second complete proof.

```python
D = lambda m: sum(j**3 for j in range(1, m + 1)) - (m*(m + 1)//2)**2
assert [D(m) for m in range(5)] == [0, 0, 0, 0, 0]
```

3. **Emit and test code.**

```python
f = lambdify(n, n**2*(n + 1)**2/4, modules="numpy")
assert all(f(m) == sum(j**3 for j in range(1, m + 1)) for m in range(1, 2001))   # values below 2**53
```

   Past n ≈ 1.37·10⁴ the value exceeds 2⁵³ and floats stop being exact; compare in integers there.

Status: Proved (the degree argument with exact evaluation, and the induction identity). The
generated code is Verified against brute force for n ≤ 2000.

## 13. Pitfalls

- **Assumptions too strong or too weak.** positive=True on a merely real variable proves false
  statements; too weak a set blocks valid simplifications.
- **Unsound rewrites.** `force=True`, or `nsimplify` output treated as exact.
- **Lost or unchecked solutions.** `solve` dropping solutions where `solveset` would not, or
  solutions never substituted back.
- **limit's default direction** is "+".
- **Float and Rational mixed.** Python 1/3 inside expressions; in SymPy ≥ 1.13, Float(2.0) != 2.
- **Misread results.** `simplify(d) != 0` taken as a disproof, or `.equals` returning None taken as
  False.
- **Calculus slips.** series' n read as a number of terms; integrate's Piecewise conditions ignored.
- **Generated code.** lambdify's float semantics forgotten, or the code never tested.
- **Overclaimed numerics.** PSLQ relations reported as theorems; an unresolved interval box
  reported as a counterexample.
- **Z3 misread.** unknown reported as unsat, or Z3's Real treated as a float.

Related: `combinatorics-generating-functions`, `ode-pde-analytic-methods`, `numerical-error-analysis`, `lean4-mathlib-formalization`, `inequality-proving`, `adversarial-verification`, hub `mathematics-toolkit`
