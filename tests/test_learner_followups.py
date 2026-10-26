"""Follow-ups to the learner censoring fix (2026-10-26).

* learned values are applied when a session ENDS (written before the next session loads them; a running
  session picks them up from its next turn once its file watcher is up); SessionStart is only a catch-up;
* the maxTurns in force is recorded when an agent is SPAWNED (pre-agent hook, keyed by tool_use_id), because
  agent files can change at any time during a session; SubagentStop records it (plus the stop reason) under the
  keys engine.py reads, each with its true basis; harness notice > spawn record > stop-time frontmatter >
  change-history estimate;
* every agent's autoCompactWindow is at least 600000 (the learner's floor) and within its tier model's window.

Run:  python3 -m unittest discover -s tests -v
"""
import stackenv  # noqa: F401  (first: scrub leaked env vars, see tests/stackenv.py)
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from stack import frontmatter, hooks, paths, tiers  # noqa: E402
from stack.learn import engine, ingest  # noqa: E402

with open(os.path.join(ROOT, "config", "learning.json"), encoding="utf-8") as _fh:
    LEARN_CFG = json.load(_fh)


class _DataDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(self.data)
        os.environ["CLAUDE_STACK_DATA"] = self.data

    def tearDown(self):
        os.environ.pop("CLAUDE_STACK_DATA", None)
        shutil.rmtree(self.tmp)


class RecordStopTests(_DataDir):
    """The limit in force is what the agent file said when the agent was spawned."""

    def setUp(self):
        super().setUp()
        self.agentfile = os.path.join(self.tmp, "tester.md")
        self.set_turns(120)
        self._find = paths.find_agent_file
        paths.find_agent_file = lambda n: self.agentfile if n == "tester" else self._find(n)
        self.sub = os.path.join(self.tmp, "proj", "S", "subagents")
        os.makedirs(self.sub)

    def tearDown(self):
        paths.find_agent_file = self._find
        super().tearDown()

    def set_turns(self, n):
        with open(self.agentfile, "w", encoding="utf-8") as fh:
            fh.write("---\nname: tester\nmaxTurns: %d\n---\nbody\n" % n)

    def spawn(self, tuid="tu1", sid="S", agent_type="tester"):
        hooks.pre_agent({"tool_name": "Agent", "session_id": sid, "tool_use_id": tuid,
                         "tool_input": {"subagent_type": agent_type, "prompt": "x"}})

    def stop(self, sid="S", tuid="tu1", **kw):
        tpath = os.path.join(self.sub, "agent-a1.jsonl")
        if tuid:
            with open(os.path.join(self.sub, "agent-a1.meta.json"), "w") as fh:
                json.dump({"agentType": "tester", "toolUseId": tuid}, fh)
        payload = {"session_id": sid, "agent_id": "a1", "agent_type": "tester", "effort": {"level": "high"},
                   "agent_transcript_path": tpath}
        payload.update(kw)
        hooks._record_stop(payload)
        return engine._stop_events(sid)["a1"]

    def test_spawn_records_limit_by_tool_use_id(self):
        self.spawn()
        rec = engine._spawn_records("S")["tu1"]
        self.assertEqual((rec["agent_type"], rec["limit_max_turns"]), ("tester", 120))

    def test_spawn_without_tool_use_id_or_for_unknown_type_records_nothing(self):
        hooks.pre_agent({"tool_name": "Agent", "session_id": "S",
                         "tool_input": {"subagent_type": "tester", "prompt": "x"}})
        self.spawn(tuid="tu2", agent_type="no-such-agent")
        self.assertEqual(engine._spawn_records("S"), {})

    def test_spawn_time_value_survives_a_later_apply(self):
        """Scenario A: another session's end lowers 120 -> 75 mid-session; the run was spawned under 120."""
        self.spawn()
        self.set_turns(75)
        ev = self.stop()
        self.assertEqual((ev["limit_max_turns"], ev["limit_basis"]), (120, "spawn_record"))
        self.assertEqual(engine._limit_at_run({}, None, ev, 75, [], None), (120, "spawn_record"))

    def test_raise_after_spawn_does_not_fake_a_cap(self):
        self.spawn()
        self.set_turns(444)
        ev = self.stop()
        self.assertEqual(engine._limit_at_run({}, None, ev, 444, [], None)[0], 120)

    def test_without_spawn_record_the_basis_is_stop_time_frontmatter(self):
        ev = self.stop(tuid=None)
        self.assertEqual((ev["limit_max_turns"], ev["limit_basis"]), (120, "stop_frontmatter"))
        # the engine labels it truthfully and does not call it a stop_event
        self.assertEqual(engine._limit_at_run({}, None, ev, 120, [], None), (120, "stop_frontmatter"))

    def test_stop_frontmatter_outranks_the_history_estimate_but_spawn_outranks_both(self):
        hist = [(1000.0, 30)]
        fm_ev = {"limit_max_turns": 120, "limit_basis": "stop_frontmatter"}
        self.assertEqual(engine._limit_at_run({}, None, fm_ev, 120, hist, 1000.0), (120, "stop_frontmatter"))
        self.assertEqual(engine._limit_at_run({}, None, None, 120, hist, 1000.0)[1], "change_history")
        spawn = {"limit_max_turns": 45}
        self.assertEqual(engine._limit_at_run({}, None, fm_ev, 120, hist, 1000.0, spawn=spawn), (45, "spawn_record"))

    def test_harness_notice_outranks_everything(self):
        spawn, ev = {"limit_max_turns": 45}, {"limit_max_turns": 120, "limit_basis": "spawn_record"}
        self.assertEqual(engine._limit_at_run({"limit_notice": 20}, None, ev, 120, [], None, spawn=spawn),
                         (20, "harness_notice"))

    def test_engine_reads_the_spawn_record_without_a_stop_event(self):
        self.spawn()
        self.set_turns(75)
        spawn = engine._spawn_records("S")["tu1"]
        self.assertEqual(engine._limit_at_run({}, None, None, 75, [], None, spawn=spawn), (120, "spawn_record"))

    def test_stop_reason_recorded_and_read_by_engine(self):
        self.spawn()
        ev = self.stop(stop_reason="error_max_turns")
        self.assertIn(ev["stop_reason"], ingest.MAX_TURNS_STOP_REASONS)

    def test_no_stop_reason_in_payload_records_none(self):
        self.assertIsNone(self.stop()["stop_reason"])

    def test_unknown_agent_type_records_no_limit(self):
        ev = self.stop(tuid=None, agent_type="no-such-agent")
        self.assertIsNone(ev["limit_max_turns"])
        self.assertEqual(engine._limit_at_run({}, None, ev, 40, [], None), (40, "frontmatter_at_first_ingest"))

    def test_session_start_no_longer_claims_authority(self):
        self.assertFalse(hasattr(hooks, "_snapshot_limits"))


