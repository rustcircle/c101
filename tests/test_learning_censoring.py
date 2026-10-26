"""Regression tests: runs cut off at their turn limit must be recorded as right-censored.

Bug (2026-10-26): ``capped`` was decided against the agent's maxTurns at *ingest* time, so re-ingesting
after a limit change reclassified old cut-off runs as uncapped; the harness's own "stopped at its N-turn
limit" notice was ignored; and the learner lowered maxTurns on 4 small runs right after a capped one.

Run:  python3 -m unittest discover -s tests -v
"""
import stackenv  # noqa: F401  (first: scrub leaked env vars, see tests/stackenv.py)
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stack.learn import engine, ingest, model  # noqa: E402

with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "learning.json")) as _fh:
    CFG = json.load(_fh)

T0 = 1_792_000_000.0  # session start (epoch seconds)


def _iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _line(**kw):
    return json.dumps(kw) + "\n"


def _assistant(sid, mid, ts, content, stop="tool_use", agent_id=None):
    row = dict(type="assistant", sessionId=sid, timestamp=_iso(ts),
               message={"id": mid, "model": "m", "stop_reason": stop,
                        "usage": {"input_tokens": 10, "output_tokens": 50}, "content": content})
    if agent_id:
        row.update(agentId=agent_id, isSidechain=True)
    return _line(**row)


