# Ising benchmark: script and output

Driver behind the worked example and the 4×4 check in `statmech-monte-carlo` (SKILL.md sections 2 and 11).
Run with `uv run --python 3.13 --with numpy --with scipy --with numba python ising.py`; about two minutes on a 2025 laptop.
It passes a NumPy `Generator` (PCG64 streams from `SeedSequence.spawn`) into `@numba.njit` functions.
The Numba Metropolis sweep here is the loop form of the NumPy checkerboard in SKILL.md; it is used only for the long τ runs.

```python
import math, time
import numpy as np, numba as nb

TC = 2/math.log(1 + math.sqrt(2))
_children = iter(np.random.SeedSequence(20261019).spawn(200))
def new_rng(): return np.random.default_rng(next(_children))

def exact_small(L, T):
    N = L*L; idx = np.arange(2**N, dtype=np.int64)
    s = ((((idx[:, None] >> np.arange(N)) & 1)*2 - 1).astype(np.int8)).reshape(-1, L, L)
    E = -(s*np.roll(s, 1, 1) + s*np.roll(s, 1, 2)).sum((1, 2)).astype(float)
    M = s.sum((1, 2)).astype(float)
    w = np.exp(-(E - E.min())/T); Z = w.sum(); avg = lambda a: (w*a).sum()/Z
    m2, m4 = avg(M**2)/N**2, avg(M**4)/N**4
    return avg(E)/N, avg(np.abs(M))/N, (avg(E**2) - avg(E)**2)/T**2/N, 1 - m4/(3*m2**2)

def metropolis_sweeps(s, beta, nsweeps, rng):
    L = s.shape[0]
    par = (np.add.outer(np.arange(L), np.arange(L)) % 2).astype(bool); masks = (par, ~par)
    acc_tab = np.exp(-beta*np.arange(9))
    E = np.empty(nsweeps); M = np.empty(nsweeps)
    for t in range(nsweeps):
        for mask in masks:
            nbr = np.roll(s, 1, 0) + np.roll(s, -1, 0) + np.roll(s, 1, 1) + np.roll(s, -1, 1)
            dE = 2*s*nbr
            flip = mask & (rng.random(s.shape) < acc_tab[np.maximum(dE, 0)])
            s[flip] *= -1
        M[t] = s.sum(); E[t] = -(s*(np.roll(s, 1, 0) + np.roll(s, 1, 1))).sum()
    return E, M

@nb.njit
def metro_numba(s, beta, nsweeps, rng):
    L = s.shape[0]; a4 = math.exp(-4*beta); a8 = math.exp(-8*beta)
    M = np.empty(nsweeps); E = np.empty(nsweeps)
    for t in range(nsweeps):
        for parity in range(2):
            for i in range(L):
                for j in range((i + parity) % 2, L, 2):
                    nbs = s[(i+1) % L, j] + s[i-1, j] + s[i, (j+1) % L] + s[i, j-1]
                    dE = 2*s[i, j]*nbs
                    if dE <= 0 or rng.random() < (a4 if dE == 4 else a8):
                        s[i, j] = -s[i, j]
        m = 0; e = 0
        for i in range(L):
            for j in range(L):
                m += s[i, j]; e -= s[i, j]*(s[(i+1) % L, j] + s[i, (j+1) % L])
        M[t] = m; E[t] = e
    return E, M

@nb.njit
def wolff_run(s, beta, nclusters, rng, stack):
    L = s.shape[0]; p = 1.0 - math.exp(-2.0*beta)
    M = np.empty(nclusters); E = np.empty(nclusters); C = np.empty(nclusters)
    for t in range(nclusters):
        i = int(rng.random()*L); j = int(rng.random()*L)
        s0 = s[i, j]; s[i, j] = -s0
        stack[0, 0] = i; stack[0, 1] = j; sp = 1; size = 1
        while sp > 0:
            sp -= 1; ci = stack[sp, 0]; cj = stack[sp, 1]
            for d in range(4):
                if d == 0: ni = (ci + 1) % L; nj = cj
                elif d == 1: ni = (ci - 1) % L; nj = cj
                elif d == 2: ni = ci; nj = (cj + 1) % L
                else: ni = ci; nj = (cj - 1) % L
                if s[ni, nj] == s0 and rng.random() < p:
                    s[ni, nj] = -s0
                    stack[sp, 0] = ni; stack[sp, 1] = nj; sp += 1; size += 1
        m = 0; e = 0
        for a in range(L):
            for b in range(L):
                m += s[a, b]; e -= s[a, b]*(s[(a+1) % L, b] + s[a, (b+1) % L])
        M[t] = m; E[t] = e; C[t] = size
    return E, M, C

def tau_int(x, c=5.0):
    x = np.asarray(x, float); x = x - x.mean(); n = len(x)
    f = np.fft.rfft(x, 2*n); acf = np.fft.irfft(f*np.conj(f))[:n]; acf /= acf[0]
    taus = 1 + 2*np.cumsum(acf[1:]); Ms = np.arange(1, n); ok = Ms >= c*taus
    M = int(Ms[np.argmax(ok)]) if ok.any() else n - 1
    return taus[M-1], taus[M-1]*math.sqrt(2*(2*M + 1)/n)

def blocking_error(x):
    x = np.asarray(x, float); errs = []
    while len(x) >= 32:
        errs.append(x.std(ddof=1)/np.sqrt(len(x)))
        x = 0.5*(x[:len(x)//2*2:2] + x[1:len(x)//2*2:2])
    return errs

def binder_jack(M, N, nb_=40):
    m = np.abs(M)/N; n = len(m)//nb_*nb_; m = m[:n].reshape(nb_, -1)
    m2 = (m**2).mean(1); m4 = (m**4).mean(1)
    m2j = (m2.sum() - m2)/(nb_ - 1); m4j = (m4.sum() - m4)/(nb_ - 1)
    return 1 - m4.mean()/(3*m2.mean()**2), 1 - m4j/(3*m2j**2)

def crossing(Ts, Ua, Ub):
    d = Ua - Ub
    for k in range(len(Ts) - 1):
        if d[k]*d[k+1] <= 0: return Ts[k] + (Ts[k+1] - Ts[k])*d[k]/(d[k] - d[k+1])
    return np.nan

t0 = time.time()
e_ex, am_ex, cv_ex, U_ex = exact_small(4, TC)
print(f'Tc={TC:.6f}; 4x4 exact at Tc: e={e_ex:.5f} |m|={am_ex:.5f} cv={cv_ex:.5f} U4={U_ex:.5f}', flush=True)
rng = new_rng(); s = np.ones((4, 4), np.int8)
E, M = metropolis_sweeps(s, 1/TC, 100000, rng); E, M = E[2000:]/16, M[2000:]/16
be = blocking_error(E)
print(f'4x4 NumPy checkerboard: e={E.mean():.5f} +- {max(be):.5f} (naive {be[0]:.5f}) |m|={np.abs(M).mean():.5f} U4={1-np.mean(M**4)/(3*np.mean(M**2)**2):.5f} [{time.time()-t0:.0f}s]', flush=True)
rng = new_rng(); s = np.ones((4, 4), np.int8)
E, M, C = wolff_run(s, 1/TC, 200000, rng, np.empty((16, 2), np.int64)); E, M = E[1000:]/16, M[1000:]/16
print(f'4x4 Wolff: e={E.mean():.5f} +- {max(blocking_error(E)):.5f} U4={1-np.mean(M**4)/(3*np.mean(M**2)**2):.5f}', flush=True)

Ts = np.array([2.25, 2.26, 2.27, 2.28, 2.29]); Ls = (16, 32, 64)
U, Uj, tauW = {}, {}, {}
for L in Ls:
    stack = np.empty((L*L, 2), np.int64)
    for T in Ts:
        rng = new_rng(); s = np.where(rng.random((L, L)) < 0.5, 1, -1).astype(np.int8)
        wolff_run(s, 1/T, 5000, rng, stack)
        E, M, C = wolff_run(s, 1/T, 200000, rng, stack)
        U[L, T], Uj[L, T] = binder_jack(M, L*L)
        if T == 2.27:
            tc_, dtc_ = tau_int(np.abs(M)); tauW[L] = (tc_, tc_*C.mean()/(L*L), C.mean())
    print(f'L={L}: U4 = {[round(U[L, T], 4) for T in Ts]} [{time.time()-t0:.0f}s]', flush=True)
for La, Lb in ((16, 32), (32, 64)):
    Tx = crossing(Ts, np.array([U[La, T] for T in Ts]), np.array([U[Lb, T] for T in Ts]))
    Tk = np.array([crossing(Ts, np.array([Uj[La, T][k] for T in Ts]), np.array([Uj[Lb, T][k] for T in Ts])) for k in range(40)])
    err = math.sqrt(39/40*((Tk - Tk.mean())**2).sum())
    print(f'Binder crossing {La}/{Lb}: T = {Tx:.4f} +- {err:.4f} (jackknife)', flush=True)
for L in Ls: print(f'Wolff T=2.27 L={L}: tau_int(|m|) = {tauW[L][0]:.2f} clusters = {tauW[L][1]:.2f} sweeps, <C>/N = {tauW[L][2]/(L*L):.3f}', flush=True)
res = {}
for L, neq, nsw in ((16, 20000, 500000), (32, 50000, 1000000), (64, 100000, 2000000)):
    rng = new_rng(); s = np.where(rng.random((L, L)) < 0.5, 1, -1).astype(np.int8)
    metro_numba(s, 1/TC, neq, rng)
    t1 = time.time(); E, M = metro_numba(s, 1/TC, nsw, rng)
    tm = tau_int(np.abs(M)); te = tau_int(E); res[L] = tm[0]
    print(f'Metropolis Tc L={L}: tau_int(|m|) = {tm[0]:.1f} +- {tm[1]:.1f}, tau_int(E) = {te[0]:.1f} +- {te[1]:.1f} sweeps ({nsw} sweeps, {time.time()-t1:.0f}s)', flush=True)
Lv = np.array(sorted(res)); print('z from tau_int(|m|), L=16..64:', round(np.polyfit(np.log(Lv), np.log([res[L] for L in Lv]), 1)[0], 3))
print(f'total {time.time()-t0:.0f}s')
```

