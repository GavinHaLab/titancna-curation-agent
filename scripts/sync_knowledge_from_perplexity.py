#!/usr/bin/env python3
"""Sync the shared curation methodology from the Perplexity project's file repo
into this GitHub repo, then optionally commit + push.

What this syncs (the shared source of truth):
  knowledge/skills.md
  knowledge/titan_reference.md

What this NEVER touches (these intentionally differ between the two versions):
  src/titan_curation/cli.py            (local-path input vs. OneDrive connector)
  src/titan_curation/config.py         (API keys vs. platform model access)
  src/titan_curation/reviewers/*       (direct Anthropic/Gemini API calls vs. subagents)
  .env.example / config/config.example.yaml
  anything under .git/, results/, .plot_cache/

Usage (run from anywhere; paths default to the well-known checkout locations
inside a Perplexity Computer sandbox, but can be overridden):

    python scripts/sync_knowledge_from_perplexity.py \
        --project-files /home/user/workspace/projects/<project-slug>/files \
        --repo-root /home/user/workspace/titan-cna-curation-agent \
        [--commit] [--push]

Run with no --commit/--push to just see a diff (dry run, the default).
This script is meant to be invoked by the agent (or by any teammate's own
agent session, since they have push access to this repo) whenever someone
says "sync to GitHub" after editing knowledge/skills.md or
knowledge/titan_reference.md in the Perplexity project.
"""
from __future__ import annotations

import argparse
import filecmp
import os
import shutil
import subprocess
import sys

SYNCED_FILES = ["skills.md", "titan_reference.md"]


def sync(project_files: str, repo_root: str) -> list[str]:
    src_dir = os.path.join(project_files, "knowledge")
    dst_dir = os.path.join(repo_root, "src", "titan_curation", "knowledge")
    if not os.path.isdir(src_dir):
        raise SystemExit(f"Source knowledge dir not found: {src_dir}")
    os.makedirs(dst_dir, exist_ok=True)

    changed = []
    for name in SYNCED_FILES:
        src = os.path.join(src_dir, name)
        dst = os.path.join(dst_dir, name)
        if not os.path.isfile(src):
            print(f"  (skip) {name}: not found in project files")
            continue
        if os.path.isfile(dst) and filecmp.cmp(src, dst, shallow=False):
            print(f"  (unchanged) {name}")
            continue
        shutil.copyfile(src, dst)
        changed.append(name)
        print(f"  (updated) {name}")
    return changed


def git(repo_root: str, *args: str) -> str:
    result = subprocess.run(["git", "-C", repo_root, *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n{result.stderr}")
    return result.stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-files", required=True,
                     help="Path to the Perplexity project's synced file repo checkout "
                          "(the directory containing knowledge/skills.md)")
    ap.add_argument("--repo-root", default=os.getcwd(),
                     help="Path to this GitHub repo's local checkout (default: cwd)")
    ap.add_argument("--commit", action="store_true", help="git commit the change")
    ap.add_argument("--push", action="store_true", help="git push after committing (implies --commit)")
    args = ap.parse_args()

    print("Comparing knowledge/ files ...")
    changed = sync(args.project_files, args.repo_root)

    if not changed:
        print("\nNothing to sync -- GitHub repo already matches the Perplexity project.")
        return 0

    print(f"\nUpdated: {', '.join(changed)}")

    if args.push:
        args.commit = True

    if args.commit:
        # Make sure this commit is attributed to whoever is actually running
        # this session, not a stale/hardcoded identity -- see git_identity_setup.sh.
        identity_script = os.path.join(args.repo_root, "scripts", "git_identity_setup.sh")
        if os.path.isfile(identity_script):
            subprocess.run(["bash", identity_script], cwd=args.repo_root, check=True)
        git(args.repo_root, "add", "src/titan_curation/knowledge")
        msg = f"Sync curation methodology from Perplexity project: {', '.join(changed)}"
        git(args.repo_root, "commit", "-m", msg)
        print(f"Committed: {msg}")
        if args.push:
            git(args.repo_root, "push")
            print("Pushed to origin.")
    else:
        print("Dry run only -- pass --commit (and --push) to actually commit/push this change.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
