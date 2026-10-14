#!/usr/bin/env bash
# Prepare an update branch. Publishing and auto-merge are deliberately separate.
set -euo pipefail

base="${BASE_BRANCH:-master}"
branch="${SYNC_BRANCH:-automation/upstream-sync}"
upstream="${UPSTREAM_URL:-https://github.com/kovidgoyal/kitty.git}"
upstream_branch="${UPSTREAM_BRANCH:-master}"

git check-ref-format "refs/heads/$base"
git check-ref-format "refs/heads/$branch"
git check-ref-format "refs/heads/$upstream_branch"
[[ "$base" != "$branch" ]] || { echo 'Sync branch must not be the distribution branch' >&2; exit 1; }
[[ -z "$(git status --porcelain)" ]] || { echo 'Refusing to sync a dirty checkout' >&2; exit 1; }

git fetch --no-tags origin "+refs/heads/$base:refs/remotes/origin/$base"
# Return errors other than a genuinely absent remote branch to the caller.
remote_branch="$(git ls-remote --heads origin "refs/heads/$branch")"
if [[ -n "$remote_branch" ]]; then
    git fetch --no-tags origin "+refs/heads/$branch:refs/remotes/origin/$branch"
    git switch -C "$branch" "origin/$branch"
    git merge --no-edit "origin/$base"
else
    git switch -C "$branch" "origin/$base"
fi

git fetch --no-tags "$upstream" "refs/heads/$upstream_branch:refs/remotes/kitty-upstream/$upstream_branch"
# Keep the upstream history and the fork's commits. Never rebase or push the base.
if ! git merge --no-edit "refs/remotes/kitty-upstream/$upstream_branch"; then
    git merge --abort
    echo 'Upstream merge conflicts: manual adaptation is required; nothing was pushed.' >&2
    exit 1
fi

echo "Prepared $branch; run dependency refresh and all checks before publishing."
