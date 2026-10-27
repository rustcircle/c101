"""Tests for optional MCP registration in the installer (--adobe, --mcp) and the Adobe entries."""
import contextlib
import io
import json
import os
import unittest
from unittest import mock

from stack import install, paths

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
                                  side_effect=lambda ctx, n, c, cl: calls.append(n)):
            rc = install.main(list(argv) + ["--dry-run"])
        return rc, calls, out.getvalue()

    def test_adobe_registers_all_five(self):
        rc, calls, out = self.run_main("--adobe")
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(calls), sorted(ADOBE))
        self.assertIn("photoshop setup:", out)

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


if __name__ == "__main__":
    unittest.main()