class _SessionFixture(unittest.TestCase):
    """A session dir with a main transcript and subagents; agent frontmatter and data dir are faked."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(self.data)
        os.environ["CLAUDE_STACK_DATA"] = self.data
        self.sid = "sess-cap"
        self.main = os.path.join(self.tmp, self.sid + ".jsonl")
        self.sub = os.path.join(self.tmp, self.sid, "subagents")
        os.makedirs(self.sub)
        self.frontmatter = {"a": 20}
        self._real_current = engine._agent_current
        engine._agent_current = lambda name: ({"maxTurns": str(self.frontmatter[name]), "path": "/x/%s.md" % name}
                                              if name in self.frontmatter else {})
        self.main_rows = [_assistant(self.sid, "m0", T0, [{"type": "text", "text": "hi"}], stop="end_turn")]

    def tearDown(self):
        engine._agent_current = self._real_current
        os.environ.pop("CLAUDE_STACK_DATA", None)
        shutil.rmtree(self.tmp)

    def add_subagent(self, agent_id, rounds, agent_type="a", start=T0 + 60, tool_use_id=None, extra_rows=()):
        with open(os.path.join(self.sub, "agent-%s.jsonl" % agent_id), "w") as fh:
            for i in range(rounds):
                fh.write(_assistant(self.sid, "%s-%d" % (agent_id, i), start + i,
                                    [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}],
                                    agent_id=agent_id))
            for row in extra_rows:
                fh.write(row)
        meta = {"agentType": agent_type, "spawnDepth": 1, "description": "d"}
        if tool_use_id:
            meta["toolUseId"] = tool_use_id
        with open(os.path.join(self.sub, "agent-%s.meta.json" % agent_id), "w") as fh:
            json.dump(meta, fh)

    def write_main(self):
        with open(self.main, "w") as fh:
            fh.writelines(self.main_rows)

    def ingest(self):
        self.write_main()
        engine.ingest_transcript(self.main)
        with open(os.path.join(self.data, "obs", "%s.json" % self.sid)) as fh:
            return json.load(fh)


class LimitAtRunTests(_SessionFixture):
    def test_run_at_limit_is_capped_one_below_is_not(self):
        """All 20 real cut-offs (2026-10-26) had exactly N rounds; N-1 is a run that finished."""
        self.add_subagent("r20", 20)
        self.add_subagent("r19", 19)
        obs = self.ingest()
        self.assertTrue(obs["r20"]["capped"], obs["r20"])
        self.assertEqual(obs["r20"]["limit_max_turns"], 20)
        self.assertFalse(obs["r19"]["capped"], obs["r19"])

    def test_capped_survives_reingest_after_limit_rises(self):
        self.add_subagent("r19", 19)
        self.add_subagent("r20", 20)
        self.add_subagent("r5", 5)
        self.ingest()
        self.frontmatter["a"] = 60  # the learner (or the user) raises the limit afterwards
        obs = self.ingest()
        self.assertTrue(obs["r20"]["capped"], obs["r20"])
        for aid in ("r19", "r20", "r5"):
            self.assertEqual(obs[aid]["limit_max_turns"], 20, aid)
        self.assertFalse(obs["r19"]["capped"])
        self.assertFalse(obs["r5"]["capped"])

    def test_new_run_after_learner_change_in_session_uses_change_history(self):
        """changed_since branch: the learner rewrote the limit after the session loaded 45."""
        self.frontmatter["a"] = 120
        os.makedirs(self.data, exist_ok=True)
        with open(os.path.join(self.data, "changes.jsonl"), "w") as fh:
            fh.write(json.dumps({"agent": "a", "updates": {"maxTurns": "45"}, "ts": T0 - 3600}) + "\n")
            fh.write(json.dumps({"agent": "a", "updates": {"maxTurns": "120"}, "ts": T0 + 600}) + "\n")
        self.add_subagent("n45", 45)
        obs = self.ingest()
        self.assertEqual((obs["n45"]["limit_max_turns"], obs["n45"]["limit_source"]), (45, "change_history"))
        self.assertTrue(obs["n45"]["capped"])

    def test_legacy_record_uses_change_history_for_its_session(self):
        """Old obs record stored with the ingest-time limit (120); changes.jsonl says 45 was in force."""
        self.frontmatter["a"] = 120
        self.add_subagent("old", 45)
        os.makedirs(os.path.join(self.data, "obs"))
        with open(os.path.join(self.data, "obs", "%s.json" % self.sid), "w") as fh:
            json.dump({"old": {"agent_id": "old", "agent_type": "a", "tool_rounds": 45, "turns": 45,
                               "limit_max_turns": 120, "capped": False, "ingested_at": T0 + 9000}}, fh)
        with open(os.path.join(self.data, "changes.jsonl"), "w") as fh:
            fh.write(json.dumps({"agent": "a", "updates": {"maxTurns": "45"}, "ts": T0 - 3600}) + "\n")
        obs = self.ingest()
        self.assertEqual(obs["old"]["limit_max_turns"], 45)
        self.assertTrue(obs["old"]["capped"])
        self.assertTrue(obs["old"]["limit_source"].startswith("legacy"), obs["old"]["limit_source"])


    def test_history_takes_smaller_value_at_session_start_boundary(self):
        """45 set well before the session; 40 written by that session's own SessionStart apply.

        The harness enforced 45 in that case: taking the smaller value at the boundary is a deliberate
        conservative bias (a spurious cap only nudges maxTurns up; a missed one drags it down)."""
        pts = [(T0 - 124, 45), (T0 - 99, 45), (T0, 40), (T0 + 9000, 120)]
        self.assertEqual(engine._limit_from_history(pts, T0), 40)
        self.assertEqual(engine._limit_from_history(pts, T0 + 5000), 40)   # last value before start
        self.assertIsNone(engine._limit_from_history([(T0 + 9000, 120)], T0))  # nothing known yet


class StructuredStopTests(_SessionFixture):
    def test_background_task_notification_marks_capped(self):
        """No text marker in the subagent transcript; the parent got the harness's turn-limit notice."""
        self.frontmatter["a"] = 120
        self.add_subagent("bg1", 30)
        note = ("<task-notification>\n<task-id>bg1</task-id>\n<status>completed</status>\n"
                "<summary>Agent \"x\" stopped at its 30-turn limit (partial result)</summary>\n</task-notification>")
        self.main_rows.append(_line(type="queue-operation", operation="enqueue", timestamp=_iso(T0 + 200),
                                    sessionId=self.sid, content=note))
        obs = self.ingest()
        self.assertTrue(obs["bg1"]["max_turns_hit"])
        self.assertTrue(obs["bg1"]["capped"])
        self.assertEqual(obs["bg1"]["limit_max_turns"], 30)

    def test_foreground_tool_result_notice_marks_capped(self):
        self.frontmatter["a"] = 120
        self.add_subagent("fg1", 22, tool_use_id="toolu_fg1")
        res = {"type": "tool_result", "tool_use_id": "toolu_fg1", "content": [
            {"type": "text", "text": "  NOTE: this agent stopped at its 20-turn limit before finishing."}]}
        self.main_rows.append(_line(type="user", timestamp=_iso(T0 + 200), message={"content": [res]}))
        obs = self.ingest()
        self.assertTrue(obs["fg1"]["capped"])
        self.assertEqual(obs["fg1"]["limit_max_turns"], 20)

    def test_structured_stop_reason_in_transcript(self):
        self.frontmatter["a"] = 120
        self.add_subagent("sr1", 10, extra_rows=[
            _assistant(self.sid, "sr1-end", T0 + 500, [{"type": "text", "text": "partial"}], stop="max_turns",
                       agent_id="sr1")])
        obs = self.ingest()
        self.assertTrue(obs["sr1"]["max_turns_hit"])
        self.assertTrue(obs["sr1"]["capped"])

    def test_foreground_notice_must_open_the_tool_result(self):
        self.frontmatter["a"] = 120
        self.add_subagent("q1", 10, tool_use_id="toolu_q1")
        res = {"type": "tool_result", "tool_use_id": "toolu_q1", "content": [
            {"type": "text", "text": "Report: NOTE: this agent stopped at its 10-turn limit before finishing."}]}
        self.main_rows.append(_line(type="user", timestamp=_iso(T0 + 301), message={"content": [res]}))
        obs = self.ingest()
        self.assertFalse(obs["q1"]["capped"], obs["q1"])

    def _notify(self, task_id, summary, result=""):
        note = ("<task-notification>\n<task-id>%s</task-id>\n<status>completed</status>\n"
                "<summary>%s</summary>\n%s</task-notification>" % (task_id, summary, result))
        self.main_rows.append(_line(type="queue-operation", operation="enqueue", timestamp=_iso(T0 + 400),
                                    sessionId=self.sid, content=note))

    def test_notice_quoted_in_result_of_finished_agent_is_not_a_cap(self):
        self.frontmatter["a"] = 120
        self.add_subagent("ok1", 12)
        self._notify("ok1", 'Agent "debug learner" finished',
                     '<result>Harness form: <summary>Agent "x" stopped at its 45-turn limit (partial)\n</result>\n')
        obs = self.ingest()
        self.assertFalse(obs["ok1"]["capped"], obs["ok1"])
        self.assertEqual(obs["ok1"]["limit_max_turns"], 120)

    def test_phrase_inside_description_is_not_a_cap(self):
        self.frontmatter["a"] = 120
        self.add_subagent("ok2", 12)
        self._notify("ok2", 'Agent "retry: stopped at its 20-turn limit" finished')
        obs = self.ingest()
        self.assertFalse(obs["ok2"]["capped"], obs["ok2"])

    def test_notice_for_one_agent_does_not_mark_another(self):
        self.frontmatter["a"] = 120
        self.add_subagent("x1", 30)
        self.add_subagent("y1", 30)
        self._notify("x1", 'Agent "x" stopped at its 30-turn limit (partial result)')
        obs = self.ingest()
        self.assertTrue(obs["x1"]["capped"])
        self.assertFalse(obs["y1"]["capped"], obs["y1"])

    def test_notice_arriving_after_first_ingest_overrides_stored_limit(self):
        self.frontmatter["a"] = 120
        self.add_subagent("late", 30)
        first = self.ingest()  # SubagentStop-time ingest: the parent has no notice yet
        self.assertEqual((first["late"]["capped"], first["late"]["limit_source"]),
                         (False, "frontmatter_at_first_ingest"))
        self._notify("late", 'Agent "x" stopped at its 30-turn limit (partial result)')
        obs = self.ingest()
        self.assertTrue(obs["late"]["capped"])
        self.assertEqual((obs["late"]["limit_max_turns"], obs["late"]["limit_source"]), (30, "harness_notice"))


