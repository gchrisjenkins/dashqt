# Branch Protection Checklist

Use this checklist to make sure the full matrix checks must pass before merge to `main`.

## Recommended Rule

- [ ] Open GitHub: `Settings` -> `Branches` -> `Add branch protection rule`
- [ ] Branch name pattern: `main`
- [ ] Enable `Require a pull request before merging`
- [ ] Enable `Require approvals` (recommended: at least `1`)
- [ ] Enable `Dismiss stale pull request approvals when new commits are pushed`
- [ ] Enable `Require status checks to pass before merging`
- [ ] Enable `Require branches to be up to date before merging`
- [ ] Add required checks from workflow `CI Full`:
- [ ] `full-lint`
- [ ] `full-typecheck`
- [ ] `full-test (ubuntu-22.04, py3.10)`
- [ ] `full-test (ubuntu-22.04, py3.11)`
- [ ] `full-test (ubuntu-22.04, py3.12)`
- [ ] `full-test (ubuntu-22.04, py3.13)`
- [ ] `full-test (ubuntu-latest, py3.12)`
- [ ] `full-test (macos-latest, py3.12)`
- [ ] Enable `Require conversation resolution before merging` (recommended)
- [ ] Enable `Do not allow bypassing the above settings` (recommended for protected repos)

## Optional Develop Rule

- [ ] Add a separate branch protection rule for `develop`
- [ ] Add required checks from workflow `CI Fast`:
- [ ] `fast-lint`
- [ ] `fast-typecheck`
- [ ] `fast-test (ubuntu-22.04, py3.12)`

## Optional Hardening

- [ ] Enable `Require signed commits` (if your team uses commit signing)
- [ ] Enable `Require linear history` (if you want to block merge commits)
- [ ] Enable `Restrict who can push to matching branches` (for tighter control)
