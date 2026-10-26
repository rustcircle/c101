"""Tests for the Bayesian learner, transcript ingestion and frontmatter editing.

Run:  python3 -m unittest discover -s tests -v
"""
import stackenv  # noqa: F401  (first: scrub leaked env vars, see tests/stackenv.py)
import json
import math
import os
import random
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stack import frontmatter  # noqa: E402
from stack.learn import bayes, ingest, model  # noqa: E402


class BayesTests(unittest.TestCase):
    def test_lognormal_recovers_parameters(self):
        rng = random.Random(7)
        obs = [bayes.Obs(math.exp(rng.gauss(math.log(20), 0.4))) for _ in range(200)]
        m = bayes.LogNormalGrid(bayes.LogNormalPrior.around(10)).fit(obs)
        mu, sigma = m.posterior_mean()
        self.assertAlmostEqual(math.exp(mu), 20, delta=2.0)
        self.assertAlmostEqual(sigma, 0.4, delta=0.08)
        q95 = m.predictive_quantile(0.95)
        self.assertAlmostEqual(q95, 20 * math.exp(1.645 * 0.4), delta=5)

    def test_censoring_pushes_estimate_up(self):
        rng = random.Random(3)
        true = [math.exp(rng.gauss(math.log(30), 0.3)) for _ in range(40)]
        cap = 25.0
        cens = [bayes.Obs(min(v, cap), v >= cap) for v in true]
        naive = [bayes.Obs(min(v, cap)) for v in true]
        prior = bayes.LogNormalPrior.around(10)
        m_c = bayes.LogNormalGrid(prior).fit(cens)
        m_n = bayes.LogNormalGrid(prior).fit(naive)
        self.assertGreater(m_c.predictive_quantile(0.5), m_n.predictive_quantile(0.5) * 1.1)
        self.assertGreater(m_c.predictive_quantile(0.5), cap)

    def test_predictive_cdf_monotone_and_quantile_inverse(self):
        m = bayes.LogNormalGrid(bayes.LogNormalPrior.around(12)).fit([bayes.Obs(v) for v in (8, 10, 12, 15, 20)])
        xs = [1, 5, 10, 20, 50, 200]
        cdf = [m.predictive_cdf(x) for x in xs]
        self.assertEqual(cdf, sorted(cdf))
        for q in (0.1, 0.5, 0.9):
            self.assertAlmostEqual(m.predictive_cdf(m.predictive_quantile(q)), q, delta=0.01)

    def test_norm_logsf_tails(self):
        self.assertAlmostEqual(bayes.norm_logsf(0.0), math.log(0.5), places=9)
        self.assertAlmostEqual(bayes.norm_logsf(10.0), -53.2312852, places=4)
        self.assertLess(abs(bayes.norm_logsf(-8.0)), 1e-12)

    def test_beta_quantile(self):
        b = bayes.BetaRate(2, 8)
        self.assertAlmostEqual(b.mean, 0.2)
        self.assertAlmostEqual(b.quantile(0.5), 0.1796, delta=0.001)  # median of Beta(2,8)

    def test_dirichlet_covering(self):
        d = bayes.DirichletCategories(["a", "b", "c"], [1, 1, 1]).update([0, 10, 0])
        self.assertEqual(d.smallest_covering(0.5), 1)
        self.assertEqual(d.smallest_covering(0.99), 2)

    def test_forgetting_detects_drift(self):
        rng = random.Random(11)
        stationary = [bayes.Obs(math.exp(rng.gauss(math.log(10), 0.3))) for _ in range(40)]
        drift = [bayes.Obs(math.exp(rng.gauss(math.log(10), 0.3))) for _ in range(25)] + \
                [bayes.Obs(math.exp(rng.gauss(math.log(40), 0.3))) for _ in range(15)]
        prior = bayes.LogNormalPrior.around(10)
        g_s, _ = bayes.select_forgetting(stationary, prior)
        g_d, _ = bayes.select_forgetting(drift, prior)
        self.assertGreaterEqual(g_s, 0.94)
        self.assertLess(g_d, g_s)

    def test_effective_window(self):
        self.assertEqual(bayes.effective_window(1.0, 30), 30.0)
        self.assertAlmostEqual(bayes.effective_window(0.9, 1000), 10.0, places=3)


