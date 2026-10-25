## Summary

<!-- What changed, why, and who or what is affected? Link the related issue,
decision record, task, finding, or review item when one exists. -->

## Related issue or decision

<!-- Use a closing keyword only when this pull request completes the issue. -->

Closes #

## Type of change

- [ ] Feature or behavior change
- [ ] Bug fix
- [ ] Refactor or performance improvement
- [ ] Documentation or process change
- [ ] Dependency update
- [ ] CI/CD or repository policy change
- [ ] Image, workflow or deployment change
- [ ] Security or privacy change
- [ ] Breaking change

## Scope and impact

<!-- Describe affected components, APIs, data, permissions, tenancy, migrations,
operations, rollout, compatibility, and rollback considerations. Say "None"
where a category does not apply. -->

## Verification

<!-- List exact commands or checks and what each result proves. State checks not
run and why. Distinguish static, local, CI, staging, and production evidence. -->

- Checks run:
- Important result or evidence:
- Checks not run and why:
- Evidence level: [ ] Static [ ] Local [ ] CI [ ] Staging [ ] Production

## Image or workflow changes only

<!-- Remove this section when the Dockerfile, the base image, the workflows and the scan files are untouched. -->

- [ ] The base image (if changed) is pinned by digest in `versions.env` and in both `FROM` lines, and `bash scripts/scan-image.sh` was run.
- [ ] Every new or changed `uses:` is a full commit SHA with a version comment; runners are `ubuntu-26.04`; top-level `permissions` is `contents: read`.
- [ ] Any new entry in `.trivyignore.yaml` has an id, a reason, an owner and an expiry date.
- [ ] The tests that pin the workflow set (`tests/unit/test_workflows.py`) were updated when a workflow was added or removed.
- [ ] Rollout and rollback are described (for a release workflow, see the README section "Releasing the engine").

## Security and data review

- [ ] No credentials, private keys, tokens, connection strings, personal data, customer data, or sensitive content was added.
- [ ] Telemetry is content-free and uses correlation identifiers rather than paths, query strings, route values, document identifiers, or payloads.
- [ ] Authorization, tenant isolation, least privilege, and denial paths were tested where applicable.
- [ ] New dependencies, base images, and GitHub Actions are pinned or controlled according to repository policy.
- [ ] No automated path can activate, approve, sign, file, or make an authoritative write unless explicitly approved.

## Documentation and operations

- [ ] User-facing or developer documentation updated when needed.
- [ ] `CHANGELOG.md` updated in this pull request; a decision record (`docs/adr/`) or `VALIDATION.md` entry added when needed.
- [ ] If the change reaches the AddOn (engine surface, tool schemas, detector ids, evidence kinds, release workflows), its `docs/whats-new-upstream.md` entry is written here, or this description says why none is needed.
- [ ] Remaining work is recorded in the repository's established tracker.
- [ ] Rollout and rollback owners are identified when the change affects a shared environment.

## Author checklist

- [ ] The pull request is focused and unrelated edits were removed.
- [ ] Tests cover changed behavior and important failure, boundary, and denial paths.
- [ ] The final diff contains no local configuration, generated artifacts, or secrets that do not belong.
- [ ] Required reviewers, approvals, environments, and CI checks are complete or explicitly called out.
