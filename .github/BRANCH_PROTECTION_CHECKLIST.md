# Branch Protection Checklist

Use this checklist to make sure `lint`, `typecheck`, and `test` must pass before merge.

## Recommended Rule

- [ ] Open GitHub: `Settings` -> `Branches` -> `Add branch protection rule`
- [ ] Branch name pattern: `main`
- [ ] Enable `Require a pull request before merging`
- [ ] Enable `Require approvals` (recommended: at least `1`)
- [ ] Enable `Dismiss stale pull request approvals when new commits are pushed`
- [ ] Enable `Require status checks to pass before merging`
- [ ] Enable `Require branches to be up to date before merging`
- [ ] Add required checks from workflow `CI`:
- [ ] `lint`
- [ ] `typecheck`
- [ ] `test (3.10)`
- [ ] `test (3.11)`
- [ ] `test (3.12)`
- [ ] Enable `Require conversation resolution before merging` (recommended)
- [ ] Enable `Do not allow bypassing the above settings` (recommended for protected repos)

## Optional Hardening

- [ ] Enable `Require signed commits` (if your team uses commit signing)
- [ ] Enable `Require linear history` (if you want to block merge commits)
- [ ] Enable `Restrict who can push to matching branches` (for tighter control)