with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "learning.json")) as _fh:
    CFG = json.load(_fh)


def _obs(turns, out_tokens, capped=False, t=0.0, effort="high"):
    return {"turns": turns, "output_tokens": out_tokens, "tokens_total": out_tokens * 10,
            "ctx_peak": 50000, "output_max_turn": out_tokens // max(turns, 1), "capped": capped,
            "started_at": t, "effort": effort}


class ModelTests(unittest.TestCase):
    def bounds(self):
        return dict(CFG["default_bounds"])

    def test_raises_max_turns_when_capped(self):
        obs = [_obs(40, 30000, capped=True, t=i) for i in range(6)] + [_obs(30, 20000, t=10 + i) for i in range(4)]
        r = model.recommend_agent("x", obs, {"maxTurns": "40", "effort": "high"}, CFG, self.bounds())
        self.assertGreater(r["maxTurns"]["recommended"], 40)
        self.assertLessEqual(r["maxTurns"]["recommended"], 80)  # max_step_factor 2

    def test_lowers_max_turns_for_short_runs(self):
        obs = [_obs(5 + (i % 3), 3000, t=i) for i in range(30)]
        r = model.recommend_agent("x", obs, {"maxTurns": "120", "effort": "high"}, CFG, self.bounds())
        self.assertLess(r["maxTurns"]["recommended"], 120)
        self.assertGreaterEqual(r["maxTurns"]["recommended"], 60)  # at most halves per update

    def test_converges_then_holds(self):
        """Repeated updates on the same evidence reach a fixed point and stay there."""
        obs = [_obs(10, 5000, t=i) for i in range(20)]
        cur, seen = 100, []
        for _ in range(8):
            r = model.recommend_agent("x", obs, {"maxTurns": str(cur), "effort": "high"}, CFG, self.bounds())
            seen.append(r["maxTurns"]["recommended"])
            if seen[-1] == cur:
                break
            cur = seen[-1]
        self.assertEqual(seen[-1], cur, seen)
        self.assertTrue(10 < cur < 40, seen)

    def test_effort_deescalates_one_level_for_tiny_outputs(self):
        obs = [_obs(6, 1500, t=i) for i in range(25)]
        r = model.recommend_agent("x", obs, {"maxTurns": "30", "effort": "xhigh"}, CFG, self.bounds())
        self.assertEqual(r["effort"]["recommended"], "high")

    def test_effort_escalates_on_failures(self):
        obs = [_obs(30, 30000, capped=(i % 2 == 0), t=i) for i in range(20)]
        r = model.recommend_agent("x", obs, {"maxTurns": "30", "effort": "medium"}, CFG, self.bounds())
        self.assertEqual(r["effort"]["recommended"], "high")

    def test_bounds_respected(self):
        obs = [_obs(3, 500, t=i) for i in range(40)]
        b = dict(self.bounds(), maxTurns=[25, 300], effort=["high", "max"])
        r = model.recommend_agent("x", obs, {"maxTurns": "40", "effort": "high"}, CFG, b)
        self.assertGreaterEqual(r["maxTurns"]["recommended"], 25)
        self.assertEqual(r["effort"]["recommended"], "high")

    def test_no_data(self):
        r = model.recommend_agent("x", [], {"maxTurns": "40"}, CFG, self.bounds())
        self.assertEqual(r["status"], "no-data")


