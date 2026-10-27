# Lennard-Jones argon in NumPy: script and output

Reproduction of Rahman (1964) behind the worked example in `molecular-dynamics-setup` (SKILL.md section 11).
Velocity Verlet, 864 atoms, LJ truncated and shifted at 2.5σ, Verlet neighbour list from `scipy.spatial.cKDTree` with a 0.3σ skin,
velocity rescaling during equilibration only, NVE production, MSD on unwrapped coordinates, Green-Kubo viscosity from the off-diagonal
pressure tensor and the Yeh-Hummer correction. Runs in about 40 s with `uv run --python 3.13 --with numpy --with scipy python md.py`.

Reading the output: the Green-Kubo running integral has no clean plateau in 60τ, so the worked example uses η* = 2.0 ± 0.4
(the script prints the correction for the 2τ value, 1.875). A production estimate needs 10-100× longer runs or many replicas.

```python
import numpy as np, time
from scipy.spatial import cKDTree
kB = 1.380649e-23; NA = 6.02214076e23
eps = 119.8*kB; sig = 3.405e-10; mass = 39.948e-3/NA
rho_star = 1374.0/mass*sig**3; T_star = 94.4/119.8
N = 864; L = (N/rho_star)**(1/3); V = L**3
tau = np.sqrt(mass*sig**2/eps)
print(f'rho*={rho_star:.4f} T*={T_star:.4f} L={L:.3f} sigma = {L*sig*1e9:.3f} nm, tau={tau*1e12:.4f} ps, eta unit={np.sqrt(mass*eps)/sig**2:.4e} Pa s', flush=True)
rc, skin, dt = 2.5, 0.3, 0.005
ecut = 4*(rc**-12 - rc**-6)
nc = 6; a = L/nc
basis = np.array([[0, 0, 0], [.5, .5, 0], [.5, 0, .5], [0, .5, .5]])
cells = np.array([[i, j, k] for i in range(nc) for j in range(nc) for k in range(nc)], float)
pos = ((cells[:, None, :] + basis[None]).reshape(-1, 3) + 0.25)*a
rng = np.random.default_rng(1964)
vel = rng.normal(0.0, 1.0, (N, 3)); vel -= vel.mean(0)
ndof = 3*N - 3
def temp(v): return (v*v).sum()/ndof
vel *= np.sqrt(T_star/temp(vel))
def build(p):
    q = np.mod(p, L); q[q >= L] = 0.0
    return cKDTree(q, boxsize=L).query_pairs(rc + skin, output_type='ndarray')
def forces(p, pairs):
    i, j = pairs[:, 0], pairs[:, 1]
    d = p[i] - p[j]; d -= L*np.round(d/L)
    r2 = np.einsum('ij,ij->i', d, d); k = r2 < rc*rc
    d, r2, i, j = d[k], r2[k], i[k], j[k]
    ir2 = 1.0/r2; ir6 = ir2**3; ff = 24.0*ir6*(2.0*ir6 - 1.0)*ir2
    fd = d*ff[:, None]
    F = np.empty((N, 3))
    for c in range(3):
        F[:, c] = np.bincount(i, fd[:, c], N) - np.bincount(j, fd[:, c], N)
    U = (4.0*ir6*(ir6 - 1.0) - ecut).sum()
    Woff = np.array([(d[:, 0]*fd[:, 1]).sum(), (d[:, 0]*fd[:, 2]).sum(), (d[:, 1]*fd[:, 2]).sum()])
    return F, U, Woff
state = {'pairs': build(pos), 'ref': pos.copy(), 'nbuild': 1}
F, U, Woff = forces(pos, state['pairs'])
def step():
    global F, U, Woff
    vel[:] += 0.5*dt*F
    pos[:] += dt*vel
    dd = pos - state['ref']
    if np.einsum('ij,ij->i', dd, dd).max() > (0.5*skin)**2:
        state['pairs'] = build(pos); state['ref'] = pos.copy(); state['nbuild'] += 1
    F, U, Woff = forces(pos, state['pairs'])
    vel[:] += 0.5*dt*F
t0 = time.time()
for n in range(4000):
    step()
    if n % 20 == 0: vel *= np.sqrt(T_star/temp(vel))
for n in range(1000): step()
print(f'equilibrated in {time.time()-t0:.1f}s, T*={temp(vel):.4f}', flush=True)
nprod = 12000; Et = np.empty(nprod); Tt = np.empty(nprod); Pxy = np.empty((nprod, 3)); traj = []
for n in range(nprod):
    step()
    K = 0.5*(vel*vel).sum(); Et[n] = K + U; Tt[n] = 2*K/ndof
    kin = np.array([(vel[:, 0]*vel[:, 1]).sum(), (vel[:, 0]*vel[:, 2]).sum(), (vel[:, 1]*vel[:, 2]).sum()])
    Pxy[n] = (kin + Woff)/V
    if n % 10 == 0: traj.append(pos.copy())
print(f'production {nprod} steps done at {time.time()-t0:.1f}s, neighbour builds {state["nbuild"]}', flush=True)
t = np.arange(nprod)*dt; slope = np.polyfit(t, Et, 1)[0]; Tm = Tt.mean()
print(f'<T*>={Tm:.4f} ({Tm*119.8:.1f} K) E/N={Et.mean()/N:.4f} std(E)/N={Et.std()/N:.2e} drift={slope/N:.2e} eps/atom/tau = {slope/ndof/Tm*(1e-9/tau):.2e} kT/DOF/ns', flush=True)
fr = np.array(traj); nf = len(fr)
def msd_D(frames, tmin=5.0):
    lags = np.arange(1, len(frames)//2)
    m = np.array([((frames[l:] - frames[:-l])**2).sum(2).mean() for l in lags]); tl = lags*10*dt
    sel = tl >= tmin
    return np.polyfit(tl[sel], m[sel], 1)[0]/6, tl.max()
Dst, tmax = msd_D(fr)
print(f'D* = {Dst:.4f} (fit 5..{tmax:.0f} tau)  D_PBC = {Dst*sig**2/tau*1e4:.3e} cm^2/s', flush=True)
Dseg = [msd_D(fr[ix])[0] for ix in np.array_split(np.arange(nf), 3)]
print('segment D*:', np.round(Dseg, 4), 'std err of mean', round(np.std(Dseg, ddof=1)/np.sqrt(3), 4))
def acf(x):
    x = x - x.mean(); n = len(x); f = np.fft.rfft(x, 2*n)
    return np.fft.irfft(f*np.conj(f))[:n]/np.arange(n, 0, -1)
C = np.mean([acf(Pxy[:, k]) for k in range(3)], axis=0)
run = V/Tm*(np.cumsum(C) - 0.5*C[0] - 0.5*C)*dt
for tt in (0.5, 1.0, 2.0, 3.0, 5.0): print(f'GK eta*(t<={tt}) = {run[int(tt/dt)]:.3f}')
eta = run[int(2.0/dt)]; xi = 2.837297
dD = Tm*xi/(6*np.pi*eta*L)
print(f'Yeh-Hummer: dD* = {dD:.4f} -> D_inf* = {Dst + dD:.4f} = {(Dst + dD)*sig**2/tau*1e4:.3e} cm^2/s (eta = {eta*np.sqrt(mass*eps)/sig**2:.3e} Pa s)')
```

## Output (October 2026)

```
rho*=0.8177 T*=0.7880 L=10.185 sigma = 3.468 nm, tau=2.1563 ps, eta unit=9.0346e-05 Pa s
equilibrated in 9.3s, T*=0.7890
production 12000 steps done at 31.0s, neighbour builds 1932
<T*>=0.7959 (95.3 K) E/N=-3.7837 std(E)/N=9.05e-05 drift=2.03e-06 eps/atom/tau = 3.94e-04 kT/DOF/ns
D* = 0.0472 (fit 5..30 tau)  D_PBC = 2.536e-05 cm^2/s
segment D*: [0.0413 0.0533 0.0442] std err of mean 0.0036
GK eta*(t<=0.5) = 2.488
GK eta*(t<=1.0) = 2.383
GK eta*(t<=2.0) = 1.875
GK eta*(t<=3.0) = 1.638
GK eta*(t<=5.0) = 2.147
Yeh-Hummer: dD* = 0.0063 -> D_inf* = 0.0534 = 2.873e-05 cm^2/s (eta = 1.694e-04 Pa s)
```
