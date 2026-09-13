#!/usr/bin/env bash
# Configure git commit identity for THIS repo checkout to match whichever
# GitHub account is currently authenticated (via `gh`) -- so commits made from
# a Perplexity Computer session are correctly attributed to the person actually
# running that session, not to a hardcoded name/email.
#
# Why this exists: GitHub only links a commit to a profile (and counts it on
# your contribution graph) if the commit's author email is a VERIFIED email on
# that GitHub account. A work email (e.g. name@fredhutch.org) is very often
# NOT added/verified on someone's personal GitHub account, so commits made
# with it show up as "unlinked" -- no author avatar, invisible under
# `?author=<username>`, not counted in your contributions graph.
#
# Fix: always commit as <login>@users.noreply.github.com (GitHub's own
# "keep my email private" alias), which is guaranteed to be verified for
# whoever `gh` is currently authenticated as, and doesn't leak anyone's real
# email into a public repo's history.
#
# Run this once per session/checkout before committing:
#   bash scripts/git_identity_setup.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

LOGIN=$(gh api user --jq '.login')
NAME=$(gh api user --jq '.name // .login')
USER_ID=$(gh api user --jq '.id')
NOREPLY_EMAIL="${USER_ID}+${LOGIN}@users.noreply.github.com"

git -C "$REPO_ROOT" config user.name "$NAME"
git -C "$REPO_ROOT" config user.email "$NOREPLY_EMAIL"

echo "Configured git identity for this checkout:"
echo "  user.name  = $NAME"
echo "  user.email = $NOREPLY_EMAIL  (GitHub account: $LOGIN)"
echo ""
echo "Commits made from here will now show up under github.com/$LOGIN"
echo "and count toward that account's contribution graph."