def _line(**kw):
    return json.dumps(kw) + "\n"


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _session(self):
        sid = "sess-1"
        main = os.path.join(self.tmp, sid + ".jsonl")
        with open(main, "w") as fh:
            for i in range(3):  # three API turns, the first split over two content-block lines
                u = {"input_tokens": 5, "cache_read_input_tokens": 1000 * (i + 1), "cache_creation_input_tokens": 10,
                     "output_tokens": 200, "output_tokens_details": {"thinking_tokens": 50}}
                blocks = [{"type": "thinking", "thinking": "x" * 40}, {"type": "text", "text": "hello"}] if i == 0 else \
                         [{"type": "tool_use", "name": "Agent", "input": {"subagent_type": "rust-expert", "prompt": "p"}}]
                for b in blocks:
                    fh.write(_line(type="assistant", sessionId=sid, timestamp="2026-10-19T10:00:0%dZ" % i, effort="high",
                                   message={"id": "m%d" % i, "model": "claude-opus-5-5", "stop_reason": "end_turn",
                                            "usage": u, "content": [b]}))
            fh.write(_line(type="user", timestamp="2026-10-19T10:00:09Z",
                           message={"content": [{"type": "tool_result", "is_error": True, "content": "boom"}]}))
        sub = os.path.join(self.tmp, sid, "subagents")
        os.makedirs(sub)
        with open(os.path.join(sub, "agent-abc.jsonl"), "w") as fh:
            for i in range(4):  # sidechain: streaming placeholder usage (stop_reason null, tiny output)
                fh.write(_line(type="assistant", agentId="abc", sessionId=sid, isSidechain=True, effort="medium",
                               timestamp="2026-10-19T10:01:0%dZ" % i,
                               message={"id": "s%d" % i, "model": "claude-sonnet-5-5", "stop_reason": None,
                                        "usage": {"input_tokens": 3, "cache_read_input_tokens": 500, "output_tokens": 2},
                                        "content": [{"type": "text", "text": "y" * 360}]}))
        with open(os.path.join(sub, "agent-abc.meta.json"), "w") as fh:
            json.dump({"agentType": "rust-expert", "spawnDepth": 2, "description": "d"}, fh)
        return main

    def test_session_ingest(self):
        recs = ingest.ingest_session(self._session())
        by = {r["agent_type"]: r for r in recs}
        main = by["main"]
        self.assertEqual(main["turns"], 3)
        self.assertEqual(main["tool_rounds"], 2)  # responses m1, m2 call tools; m0 is thinking+text
        self.assertEqual(main["output_tokens"], 600)
        self.assertEqual(main["thinking_tokens"], 150)
        self.assertEqual(main["ctx_peak"], 3015)
        self.assertEqual(main["tool_errors"], 1)
        self.assertEqual(main["agent_spawns"], {"rust-expert": 2})
        self.assertEqual(main["effort"], "high")
        sub = by["rust-expert"]
        self.assertEqual(sub["spawn_depth"], 2)
        self.assertEqual(sub["turns"], 4)
        self.assertEqual(sub["tool_rounds"], 0)
        self.assertTrue(sub["output_estimated"])
        self.assertEqual(sub["output_tokens"], 4 * 100)  # 360 chars / 3.6
        self.assertEqual(sub["model"], "claude-sonnet-5-5")


class FrontmatterTests(unittest.TestCase):
    DOC = '---\nname: a\ndescription: "x: y"\nmaxTurns: 10\nmcpServers:\n  - exa\n  - jina\nskills: [p, q]\n---\nbody\n---\nmore\n'

    def test_parse(self):
        fm = frontmatter.parse(self.DOC)
        self.assertEqual(fm["description"], "x: y")
        self.assertEqual(fm["mcpServers"], ["exa", "jina"])
        self.assertEqual(fm["skills"], ["p", "q"])

    def test_set_preserves_body_and_other_keys(self):
        out = frontmatter.set_keys(self.DOC, {"maxTurns": "12", "effort": "high", "mcpServers": ["exa"]})
        self.assertTrue(out.endswith("body\n---\nmore\n"))
        fm = frontmatter.parse(out)
        self.assertEqual(fm["maxTurns"], "12")
        self.assertEqual(fm["effort"], "high")
        self.assertEqual(fm["mcpServers"], ["exa"])
        self.assertEqual(fm["description"], "x: y")

    def test_delete_key(self):
        out = frontmatter.set_keys(self.DOC, {"mcpServers": None})
        self.assertNotIn("mcpServers", frontmatter.parse(out))
        self.assertIn("skills", frontmatter.parse(out))


