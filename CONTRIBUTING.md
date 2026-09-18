# Contributing and releases

Use a fork/feature branch. Keep resume tailoring in ignored files; contributions
should change only reusable source, docs or synthetic fixtures.

1. Run `./scripts/setup.sh` and install `requirements-dev.txt` in `.venv`.
2. Change code and add a regression test for behavior changes.
3. Run `make test` and `make demo` with the example profile in a clean checkout.
4. Inspect `git diff` and stage explicit paths. Review any new public path before
   adding it to `public-files.txt`; keep that inventory sorted and exact.
5. Run `make check` and `.venv/bin/python -m pip_audit -r requirements.txt --strict`.
6. Open a PR. Both matrix jobs must pass before merging.

The mandatory CI checks are `test (3.10)` and `test (3.12)`. Fork owners should
protect `main` with those required checks, require PRs, block force pushes/deletions,
and restrict direct pushes. Repository settings are not copied automatically when
forking. Do not require another person's approval on a single-maintainer fork unless
you actually have another reviewer available. Enable dependency alerts and secret
scanning/push protection where available in repository settings.

CI intentionally has no Notion credentials. Never use real application data in a
fixture. The release archive is a `git archive` of the committed public tree; local
ignored files cannot enter it. Packaging refuses an index that differs from HEAD.

## Release procedure

After merging a verified commit to main:

```sh
git switch main
git pull --ff-only
git tag v0.1.1
git push origin v0.1.1
```

Choose a new semantic version appropriate to the change. Tagging triggers the Release
workflow, which reruns CI and only then publishes the source archive and SHA256SUMS.
No server deployment or Notion write happens. Downloaders can verify the archive
using `sha256sum -c SHA256SUMS` (Linux) or `shasum -a 256 -c SHA256SUMS` (macOS).
If a release check fails, fix the cause through a PR; do not bypass the verification job.

Dependency updates should modify pins, pass the audit, and verify the fictional PDF
on both supported CI versions. Exact application runtime versions are pinned;
development-tool transitive dependencies are resolved by pip, so those are not a full
hash-locked environment. System TeX/Poppler versions come from the OS package manager.
