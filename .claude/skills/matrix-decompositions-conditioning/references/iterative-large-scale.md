# Iterative and large-scale recipes

Run each block with one command (cwd does not persist between calls):

```bash
uv run -q --python 3.13 --with numpy --with scipy --with pyamg --with scikit-learn python -I <out_dir>/recipe.py
```

`--python 3.13` (also the stack's `UV_PYTHON`) matters here: pyamg 5.3 publishes no CPython 3.14 wheels
(checked October 2026).

Numbers below were measured October 2026 (NumPy 2.5, SciPy 1.18, pyamg 5.3, scikit-learn 1.9).

## 1. Preconditioned Krylov solves with iteration counts

```python
import numpy as np, pyamg, scipy.sparse.linalg as sla
A = pyamg.gallery.poisson((100, 100), format="csr")          # 2-D Laplacian, n = 10_000, SPD
b = np.ones(A.shape[0])
def run(solver, **kw):
    it = [0]
    x, info = solver(A, b, rtol=1e-8, callback=lambda *_: it.__setitem__(0, it[0] + 1), **kw)
    return it[0], info, np.linalg.norm(b - A @ x) / np.linalg.norm(b)   # true relative residual
print("cg          ", run(sla.cg))                                         # 187 iterations
amg = pyamg.smoothed_aggregation_solver(A).aspreconditioner(cycle="V")
print("cg + AMG    ", run(sla.cg, M=amg))                                  # 9 iterations
ilu = sla.spilu(A.tocsc(), drop_tol=1e-4, fill_factor=10)
print("gmres + ILU ", run(sla.gmres, M=sla.LinearOperator(A.shape, ilu.solve), restart=50,
                         callback_type="pr_norm"))                        # 134 inner iterations
```

- `gmres` with `callback_type="pr_norm"` calls back once per inner iteration with the preconditioned
  residual norm; `"x"` once per restart cycle with the iterate.
- AMG suits elliptic PDE matrices (Poisson, diffusion, elasticity); ILU suits mildly non-symmetric
  or non-elliptic matrices; neither is universal. Measure iterations and wall time together: a
  preconditioner that halves iterations but triples the cost per iteration is a loss.
- √κ scaling for CG: 1-D Laplacian with N = 100, 400, 1600 (κ ≈ 4.1e3, 6.5e4, 1.0e6) needed 50, 200,
  800 iterations (rtol 1e-8): iterations ×4 when κ ×16.

## 2. Eigenvalues of large sparse symmetric matrices

```python
import numpy as np, pyamg, scipy.sparse.linalg as sla
A = pyamg.gallery.poisson((60, 60), format="csr").astype(float)
vals_si, _ = sla.eigsh(A, k=5, sigma=0.0, which="LM")         # shift-invert: eigenvalues nearest 0
vals_la, _ = sla.eigsh(A, k=5, which="LA")                      # largest algebraic, no factorisation
rng = np.random.default_rng(0)
X = rng.normal(size=(A.shape[0], 5))
ml = pyamg.smoothed_aggregation_solver(A)
vals_lo, _ = sla.lobpcg(A, X, M=ml.aspreconditioner(), largest=False, tol=1e-8, maxiter=500)
print(np.sort(vals_si), np.sort(vals_lo))                       # agree to ~1e-8
```

- Shift-invert factors A - σI once (sparse LU); use it for interior or smallest eigenvalues.
- LOBPCG needs a good preconditioner and a block size a bit larger than the number wanted; it may
  warn about not reaching `tol` within `maxiter`: check the residual norms it returns with
  `retResidualNormsHistory=True`.
- Generalised problems Ax = λBx: `eigsh(A, k, M=B, sigma=...)` with B SPD; dense: `eigh(A, B)`.

## 3. Randomized SVD with an a posteriori check

```python
import numpy as np
from sklearn.utils.extmath import randomized_svd
rng = np.random.default_rng(0)
m, n = 2000, 1000
U, _ = np.linalg.qr(rng.normal(size=(m, n))); V, _ = np.linalg.qr(rng.normal(size=(n, n)))
s = 1.0 / np.arange(1, n + 1) ** 2                              # fast spectral decay
A = (U * s) @ V.T
Uk, sk, Vtk = randomized_svd(A, n_components=20, n_oversamples=10, n_iter="auto", random_state=0)
# a posteriori error estimate with Gaussian probes (no full SVD needed)
G = rng.normal(size=(n, 10))
R = A @ G - Uk @ (np.diag(sk) @ (Vtk @ G))
est = np.sqrt(np.mean(np.sum(R**2, axis=0)))                    # ≈ ‖A - A_k‖_F for unit-variance probes
print(est, np.sqrt((s[20:]**2).sum()), s[20])                   # 0.0057 0.0062 0.0023
```

With 10 probes the estimate itself scatters by tens of percent (here 0.0057 against the optimal
Frobenius error 0.0062, which the randomized result cannot beat); use 20-50 probes when the
decision is close.

- Accept the factorisation when the estimate is within a small factor of the target accuracy; if not,
  raise `n_oversamples` first, then `n_iter` (scikit-learn's own advice).
- `scipy.sparse.linalg.svds(A, k)` (ARPACK/LOBPCG/PROPACK backends via `solver=`) is deterministic and
  better for a handful of triplets of a sparse matrix.

## 4. Pseudospectrum on a grid

```python
import numpy as np
from scipy.linalg import svdvals
def pseudospectrum(A, re, im):
    n = A.shape[0]; I = np.eye(n)
    return np.array([[svdvals(complex(x, y) * I - A)[-1] for x in re] for y in im])   # σ_min(zI - A)
A = np.diag(np.ones(19), 1) * 1.0 + np.diag(np.full(20, -1.0))   # Jordan-like, eigenvalue -1
re, im = np.linspace(-2.5, 0.5, 121), np.linspace(-1.5, 1.5, 121)
S = pseudospectrum(A, re, im)
# contour levels log10(eps) = -2, -4, -8: region where perturbations of size eps can move eigenvalues
print((S < 1e-8).mean(), (S < 1e-2).mean())                     # fraction of the grid inside each level
```

A normal matrix has ε-pseudospectrum equal to the union of ε-discs around its eigenvalues. Anything
much larger means computed eigenvalues are unreliable at that perturbation level and transient
behaviour (‖exp(tA)‖, ‖A^k‖) can be far from what the eigenvalues predict.

## 5. Julia equivalents (names only; check the package docs for signatures)

| Need | Julia |
|---|---|
| dense factorisations | LinearAlgebra: `lu`, `cholesky`, `bunchkaufman`, `qr`, `svd`, `eigen`, `schur`, `factorize` |
| sparse direct | SparseArrays (UMFPACK, CHOLMOD): `lu(S)`, `cholesky(S)`, `ldlt(S)`, `S \ b` |
| Krylov solvers | Krylov.jl, IterativeSolvers.jl |
| AMG | AlgebraicMultigrid.jl |
| sparse eigenvalues | Arpack.jl, KrylovKit.jl |
| unified solver front end | LinearSolve.jl |
