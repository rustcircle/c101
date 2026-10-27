"""Tests for optional MCP registration in the installer (--adobe, --mcp) and the Adobe entries."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from stack import adobe, install, paths

ADOBE = ("indesign", "illustrator", "photoshop", "after-effects", "premiere-pro")


class AdobeEntriesTest(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(paths.CONFIG_DIR, "mcp.optional.json"), encoding="utf-8") as fh:
            self.servers = json.load(fh)["mcpServers"]

    def test_all_five_apps_tagged_adobe(self):
        self.assertEqual(sorted(install.adobe_servers()), sorted(ADOBE))

    def test_entries_are_stdio_with_note_and_setup(self):
        for name in ADOBE:
            cfg = self.servers[name]
            self.assertEqual(cfg.get("type"), "stdio", name)
            self.assertTrue(cfg.get("command"), name)
            self.assertTrue(cfg.get("_note"), name)
            self.assertTrue(cfg.get("_setup"), name)

    def test_user_entry_drops_private_keys_and_rewrites_paths(self):
        for name in ADOBE:
            entry = install._user_mcp_entry(self.servers[name])
            self.assertFalse([k for k in entry if k.startswith("_")], name)
            self.assertNotIn("CLAUDE_PROJECT_DIR", json.dumps(entry), name)


class InstallFlagsTest(unittest.TestCase):
    def run_main(self, *argv):
        out = io.StringIO()
        calls = []
        with contextlib.redirect_stdout(out), \
                mock.patch.object(install, "base"), \
                mock.patch.object(install, "python_env"), \
                mock.patch.object(install, "link_default_python"), \
                mock.patch.object(install.shutil, "which", return_value=None), \
                mock.patch.object(install, "_register_user_mcp",
                                  side_effect=lambda ctx, n, c, cl: calls.append(n)), \
                mock.patch.object(adobe, "setup", return_value=[]) as setup:
            rc = install.main(list(argv) + ["--dry-run"])
        self.setup_calls = setup.call_args_list
        return rc, calls, out.getvalue()

    def test_adobe_registers_all_five_and_runs_setup(self):
        rc, calls, out = self.run_main("--adobe")
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(calls), sorted(ADOBE))
        self.assertEqual(sorted(self.setup_calls[0].args[1]), sorted(ADOBE))
        self.assertNotIn("photoshop setup:", out)  # automated, so no manual hint

    def test_adobe_no_setup_prints_hints_only(self):
        rc, calls, out = self.run_main("--adobe", "photoshop", "--adobe-no-setup")
        self.assertEqual(calls, ["photoshop"])
        self.assertEqual(self.setup_calls, [])
        self.assertIn("photoshop setup:", out)

    def test_mcp_flag_never_runs_adobe_setup(self):
        self.run_main("--mcp", "photoshop")
        self.assertEqual(self.setup_calls, [])

    def test_no_adobe_unregisters_and_removes_agents(self):
        with contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.object(install, "base"), mock.patch.object(install, "python_env"), \
                mock.patch.object(install, "link_default_python"), \
                mock.patch.object(install, "unregister_optional") as unreg, \
                mock.patch.object(adobe.sys, "platform", "darwin"), \
                mock.patch.object(adobe, "remove_agents") as rm:
            self.assertEqual(install.main(["--no-adobe", "--dry-run"]), 0)
        self.assertEqual(sorted(unreg.call_args.args[1]), sorted(ADOBE))
        rm.assert_called_once()

    def test_setup_failure_sets_exit_code(self):
        with contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.object(install, "base"), mock.patch.object(install, "python_env"), \
                mock.patch.object(install, "link_default_python"), \
                mock.patch.object(install, "_register_user_mcp"), \
                mock.patch.object(adobe, "setup", return_value=["photoshop"]):
            self.assertEqual(install.main(["--adobe", "photoshop", "--dry-run"]), 1)

    def test_adobe_subset_and_mcp_dedup(self):
        rc, calls, _ = self.run_main("--adobe", "photoshop,indesign", "--mcp", "indesign,markitdown")
        self.assertEqual(rc, 0)
        self.assertEqual(calls, ["photoshop", "indesign", "markitdown"])

    def test_unknown_name_fails_before_any_write(self):
        with mock.patch.object(install, "base") as base, self.assertRaises(SystemExit) as cm:
            install.main(["--adobe", "photoshop,lightroomx"])
        self.assertIn("lightroomx", str(cm.exception))
        base.assert_not_called()

    def test_no_claude_cli_prints_manual_command(self):
        out = io.StringIO()
        cfg = {"type": "stdio", "command": "${CLAUDE_PROJECT_DIR:-.}/bin/mcp-run", "args": ["x"], "_note": "n"}
        with contextlib.redirect_stdout(out):
            install._register_user_mcp(install.Ctx(True), "demo", cfg, None)
        self.assertIn("claude mcp add-json --scope user demo", out.getvalue())
        self.assertNotIn("_note", out.getvalue())


class AdobeSetupTest(unittest.TestCase):
    def test_tool_env_puts_nix_and_brew_first_without_duplicates(self):
        with mock.patch.dict(os.environ, {"PATH": "/usr/bin:/run/current-system/sw/bin"}):
            parts = adobe.tool_env()["PATH"].split(os.pathsep)
        self.assertIn(os.path.expanduser("~/.nix-profile/bin"), parts)
        self.assertEqual(parts.count("/run/current-system/sw/bin"), 1)
        self.assertEqual(parts[-1], "/run/current-system/sw/bin")

    def test_one_failure_does_not_stop_the_others(self):
        ran = []
        boom = mock.Mock(side_effect=RuntimeError("no clone"))
        fine = mock.Mock(side_effect=lambda ctx: ran.append("indesign"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(adobe.sys, "platform", "darwin"), \
                mock.patch.object(adobe, "which", return_value="/x"), \
                mock.patch.dict(adobe.SETUP, {"photoshop": boom, "indesign": fine}):
            failed = adobe.setup(install.Ctx(True), ["photoshop", "indesign"])
        self.assertEqual(failed, ["photoshop"])
        self.assertEqual(ran, ["indesign"])
        self.assertIn("photoshop setup FAILED: no clone", out.getvalue())
        self.assertNotIn("Enable Developer Mode", out.getvalue())  # no manual steps for a failed app
        self.assertIn("allow 'node' to control Adobe InDesign", out.getvalue())

    def test_missing_tool_reported_with_nix_hint(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(adobe.sys, "platform", "darwin"), \
                mock.patch.object(adobe, "which", return_value=None):
            self.assertEqual(adobe.setup(install.Ctx(True), ["after-effects"]), ["after-effects"])
        self.assertIn("missing git, node, npm on PATH (nix", out.getvalue())

    def test_non_macos_skips(self):
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(adobe.sys, "platform", "linux"):
            self.assertEqual(adobe.setup(install.Ctx(True), list(ADOBE)), [])

    def test_launch_agent_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()) as out, \
                mock.patch.object(adobe, "AGENTS_DIR", d):
            adobe.launch_agent(install.Ctx(True), "com.c101.test", ["/x/node", "proxy.js"], d)
            self.assertEqual(os.listdir(d), [])
        self.assertIn("install LaunchAgent com.c101.test", out.getvalue())

    def test_pins_are_full_shas(self):
        for url, sha in adobe.REPOS.values():
            self.assertRegex(sha, r"^[0-9a-f]{40}$", url)


if __name__ == "__main__":
    unittest.main()