class PruneTests(_DataDir):
    def test_session_end_prunes_old_spawn_and_limit_records(self):
        old = 15 * 86400
        for sub, name in (("spawns", "OLD.jsonl"), ("spawns", "NEW.jsonl"), ("limits", "OLD.json")):
            d = os.path.join(self.data, sub)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, name), "w") as fh:
                fh.write("{}")
            if name.startswith("OLD"):
                t = os.path.getmtime(os.path.join(d, name)) - old
                os.utime(os.path.join(d, name), (t, t))
        hooks.session_end({"session_id": "S"})  # no transcript: nothing is detached, pruning still runs
        self.assertEqual(sorted(os.listdir(os.path.join(self.data, "spawns"))), ["NEW.jsonl"])
        self.assertEqual(os.listdir(os.path.join(self.data, "limits")), [])


class ApplyTimingTests(_DataDir):
    def setUp(self):
        super().setUp()
        self.agent = os.path.join(self.tmp, "x.md")
        with open(self.agent, "w", encoding="utf-8") as fh:
            fh.write("---\nname: x\nmaxTurns: 40\n---\nbody\n")
        with open(os.path.join(self.data, "recommendations.json"), "w") as fh:
            json.dump({"agents": {"x": {"managed": True, "status": "ok", "path": self.agent,
                                        "maxTurns": {"current": 40, "recommended": 60, "reason": "t"}}}}, fh)
        self._load = engine.load_config
        self.cfg = dict(LEARN_CFG)
        engine.load_config = lambda: self.cfg

    def tearDown(self):
        engine.load_config = self._load
        super().tearDown()

    def turns(self):
        return frontmatter.read(self.agent)["maxTurns"]

    def test_shipped_config_applies_at_session_end(self):
        self.assertEqual(LEARN_CFG["apply_on"], "session_end")
        self.assertEqual(LEARN_CFG["min_obs_lower"], 8)

    def test_session_end_run_applies(self):
        self.cfg["apply_on"] = "session_end"
        self.assertEqual(engine.apply_on(), "session_end")
        self.assertEqual([c["agent"] for c in engine.apply()], ["x"])
        self.assertEqual(self.turns(), "60")

    def test_session_start_catch_up_applies_pending_values(self):
        for mode in ("session_end", "session_start"):
            with open(self.agent, "w", encoding="utf-8") as fh:
                fh.write("---\nname: x\nmaxTurns: 40\n---\nbody\n")
            self.cfg["apply_on"] = mode
            self.assertEqual([c["agent"] for c in hooks._apply_learned()], ["x"], mode)
            self.assertEqual(self.turns(), "60", mode)

    def test_never_applies_nothing_anywhere(self):
        self.cfg["apply_on"] = "never"
        self.assertEqual(hooks._apply_learned(), [])
        self.cfg.update(apply_on="session_end", auto_apply=False)
        self.assertEqual(hooks._apply_learned(), [])
        self.assertEqual(self.turns(), "40")

    def test_start_message_says_next_session(self):
        self.cfg["apply_on"] = "session_end"
        out = hooks.session_start({"session_id": "S"})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("next turn", out)
        self.assertIn("next session", out)  # the startup caveat
        self.assertNotIn("hot-reloads", hooks._apply_learned.__doc__ or "")

    def test_session_end_apply_then_session_start_catch_up_is_a_no_op(self):
        """Effort was judged against recommendations.json's stale `current`, so it was re-applied."""
        with open(self.agent, "w", encoding="utf-8") as fh:
            fh.write("---\nname: x\nmaxTurns: 40\neffort: high\n---\nbody\n")
        with open(os.path.join(self.data, "recommendations.json"), "w") as fh:
            json.dump({"agents": {"x": {"managed": True, "status": "ok", "path": self.agent,
                                        "maxTurns": {"current": 40, "recommended": 40},
                                        "effort": {"current": "high", "recommended": "xhigh", "reason": "r"}}}}, fh)
        self.cfg["apply_on"] = "session_end"
        self.assertEqual([c["updates"] for c in engine.apply()], [{"effort": "xhigh"}])
        self.assertEqual(hooks._apply_learned(), [])
        out = hooks.session_start({"session_id": "S2", "source": "startup"})["hookSpecificOutput"]
        self.assertNotIn("Caught up", out["additionalContext"])
        with open(os.path.join(self.data, "changes.jsonl"), encoding="utf-8") as fh:
            self.assertEqual(len(fh.read().splitlines()), 1)

    def test_apply_logs_only_what_it_wrote(self):
        with open(self.agent, "w", encoding="utf-8") as fh:
            fh.write("---\nname: x\nmaxTurns: 60\neffort: xhigh\n---\nbody\n")  # already at the recommendation
        with open(os.path.join(self.data, "recommendations.json"), "w") as fh:
            json.dump({"agents": {"x": {"managed": True, "status": "ok", "path": self.agent,
                                        "maxTurns": {"current": 40, "recommended": 60},
                                        "effort": {"current": "high", "recommended": "xhigh"}}}}, fh)
        self.assertEqual(engine.apply(), [])
        self.assertEqual(engine.apply(dry_run=True), [])
        self.assertFalse(os.path.exists(os.path.join(self.data, "changes.jsonl")))

    def test_session_end_hook_is_wired(self):
        with open(os.path.join(ROOT, ".claude", "settings.json"), encoding="utf-8") as fh:
            ev = json.load(fh)["hooks"]
        self.assertIn("session-end", json.dumps(ev["SessionEnd"]))


class CompactWindowPolicyTests(unittest.TestCase):
    def test_learner_bounds_floor_600k_upper_is_model_window(self):
        lo, hi = LEARN_CFG["default_bounds"]["autoCompactWindow"]
        self.assertEqual(lo, 600_000)
        for tier, spec in tiers.load()["tiers"].items():
            self.assertEqual(hi, spec["context_window"], tier)

    def test_no_agent_below_floor_so_sync_has_nothing_to_write(self):
        """The floor is a floor: the learner may have raised some agents, never below it."""
        pending = [c for c in tiers.sync() if "autoCompactWindow" in c.get("updates", {})]
        self.assertEqual(pending, [])

    def test_initial_window_clamped_to_tier_window(self):
        cfg = tiers.load()
        name = next(iter(cfg["agents"]))
        cfg["tiers"][cfg["agents"][name]["tier"]]["context_window"] = 200_000
        self.assertEqual(tiers.initial_compact_window(name, cfg), 200_000)
        cfg["agents"][name]["autoCompactWindow"] = 150_000
        self.assertEqual(tiers.initial_compact_window(name, cfg), 150_000)


if __name__ == "__main__":
    unittest.main()