class SessionLifecycleTests(unittest.TestCase):
    """SessionEnd records (history.jsonl) without applying; SessionStart applies pending values."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(os.path.join(self.data, "obs"))
        os.environ["CLAUDE_STACK_DATA"] = self.data
        self.agent = os.path.join(self.tmp, "a.md")
        with open(self.agent, "w") as fh:
            fh.write("---\nname: a\ndescription: x\nmaxTurns: 40\neffort: medium\n---\nbody\n")
        with open(os.path.join(self.data, "recommendations.json"), "w") as fh:
            json.dump({"agents": {"a": {"managed": True, "status": "ok", "path": self.agent,
                                        "maxTurns": {"current": 40, "recommended": 60, "reason": "r"},
                                        "effort": {"current": "medium", "recommended": "high", "reason": "e"}}}}, fh)
        with open(os.path.join(self.data, "obs", "S1.json"), "w") as fh:
            json.dump({"x1": {"agent_id": "x1", "agent_type": "a", "turns": 12, "tool_rounds": 9, "capped": False,
                              "tool_errors": 1, "tokens_total": 5000, "output_tokens": 700, "duration_s": 3.5,
                              "effort": "medium", "model": "claude-sonnet-5-5", "started_at": 1.7e9,
                              "transcript": "/p/proj/S1.jsonl"},
                       "x2": {"agent_id": "x2", "agent_type": "a", "turns": 30, "tool_rounds": 40, "capped": True,
                              "tool_errors": 0, "tokens_total": 9000, "output_tokens": 900, "duration_s": 8.0,
                              "effort": "medium", "model": "claude-sonnet-5-5", "started_at": 1.7e9 + 60,
                              "transcript": "/p/proj/S1.jsonl"}}, fh)

    def tearDown(self):
        os.environ.pop("CLAUDE_STACK_DATA", None)

    def test_record_is_idempotent_and_summarises_agents(self):
        from stack.learn import engine
        engine.record_session("S1")
        line = engine.record_session("S1")
        with open(os.path.join(self.data, "history.jsonl")) as fh:
            self.assertEqual(len(fh.readlines()), 1)
        a = line["agents"]["a"]
        self.assertEqual((a["runs"], a["capped"], a["tool_errors"], a["turns_max"]), (2, 1, 1, 30))
        self.assertEqual(a["maxTurns"], {"current": 40, "recommended": 60})
        rows = engine.history(by="session")["a"]
        self.assertEqual(rows[0]["cap_rate"], 0.5)

    def test_start_applies_pending_values_and_respects_apply_on(self):
        from stack import frontmatter
        from stack.learn import engine
        real = engine.load_config
        try:
            engine.load_config = lambda: dict(real(), apply_on="never")
            self.assertEqual(engine.start_of_session(), [])
            self.assertEqual(frontmatter.read(self.agent)["maxTurns"], "40")
            engine.load_config = lambda: dict(real(), apply_on="session_start")
            ch = engine.start_of_session()
        finally:
            engine.load_config = real
        self.assertEqual(ch[0]["updates"], {"maxTurns": "60", "effort": "high"})
        fm = frontmatter.read(self.agent)
        self.assertEqual((fm["maxTurns"], fm["effort"]), ("60", "high"))

    def _run_after_session(self, apply_on):
        from stack.learn import engine
        real_ingest, real_update, real_cfg = engine.ingest_transcript, engine.update, engine.load_config
        engine.ingest_transcript = lambda tp: 2
        engine.update = lambda only=None: {"agents": {}}
        engine.load_config = lambda: dict(real_cfg(), apply_on=apply_on)
        try:
            return engine.run_after_session("/p/proj/S1.jsonl")
        finally:
            engine.ingest_transcript, engine.update, engine.load_config = real_ingest, real_update, real_cfg

    def test_session_end_records_without_applying_under_legacy_session_start(self):
        from stack import frontmatter
        res = self._run_after_session("session_start")
        self.assertTrue(res["recorded"])
        self.assertEqual(res["changes"], [])
        self.assertEqual(frontmatter.read(self.agent)["maxTurns"], "40")

    def test_session_end_applies_by_default(self):
        """Claude Code loads agent definitions once per session, so the values must be on disk when it ends."""
        from stack import frontmatter
        from stack.learn import engine
        self.assertEqual(engine.apply_on(), "session_end")  # shipped config/learning.json
        res = self._run_after_session("session_end")
        self.assertTrue(res["recorded"])
        self.assertEqual(res["changes"][0]["updates"], {"maxTurns": "60", "effort": "high"})
        fm = frontmatter.read(self.agent)
        self.assertEqual((fm["maxTurns"], fm["effort"]), ("60", "high"))


if __name__ == "__main__":
    unittest.main()
