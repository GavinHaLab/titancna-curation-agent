# Contributing

## Committing from a Perplexity Computer session (any collaborator)

This repo lives under the `GavinHaLab` GitHub organization. Anyone in the org
already has write (or admin) access to it via the org's default permissions —
no extra invite needed. To commit and have it correctly show up under **your
own** GitHub profile (avatar, contribution graph, `?author=<you>` filter):

1. Make sure your own GitHub account is connected under your own Perplexity
   account (Settings → Connectors → GitHub). Each person must connect their
   own account — this is not shared across teammates.
2. In your Computer session, before committing, run:
   ```bash
   bash scripts/git_identity_setup.sh
   ```
   This detects whichever GitHub account your session is authenticated as and
   configures `git config user.name`/`user.email` for this checkout to match
   a *verified* email on that account (your `@users.noreply.github.com`
   alias — this works even if your work email isn't added/verified on
   GitHub, and doesn't leak your real email into the public commit history).
3. Commit and push as normal. GitHub will now correctly attribute the commit
   to you.

**Why this matters:** GitHub only links a commit to a profile if the commit's
author email exactly matches a *verified* email on that account. A commit
authored as `you@fredhutch.org` will show up as an "unlinked" commit with no
avatar and won't count on your contribution graph unless that exact email is
verified on your GitHub account — which it usually isn't. Skipping step 2 is
the most common reason someone's own commits don't appear under their profile.

## Syncing curation methodology

See the "Syncing curation methodology from the Perplexity project" section in
`README.md` for `scripts/sync_knowledge_from_perplexity.py`. Run
`git_identity_setup.sh` first so the sync commit is attributed to you too.

## Code layout

See `README.md` → "Repo layout" for what lives where. Keep
`src/titan_curation/knowledge/*.md` (curation methodology) as the one thing
intentionally shared with the Perplexity Computer prototype; everything else
here (local-path input, direct API-key reviewers) is CLI-specific by design.