## Output (October 2026)

```
Tc=2.269185; 4x4 exact at Tc: e=-1.56562 |m|=0.84386 cv=0.78327 U4=0.61720
4x4 NumPy checkerboard: e=-1.56306 +- 0.00248 (naive 0.00161) |m|=0.84257 U4=0.61653 [4s]
4x4 Wolff: e=-1.56344 +- 0.00171 U4=0.61664
L=16: U4 = [0.6209, 0.6169, 0.6119, 0.6056, 0.5995] [10s]
L=32: U4 = [0.6287, 0.6199, 0.6104, 0.598, 0.5848] [23s]
L=64: U4 = [0.6398, 0.6272, 0.61, 0.583, 0.5496] [69s]
Binder crossing 16/32: T = 2.2666 +- 0.0012 (jackknife)
Binder crossing 32/64: T = 2.2695 +- 0.0011 (jackknife)
Wolff T=2.27 L=16: tau_int(|m|) = 4.26 clusters = 2.33 sweeps, <C>/N = 0.547
Wolff T=2.27 L=32: tau_int(|m|) = 6.12 clusters = 2.80 sweeps, <C>/N = 0.457
Wolff T=2.27 L=64: tau_int(|m|) = 8.76 clusters = 3.35 sweeps, <C>/N = 0.383
Metropolis Tc L=16: tau_int(|m|) = 21.1 +- 0.6, tau_int(E) = 11.9 +- 0.3 sweeps (500000 sweeps, 1s)
Metropolis Tc L=32: tau_int(|m|) = 81.4 +- 3.3, tau_int(E) = 37.3 +- 1.0 sweeps (1000000 sweeps, 6s)
Metropolis Tc L=64: tau_int(|m|) = 335.4 +- 19.4, tau_int(E) = 120.1 +- 4.2 sweeps (2000000 sweeps, 49s)
z from tau_int(|m|), L=16..64: 1.996
total 127s
```