class ApplyStaleRecommendationTests(unittest.TestCase):
    """apply() must judge a stored recommendation against the agent file as it is now."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["CLAUDE_STACK_DATA"] = self.tmp
        self.agent = os.path.join(self.tmp, "zz-agent.md")

    def tearDown(self):
        os.environ.pop("CLAUDE_STACK_DATA", None)
        shutil.rmtree(self.tmp)

    def run_apply(self, file_turns, current, recommended, n_eff=30.0, last_capped=False):
        from stack import frontmatter
        with open(self.agent, "w") as fh:
            fh.write("---\nname: zz-agent\ndescription: x\nmaxTurns: %d\n---\nbody\n" % file_turns)
        with open(os.path.join(self.tmp, "recommendations.json"), "w") as fh:
            json.dump({"agents": {"zz-agent": {
                "managed": True, "status": "ok", "path": self.agent,
                "turns": {"n_eff": n_eff, "last_capped": last_capped},
                "maxTurns": {"current": current, "recommended": recommended, "reason": "r"},
                "effort": {"current": None, "recommended": None}}}}, fh)
        engine.apply()
        return int(frontmatter.read(self.agent)["maxTurns"])

    def test_stale_recommendation_never_lowers_a_newer_manual_value(self):
        self.assertEqual(self.run_apply(120, current=45, recommended=60), 120)

    def test_stale_upward_recommendation_still_raises(self):
        self.assertEqual(self.run_apply(120, current=45, recommended=240), 240)

    def test_fresh_downward_move_applied_when_guards_pass(self):
        self.assertEqual(self.run_apply(120, current=120, recommended=80), 80)

    def test_downward_move_refused_on_little_evidence_or_recent_cap(self):
        self.assertEqual(self.run_apply(120, current=120, recommended=80, n_eff=4), 120)
        self.assertEqual(self.run_apply(120, current=120, recommended=80, last_capped=True), 120)

    def test_downward_move_refused_below_lower_bound(self):
        lo = CFG["default_bounds"]["maxTurns"][0]
        self.assertEqual(self.run_apply(120, current=120, recommended=lo - 1), 120)


def _obs(rounds, capped=False, t=0.0):
    return {"turns": rounds, "tool_rounds": rounds, "output_tokens": 3000, "tokens_total": 30000,
            "ctx_peak": 50000, "output_max_turn": 300, "capped": capped, "started_at": t, "effort": "high"}


class DownwardGuardTests(unittest.TestCase):
    def bounds(self):
        return dict(CFG["default_bounds"])

    def test_no_lowering_with_few_effective_runs(self):
        obs = [_obs(r, t=i) for i, r in enumerate((8, 18, 5, 4))]  # the deep-researcher 45 -> 40 case
        r = model.recommend_agent("x", obs, {"maxTurns": "120", "effort": "high"}, CFG, self.bounds())
        self.assertLess(r["turns"]["n_eff"], 8)
        self.assertEqual(r["maxTurns"]["recommended"], 120, r["maxTurns"])

    def test_no_lowering_right_after_a_capped_run(self):
        obs = [_obs(5 + (i % 3), t=i) for i in range(30)] + [_obs(40, capped=True, t=100)]
        r = model.recommend_agent("x", obs, {"maxTurns": "120", "effort": "high"}, CFG, self.bounds())
        self.assertEqual(r["maxTurns"]["recommended"], 120, r["maxTurns"])

    def test_raising_still_allowed_with_few_runs(self):
        obs = [_obs(40, capped=True, t=i) for i in range(4)]
        r = model.recommend_agent("x", obs, {"maxTurns": "40", "effort": "high"}, CFG, self.bounds())
        self.assertGreater(r["maxTurns"]["recommended"], 40)

    def test_hold_still_enforces_upper_bound(self):
        obs = [_obs(r, t=i) for i, r in enumerate((8, 18, 5, 4))]
        b = dict(self.bounds(), maxTurns=[5, 1000])
        r = model.recommend_agent("x", obs, {"maxTurns": "1200", "effort": "high"}, CFG, b)
        self.assertEqual(r["maxTurns"]["recommended"], 1000, r["maxTurns"])
        self.assertTrue(r["maxTurns"]["reason"].startswith("hold"), r["maxTurns"])

    def test_no_lowering_when_many_runs_were_censored(self):
        """web-searcher case: 14 of 28 runs cut off at 20, limit now 120, latest run uncapped."""
        obs = []
        for i in range(28):
            obs.append(_obs(20, capped=True, t=i) if i % 2 == 0 else _obs(12 + i % 5, t=i))
        r = model.recommend_agent("x", obs, {"maxTurns": "120", "effort": "high"}, CFG, self.bounds())
        self.assertGreaterEqual(r["turns"]["n_eff"], 8)
        self.assertEqual(r["maxTurns"]["recommended"], 120, r["maxTurns"])

    def test_capped_share_threshold_is_configurable(self):
        obs = [_obs(6, t=i) for i in range(40)]
        obs[5] = _obs(6, capped=True, t=5)  # 1 of 40 capped: 2.5%
        cfg = dict(CFG, max_capped_frac_lower=0.01)
        r = model.recommend_agent("x", obs, {"maxTurns": "120", "effort": "high"}, cfg, self.bounds())
        self.assertEqual(r["maxTurns"]["recommended"], 120, r["maxTurns"])
        r = model.recommend_agent("x", obs, {"maxTurns": "120", "effort": "high"}, CFG, self.bounds())
        self.assertLess(r["maxTurns"]["recommended"], 120)

    def test_never_lowered_below_1_5x_longest_uncapped_run(self):
        obs = [_obs(5 + (i % 3), t=i) for i in range(40)]
        obs[3] = _obs(40, t=3)
        r = model.recommend_agent("x", obs, {"maxTurns": "100", "effort": "high"}, CFG, self.bounds())
        self.assertGreaterEqual(r["maxTurns"]["recommended"], 60, r["maxTurns"])  # ceil(1.5 x 40)
        self.assertLess(r["maxTurns"]["recommended"], 100)

    def test_compact_window_bounds_come_from_config(self):
        obs = [dict(_obs(10, t=i), ctx_peak=300000) for i in range(10)]
        cur = {"maxTurns": "40", "effort": "high", "autoCompactWindow": "250000"}
        r = model.recommend_agent("x", obs, cur, CFG, self.bounds())
        self.assertEqual(r["budget"].get("autoCompactWindow"), CFG["default_bounds"]["autoCompactWindow"][0])
        cfg = json.loads(json.dumps(CFG))
        cfg["default_bounds"]["autoCompactWindow"] = [600000, 800000]
        big = [dict(_obs(10, t=i), ctx_peak=900000) for i in range(10)]
        cur["autoCompactWindow"] = "600000"
        r = model.recommend_agent("x", big, cur, cfg, dict(cfg["default_bounds"]))
        self.assertEqual(r["budget"].get("autoCompactWindow"), 800000)

    def test_lowering_still_allowed_with_enough_uncapped_runs(self):
        obs = [_obs(5 + (i % 3), t=i) for i in range(30)]
        r = model.recommend_agent("x", obs, {"maxTurns": "120", "effort": "high"}, CFG, self.bounds())
        self.assertLess(r["maxTurns"]["recommended"], 120)


if __name__ == "__main__":
    unittest.main()
