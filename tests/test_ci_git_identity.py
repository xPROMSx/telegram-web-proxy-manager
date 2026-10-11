"""Synthetic-only metadata regression tests; no private identities in fixtures."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import ci_git_identity as identity


class IdentityPolicyTests(unittest.TestCase):
    def test_approved_public_profiles_and_github_agents(self):
        good = [
            ("xPROMSx", identity.OWNER_EMAIL),
            (identity.OWNER_PUBLIC_ALIAS, identity.OWNER_EMAIL),
            ("GitHub", "noreply@github.com"),
            ("GitHub", "github@users.noreply.github.com"),
            ("fixture-user", "123+fixture-user@users.noreply.github.com"),
            ("fixture-user", "fixture-user@users.noreply.github.com"),
            ("github-actions[bot]", "41898282+github-actions[bot]@users.noreply.github.com"),
            ("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com"),
        ]
        for name, mail in good:
            with self.subTest(kind=mail.split("@")[-1]):
                self.assertTrue(identity.allowed_identity(name, mail))

    def test_private_and_mismatched_identities_refused(self):
        bad = [
            ("Private Example", "person@example.invalid"),
            ("Private Example", identity.OWNER_EMAIL),
            ("fake-user", "123+other-user@users.noreply.github.com"),
            ("fixture-user", "fixture-user@other.invalid"),
            ("fixture-user", "notanid+fixture-user@users.noreply.github.com"),
            ("fixture-user", "0+fixture-user@users.noreply.github.com"),
            ("GitHub", "person@example.invalid"),
            ("fixture user", "123+fixture-user@users.noreply.github.com"),
            ("github-actions[bot]", "person@example.invalid"),
        ]
        for name, mail in bad:
            with self.subTest(kind=mail.split("@")[-1]):
                self.assertFalse(identity.allowed_identity(name, mail))

    def test_metadata_from_pr_only_no_upstream_or_error_leak(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args, env=None):
                return subprocess.check_output(["git", *args], cwd=root,
                                               env=env, stderr=subprocess.DEVNULL).decode().strip()
            git("init", "-q")
            git("config", "commit.gpgsign", "false")
            def commit(a_name, a_email, c_name, c_email, message):
                env = dict(os.environ, GIT_AUTHOR_NAME=a_name, GIT_AUTHOR_EMAIL=a_email,
                           GIT_COMMITTER_NAME=c_name, GIT_COMMITTER_EMAIL=c_email)
                git("commit", "--allow-empty", "-qm", message, env=env)
                return git("rev-parse", "HEAD")
            base = commit("Historical Private", "historical@example.invalid",
                          "Historical Private", "historical@example.invalid", "historical")
            first = commit("xPROMSx", identity.OWNER_EMAIL, "GitHub", "noreply@github.com", "new public")
            self.assertEqual(identity.check_pr(base, first, root), (True, "1 PR commit(s) checked"))
            second = commit("github-actions[bot]", "41898282+github-actions[bot]@users.noreply.github.com",
                            "github-actions[bot]", "41898282+github-actions[bot]@users.noreply.github.com",
                            "bot")
            self.assertEqual(identity.check_pr(base, second, root), (True, "2 PR commit(s) checked"))
            bad = commit("Private Example", "person@example.invalid", "xPROMSx",
                         identity.OWNER_EMAIL, "private author")
            ok, message = identity.check_pr(base, bad, root)
            self.assertFalse(ok)
            self.assertIn("author identity not approved", message)
            self.assertNotIn("person@", message)
            bad2 = commit("xPROMSx", identity.OWNER_EMAIL, "Private Example",
                          "person@example.invalid", "private committer")
            # Start at the preceding commit: that earlier bad author is outside this PR.
            ok, message = identity.check_pr(bad, bad2, root)
            self.assertFalse(ok)
            self.assertIn("committer identity not approved", message)
            self.assertNotIn("person@", message)
            self.assertFalse(identity.check_pr("0" * 40, bad2, root)[0])
            self.assertFalse(identity.check_pr(base, "f" * 40, root)[0])


if __name__ == "__main__":
    unittest.main()
