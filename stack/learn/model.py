"""From observations to per-agent recommendations (maxTurns, effort, token window).

maxTurns
    Censored log-normal posterior over turns-per-invocation, prior centred on
    the hand-set limit (typical run ~ limit / prior_limit_ratio).  The
    recommendation is the posterior-predictive ``turns_quantile`` times a
    safety margin, rounded up, clamped to the agent's bounds, and moved at most
    ``max_step_factor`` per update.  Runs that hit the limit are right-censored
    observations, so a cap that is too low pushes the posterior *up* rather
    than looking like "this agent always needs exactly N turns".

effort
    Each run is categorised into an effort band by the output tokens it
    produced (thinking included).  A Dirichlet over the bands (sticky prior on
    the current level) gives the smallest level that covers
    ``effort_cover_mass`` of runs; a Beta posterior on the cap-hit/failure rate
    escalates when the agent keeps running out of road and blocks
    de-escalation while failures are non-trivial.  Moves one level at a time.

token window
    Censoring-free log-normal posteriors on output tokens, total tokens,
    largest single-turn output and peak context per turn give [min, max]
    windows (predictive quantiles), a max-output-tokens setting for headless
    spawns, and a flag when the agent's context regularly approaches the
    standard window (a 1M-context model variant is worth it).

data window
    The forgetting factor gamma is chosen per agent by prequential log score;
    it determines the effective number of past runs the posterior listens to.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

from .bayes import (BetaRate, DirichletCategories, LogNormalGrid, LogNormalPrior, Obs,
                    effective_window, forgetting_weights, select_forgetting)

EFFORT_LEVELS = ["low", "medium", "high", "xhigh", "max"]


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def effort_index(level: Optional[str]) -> Optional[int]:
    try:
        return EFFORT_LEVELS.index(level) if level else None
    except ValueError:
        return None


def band_of(tokens: float, bands: Sequence[float]) -> int:
    for i, b in enumerate(bands):
        if tokens < b:
            return i
    return len(bands)


def _quantiles(model: LogNormalGrid, qs: Sequence[float]) -> Dict[str, float]:
    return {"q%02d" % int(round(q * 100)): round(model.predictive_quantile(q), 1) for q in qs}


def recommend_agent(name: str, obs: List[dict], current: Dict[str, object], cfg: dict,
                    bounds: Dict[str, object]) -> dict:
    """Compute the recommendation for one agent.

    obs     -- observations for this agent, any order (sorted here by start time)
    current -- {"maxTurns": int|None, "effort": str|None}
    bounds  -- {"maxTurns": [lo, hi], "effort": [lo, hi], "learn": bool}
    """
    obs = sorted(obs, key=lambda r: (r.get("started_at") or 0.0))
    n = len(obs)
    cur_turns = current.get("maxTurns")
    cur_turns = int(cur_turns) if cur_turns not in (None, "") else None
    cur_effort = current.get("effort") if current.get("effort") in EFFORT_LEVELS else None
    out: dict = {"agent": name, "n": n, "current": {"maxTurns": cur_turns, "effort": cur_effort}}
    if n == 0:
        out["status"] = "no-data"
        return out

    # ---- turns: censored log-normal with evidence-selected data window ----
    limit_typical = (cur_turns / cfg["prior_limit_ratio"]) if cur_turns else cfg["prior_turns_typical"]
    prior = LogNormalPrior.around(max(limit_typical, 1.0), spread_factor=cfg["prior_spread"])
    tseries = [Obs(max(float(r.get("tool_rounds", r["turns"])), 1.0), bool(r.get("capped"))) for r in obs]
    gamma, scores = select_forgetting(tseries, prior, min_points=cfg["min_points_for_window"])
    w = forgetting_weights(n, gamma)
    tmodel = LogNormalGrid(prior).fit(Obs(o.value, o.censored, wi) for o, wi in zip(tseries, w))
    n_eff = tmodel.n_eff
    out["window"] = {"gamma": gamma, "effective_runs": round(effective_window(gamma, n), 1),
                     "scores": {str(k): round(v, 2) for k, v in scores.items()}}
    wsum = sum(w) or 1.0
    capped_frac = sum(wi for o, wi in zip(tseries, w) if o.censored) / wsum
    longest_uncapped = max((o.value for o in tseries if not o.censored), default=0.0)
    lower_floor = int(math.ceil(cfg.get("lower_floor_factor", 1.5) * longest_uncapped))
    out["turns"] = dict(_quantiles(tmodel, (0.5, 0.9, 0.95, 0.99)),
                        n_eff=round(n_eff, 2), n_capped=sum(1 for o in tseries if o.censored),
                        last_capped=tseries[-1].censored, capped_frac=round(capped_frac, 3),
                        lower_floor=lower_floor)

    lo_t, hi_t = bounds.get("maxTurns", cfg["default_bounds"]["maxTurns"])
    rec_turns = cur_turns
    reason = "insufficient data"
    if n_eff >= cfg["min_obs_turns"]:
        target = math.ceil(tmodel.predictive_quantile(cfg["turns_quantile"]) * cfg["turns_margin"])
        if cur_turns:
            step = cfg["max_step_factor"]
            target = int(_clamp(target, math.floor(cur_turns / step), math.ceil(cur_turns * step)))
        target = int(_clamp(target, lo_t, hi_t))
        # Lowering is the costly direction (a cut-off run loses its work), so it needs more evidence
        # than raising: enough effective runs, the latest run not itself capped, few capped runs in the
        # effective window (with many, the upper tail is extrapolated from censored data), and never
        # below lower_floor_factor x the longest run that finished.  Raising is unaffected; bounds are
        # still enforced.  engine.apply() re-checks the same evidence before writing.
        hold = None
        if cur_turns and target < cur_turns:
            min_lower = cfg.get("min_obs_lower", 8)
            max_cf = cfg.get("max_capped_frac_lower", 0.10)
            if n_eff < min_lower:
                hold = "hold: lowering needs n_eff >= %g (have %.1f)" % (min_lower, n_eff)
            elif tseries[-1].censored:
                hold = "hold: most recent run hit the cap"
            elif capped_frac > max_cf:
                hold = "hold: %.0f%% of effective runs capped (> %.0f%%)" % (100 * capped_frac, 100 * max_cf)
            elif lower_floor >= cur_turns:
                hold = "hold: longest uncapped run x %.1f >= current" % cfg.get("lower_floor_factor", 1.5)
            elif target < lower_floor:
                target = int(_clamp(lower_floor, lo_t, hi_t))
        if hold:
            rec_turns = int(_clamp(cur_turns, lo_t, hi_t))
            reason = hold
        elif cur_turns is None or abs(target - cur_turns) >= max(2, cfg["min_change_frac"] * cur_turns):
            rec_turns = target
            reason = "q%02d of predictive x %.2f margin" % (round(cfg["turns_quantile"] * 100), cfg["turns_margin"])
        else:
            reason = "within hysteresis band"
    out["maxTurns"] = {"current": cur_turns, "recommended": rec_turns, "reason": reason}

    # ---- effort: Dirichlet over output-token bands + Beta failure rate ----
    bands = cfg["effort_bands_output_tokens"]
    counts = [0.0] * len(EFFORT_LEVELS)
    fails = succ = 0.0
    for r, wi in zip(obs, w):
        counts[band_of(float(r.get("output_tokens") or 0), bands)] += wi
        if r.get("capped") or r.get("failed"):
            fails += wi
        else:
            succ += wi
    alpha0 = [cfg["effort_prior_alpha"]] * len(EFFORT_LEVELS)
    ci = effort_index(cur_effort)
    if ci is not None:
        alpha0[ci] += cfg["effort_prior_stickiness"]
    dirich = DirichletCategories(EFFORT_LEVELS, alpha0).update(counts)
    fail_post = BetaRate(cfg["fail_prior"][0], cfg["fail_prior"][1]).update(fails, succ)
    lo_e, hi_e = [effort_index(x) for x in bounds.get("effort", cfg["default_bounds"]["effort"])]
    rec_e = cur_effort
    e_reason = "insufficient data"
    if n_eff >= cfg["min_obs_effort"]:
        idx = dirich.smallest_covering(cfg["effort_cover_mass"])
        if fail_post.mean > cfg["fail_rate_escalate"]:
            idx = max(idx, (ci if ci is not None else idx) + 1)
            e_reason = "escalate: P(fail)=%.2f" % fail_post.mean
        elif ci is not None and idx < ci and fail_post.mean > cfg["fail_rate_deescalate"]:
            idx = ci
            e_reason = "hold: failures block de-escalation"
        else:
            e_reason = "smallest band covering %.0f%% of runs" % (100 * cfg["effort_cover_mass"])
        if ci is not None:  # one level per update
            idx = int(_clamp(idx, ci - 1, ci + 1))
        idx = int(_clamp(idx, lo_e, hi_e))
        rec_e = EFFORT_LEVELS[idx]
    out["effort"] = {
        "current": cur_effort, "recommended": rec_e, "reason": e_reason,
        "band_probs": {lvl: round(p, 3) for lvl, p in zip(EFFORT_LEVELS, dirich.predictive())},
        "p_fail_mean": round(fail_post.mean, 3), "p_fail_q90": round(fail_post.quantile(0.9), 3),
        "observed": _mode([r.get("effort") for r in obs]),
    }

    # ---- token windows ----
    toks = {}
    for metric in ("output_tokens", "tokens_total", "ctx_peak", "output_max_turn"):
        vals = [float(r.get(metric) or 0) for r in obs]
        if not any(v > 0 for v in vals):
            continue
        typical = sorted(v for v in vals if v > 0)[len([v for v in vals if v > 0]) // 2]
        m = LogNormalGrid(LogNormalPrior.around(typical, spread_factor=4.0)).fit(
            Obs(v, False, wi) for v, wi in zip(vals, w) if v > 0)
        lo_q, hi_q = cfg["token_window_quantiles"]
        toks[metric] = {"min": int(m.predictive_quantile(lo_q)), "median": int(m.predictive_quantile(0.5)),
                        "max": int(m.predictive_quantile(hi_q))}
    out["tokens"] = toks
    budget = {}
    if "output_max_turn" in toks:
        budget["max_output_tokens"] = int(_clamp(
            math.ceil(toks["output_max_turn"]["max"] * cfg["turns_margin"] / 1000.0) * 1000,
            cfg["max_output_tokens_bounds"][0], cfg["max_output_tokens_bounds"][1]))
    if "ctx_peak" in toks:
        cur_win = current.get("autoCompactWindow")
        cur_win = int(cur_win) if str(cur_win or "").isdigit() else cfg["context_window_tokens"]
        lo_w, hi_w = bounds.get("autoCompactWindow",
                                cfg["default_bounds"].get("autoCompactWindow", [600000, 1000000]))
        budget["recommend_1m_context"] = toks["ctx_peak"]["max"] > cfg["context_window_tokens"] * cfg["context_pressure"]
        # Quality first: when the context regularly approaches the compaction point, raise the
        # window so long tasks are not compacted (lossily) mid-flight. Never lowers it.
        # Bounds from config (default_bounds / per-agent autoCompactWindow); a window below the floor
        # is raised to it.
        want = None
        if n_eff >= cfg["min_obs_turns"] and toks["ctx_peak"]["max"] > cur_win * cfg["context_pressure"]:
            want = int(math.ceil(toks["ctx_peak"]["max"] * cfg["turns_margin"] / 10000.0) * 10000)
        if cur_win < lo_w:
            want = max(want or 0, lo_w)
        if want is not None:
            want = int(_clamp(want, lo_w, hi_w))
            if want > cur_win:
                budget["autoCompactWindow"] = want
    out["budget"] = budget
    out["status"] = "ok"
    return out


def _mode(xs):
    xs = [x for x in xs if x]
    return max(set(xs), key=xs.count) if xs else None
