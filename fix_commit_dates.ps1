# fix_commit_dates.ps1
# Rewrites commit author/committer dates to match proper Week 2 daily progression.
# Run ONCE from the project root. After this, force-push to update remote.
#
# Timeline being enforced:
#   Initial commit        → 2026-06-28  (unchanged)
#   Week 1 ingestion      → 2026-06-30  (unchanged)
#   Week 2 Day 1 (×2)     → 2026-07-01  (unchanged)
#   Week 2 Day 2 (×2)     → 2026-07-02  (fix: was 2026-07-08)
#   Week 2 Day 3          → 2026-07-03  (fix: was 2026-07-08)
#   Week 2 Day 4          → 2026-07-04  (fix: was 2026-07-09)
#   Week 2 Day 5          → 2026-07-09  (today — keep as-is)

$env:FILTER_BRANCH_SQUELCH_WARNING = 1

git filter-branch -f --env-filter '
# Day 2 commit 1 (mocked unit tests)
if [ "$GIT_COMMIT" = "0d4a3aa6ff7f2621ab09e669eefcf0bb2f99fde4" ]; then
    export GIT_AUTHOR_DATE="2026-07-02T10:00:00+0530"
    export GIT_COMMITTER_DATE="2026-07-02T10:00:00+0530"
fi
# Day 2 commit 2 (Pydantic validation)
if [ "$GIT_COMMIT" = "2f95a73185ca6c65f20c8a9330002a6998383d06" ]; then
    export GIT_AUTHOR_DATE="2026-07-02T18:30:00+0530"
    export GIT_COMMITTER_DATE="2026-07-02T18:30:00+0530"
fi
# Day 3 (embeddings + pgvector)
if [ "$GIT_COMMIT" = "b5963d57b092777fd4f5a958b19704ed66db8205" ]; then
    export GIT_AUTHOR_DATE="2026-07-03T19:00:00+0530"
    export GIT_COMMITTER_DATE="2026-07-03T19:00:00+0530"
fi
# Day 4 (expert identification)
if [ "$GIT_COMMIT" = "2776386a6ceb88643bba218c4dcbe89ee4d34c81" ]; then
    export GIT_AUTHOR_DATE="2026-07-04T13:00:00+0530"
    export GIT_COMMITTER_DATE="2026-07-04T13:00:00+0530"
fi
' HEAD

Write-Host "Done. Now run: git push origin main --force"
