"""Check author and committer privacy for commits introduced by one PR.

No credentials/network required; never print rejected identities to CI logs.
"""
import argparse
import re
import subprocess
import sys

OWNER_NAME = "xPROMSx"
OWNER_EMAIL = "102687702+xPROMSx@users.noreply.github.com"
# Public GitHub profile display alias on existing GitHub-web/API commits.
OWNER_PUBLIC_ALIAS = "Proms"
NOREPLY_SUFFIX = "@users.noreply.github.com"
SHA = re.compile(r"[0-9a-f]{40}\Z")
HANDLE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,38})\Z")
BOT = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*\[bot\]\Z")


def allowed_identity(name, email):
    """Allow verified public-format identities, never arbitrary real addresses."""
    if not isinstance(name, str) or not isinstance(email, str):
        return False
    if name in (OWNER_NAME, OWNER_PUBLIC_ALIAS) and email == OWNER_EMAIL:
        return True
    if name == "GitHub" and email in ("noreply@github.com", "github@users.noreply.github.com"):
        return True
    if not email.endswith(NOREPLY_SUFFIX):
        return False
    local = email[:-len(NOREPLY_SUFFIX)]
    if "+" in local:
        numeric_id, handle = local.split("+", 1)
        if not numeric_id.isascii() or not numeric_id.isdecimal() or not numeric_id.strip("0"):
            return False
    else:
        handle = local
    # GitHub public username or a conventional GitHub App bot identity.
    return bool((HANDLE.fullmatch(handle) or BOT.fullmatch(handle)) and name.casefold() == handle.casefold())


def git(*args, repository="."):
    return subprocess.check_output(["git", *args], cwd=repository, stderr=subprocess.DEVNULL, timeout=30)


def check_pr(base, head, repository="."):
    if not all(isinstance(x, str) and SHA.fullmatch(x) and x != "0" * 40 for x in (base, head)):
        return False, "invalid commit revision"
    try:
        for sha in (base, head):
            if git("rev-parse", "--verify", sha + "^{commit}", repository=repository).decode().strip() != sha:
                return False, "unavailable commit revision"
        # PR-only set difference: commits reachable from base (including upstream)
        # are never checked, even when the PR branch has merged its base.
        commits = git("rev-list", "--reverse", base + ".." + head, repository=repository).decode().splitlines()
        if not commits or len(commits) > 500 or any(not SHA.fullmatch(x) for x in commits):
            return False, "empty, oversized or invalid PR commit set"
        for sha in commits:
            data = git("show", "-s", "--format=%an%x00%ae%x00%cn%x00%ce", sha, repository=repository)
            values = data.removesuffix(b"\n").split(b"\x00")
            if len(values) != 4:
                return False, "malformed commit metadata at " + sha[:12]
            try:
                author, author_email, committer, committer_email = [value.decode("utf-8") for value in values]
            except UnicodeError:
                return False, "invalid identity encoding at " + sha[:12]
            if not allowed_identity(author, author_email):
                return False, "author identity not approved at " + sha[:12]
            if not allowed_identity(committer, committer_email):
                return False, "committer identity not approved at " + sha[:12]
        return True, str(len(commits)) + " PR commit(s) checked"
    except (OSError, UnicodeError, subprocess.SubprocessError):
        return False, "unable to inspect PR commits"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--event", required=True)
    args = parser.parse_args()
    if args.event == "push":
        print("Commit identity: PASS (PR-only check; push event)")
        return 0
    if args.event != "pull_request":
        print("Commit identity: FAIL (unexpected event)")
        return 1
    ok, message = check_pr(args.base, args.head)
    print("Commit identity: " + ("PASS" if ok else "FAIL") + " (" + message + ")")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
