"""scripts/release-publish.py: the steps that verify the attestations and turn a draft into a public release.

A v* tag cannot be moved or deleted, so a release that goes public with the wrong files, or goes public before
everything has been checked, is permanent. `gh` is replaced by a small fake of the parts of GitHub these steps use, so
every path is exercised without a network."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release-publish.py"
REPO = "owner/repo"
TAG = "v0.1.0"
SHA = "0123456789abcdef0123456789abcdef01234567"
WORKFLOW = ".github/workflows/publish-core.yml"
REF = f"refs/tags/{TAG}"
WHEEL = "cloud_crawler_core-0.1.0-py3-none-any.whl"
SDIST = "cloud_crawler_core-0.1.0.tar.gz"
SBOM = "cloud-crawler-core.cdx.json"


def _load():
    spec = importlib.util.spec_from_file_location("release_publish", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rp = _load()
REAL_SLEEP = rp.sleep


def make_files(root: Path) -> Path:
    """The downloaded `release-files` artifact."""
    (root / "dist").mkdir(parents=True)
    (root / "sbom").mkdir()
    (root / "dist" / WHEEL).write_bytes(b"wheel bytes")
    (root / "dist" / SDIST).write_bytes(b"sdist bytes")
    (root / "sbom" / SBOM).write_text("{}", encoding="utf-8")
    (root / "release-notes.md").write_text("### Added\n\n- The first release.\n", encoding="utf-8")
    return root


class FakeGitHub:
    """The parts of `gh` that release-publish.py uses, with a switch for each way GitHub can disappoint."""

    def __init__(self, directory: Path, **options):
        self.directory = directory
        self.calls: list[tuple[str, ...]] = []
        self.releases: list[dict] = options.pop("releases", [])
        self.drop = options.pop("drop", None)  # an asset that does not arrive
        self.state = options.pop("state", "uploaded")
        self.digest = options.pop("digest", "right")  # "right", "wrong" or None (an API that reports no digest)
        self.create_fails = options.pop("create_fails", False)
        self.patch_fails = options.pop("patch_fails", False)
        self.patch_keeps_draft = options.pop("patch_keeps_draft", False)
        self.list_fails = options.pop("list_fails", False)
        self.invisible_lists = options.pop("invisible_lists", 0)  # listings that do not show the new draft yet
        self.verify_results = options.pop("verify_results", [0])  # return codes of the attestation checks, in turn
        assert not options, options

    def __call__(self, *args: str):
        self.calls.append(args)
        if args[:2] == ("attestation", "verify"):
            code = self.verify_results.pop(0) if len(self.verify_results) > 1 else self.verify_results[0]
            return _Done(code, "", "HTTP 404: no attestations found" if code else "")
        if args[:2] == ("api", "--paginate"):
            if self.list_fails:
                return _Done(1, "", "HTTP 500")
            if self.invisible_lists > 0 and any(c[:2] == ("release", "create") for c in self.calls):
                self.invisible_lists -= 1
                return _Done(0, "[]", "")
            return _Done(0, "".join(json.dumps([release]) for release in self.releases) or "[]", "")
        if args[:2] == ("release", "create"):
            return self.create(args)
        if args[:3] == ("api", "--method", "PATCH"):
            return self.patch(args)
        if args[0] == "api" and "/releases/" in args[1]:
            release = next(r for r in self.releases if r["id"] == int(args[1].rsplit("/", 1)[1]))
            return _Done(0, json.dumps(release), "")
        raise AssertionError(f"unexpected gh call: {args}")

    def create(self, args: tuple[str, ...]):
        if self.create_fails:
            return _Done(1, "", "HTTP 422: tag does not exist")
        paths = [Path(a) for a in args[args.index("--notes-file") + 2 :]]
        assets = []
        for path in paths:
            if path.name == self.drop:
                continue
            digest = {"right": f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}", "wrong": "sha256:" + "0" * 64}
            asset = {"name": path.name, "state": self.state}
            if self.digest:
                asset["digest"] = digest[self.digest]
            assets.append(asset)
        self.releases.append({"id": 77, "tag_name": args[2], "draft": True, "assets": assets, "html_url": "https://x"})
        return _Done(0, "https://x", "")

    def patch(self, args: tuple[str, ...]):
        if self.patch_fails:
            return _Done(1, "", "HTTP 403")
        if not self.patch_keeps_draft:
            next(r for r in self.releases if r["id"] == int(args[3].rsplit("/", 1)[1]))["draft"] = False
        return _Done(0, "{}", "")


class _Done:
    def __init__(self, returncode: int, stdout: str, stderr: str):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


@pytest.fixture
def files(tmp_path):
    return make_files(tmp_path / "release-files")


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    monkeypatch.setattr(rp, "sleep", lambda seconds: None)


def use(monkeypatch, fake: FakeGitHub) -> FakeGitHub:
    monkeypatch.setattr(rp, "gh", fake)
    return fake


def verbs(fake: FakeGitHub) -> list[str]:
    names = []
    for call in fake.calls:
        if call[0] == "release":
            names.append("create")
        elif call[:3] == ("api", "--method", "PATCH"):
            names.append("PATCH")
        elif call[:2] == ("api", "--paginate"):
            names.append("list")
        elif call[0] == "api":
            names.append("get")
    return names


# --- verify-attestations -----------------------------------------------------------------------------------------


def test_the_attestation_check_names_this_workflow_this_ref_and_this_commit():
    path = Path("dist") / "x.whl"
    command = rp.verify_command(path, REPO, rp.SBOM, WORKFLOW, REF, SHA)
    assert command == [
        "attestation",
        "verify",
        str(path),
        "--repo",
        REPO,
        "--predicate-type",
        "https://cyclonedx.org/bom",
        "--signer-workflow",
        f"{REPO}/{WORKFLOW}",
        "--source-ref",
        REF,
        "--source-digest",
        SHA,
    ]


def test_every_file_is_verified_for_both_the_provenance_and_the_sbom_with_the_strict_flags(files, monkeypatch, capsys):
    fake = use(monkeypatch, FakeGitHub(files))
    assert rp.verify_attestations(files / "dist", REPO, WORKFLOW, REF, SHA) == []
    assert len(fake.calls) == 4
    seen = {(Path(c[2]).name, c[c.index("--predicate-type") + 1]) for c in fake.calls}
    assert seen == {(w, p) for w in (WHEEL, SDIST) for p in (rp.PROVENANCE, rp.SBOM)}
    assert rp.PROVENANCE == "https://slsa.dev/provenance/v1" and rp.SBOM == "https://cyclonedx.org/bom"
    for call in fake.calls:
        for flag in ("--repo", "--signer-workflow", "--source-ref", "--source-digest"):
            assert flag in call, f"the loose form (without {flag}) must never be used"
        assert call[call.index("--source-ref") + 1] == REF and call[call.index("--source-digest") + 1] == SHA
        assert call[call.index("--signer-workflow") + 1] == f"{REPO}/{WORKFLOW}"
    assert "verified https://cyclonedx.org/bom for " + SDIST in capsys.readouterr().out


def test_an_attestation_that_does_not_match_is_a_problem_naming_what_was_missing(files, monkeypatch):
    use(monkeypatch, FakeGitHub(files, verify_results=[1]))
    found = rp.verify_attestations(files / "dist", REPO, WORKFLOW, REF, SHA)
    assert len(found) == 4, "every file and predicate is reported, not only the first"
    assert all(f"from {WORKFLOW} on {REF} at {SHA[:12]}" in p and "no attestations found" in p for p in found)


def test_a_slow_attestation_is_retried_a_few_times_but_a_wrong_one_still_fails(files, monkeypatch):
    fake = use(monkeypatch, FakeGitHub(files, verify_results=[1, 1, 0]))
    assert rp.verify_attestations(files / "dist", REPO, WORKFLOW, REF, SHA) == []
    assert len(fake.calls) == 6  # the first check needed three tries, the other three passed at once
    fake = use(monkeypatch, FakeGitHub(files, verify_results=[1]))
    rp.verify_attestations(files / "dist", REPO, WORKFLOW, REF, SHA)
    assert len(fake.calls) == 4 * rp.VERIFY_TRIES


def test_the_directory_must_hold_exactly_one_wheel_and_one_sdist(files, monkeypatch):
    fake = use(monkeypatch, FakeGitHub(files))
    (files / "dist" / WHEEL).unlink()
    found = rp.verify_attestations(files / "dist", REPO, WORKFLOW, REF, SHA)
    assert len(found) == 1 and "exactly one wheel and one sdist" in found[0] and fake.calls == []
    (files / "dist" / WHEEL).write_bytes(b"w")
    (files / "dist" / "other-0.1.0-py3-none-any.whl").write_bytes(b"w")
    assert "exactly one wheel and one sdist" in rp.verify_attestations(files / "dist", REPO, WORKFLOW, REF, SHA)[0]
    assert fake.calls == []


# --- publish: draft first, public last -----------------------------------------------------------------------------


def test_the_release_is_created_as_a_draft_checked_and_only_then_made_public(files, monkeypatch, capsys):
    fake = use(monkeypatch, FakeGitHub(files))
    assert rp.publish(REPO, TAG, files) == []
    assert verbs(fake) == ["list", "create", "list", "PATCH", "get"], (
        "check for a release, draft, look, publish, re-read"
    )
    create = next(c for c in fake.calls if c[0] == "release")
    assert create[:3] == ("release", "create", TAG)
    for flag in ("--draft", "--verify-tag"):
        assert flag in create
    assert "--clobber" not in create and "--latest" not in create
    assert [Path(a).name for a in create[create.index("--notes-file") + 2 :]] == [WHEEL, SDIST, SBOM]
    assert fake.releases[0]["draft"] is False
    assert f"release {TAG} is public with" in capsys.readouterr().out


def test_an_existing_release_is_never_touched(files, monkeypatch):
    for draft, words in ((False, "a public release"), (True, "a draft")):
        fake = use(monkeypatch, FakeGitHub(files, releases=[{"id": 5, "tag_name": TAG, "draft": draft, "assets": []}]))
        found = rp.publish(REPO, TAG, files)
        assert len(found) == 1 and f"{TAG} already has {words}" in found[0] and "never replaced" in found[0]
        assert verbs(fake) == ["list"], "no create, no upload, no edit"
    other = [{"id": 5, "tag_name": "v0.0.9", "draft": False, "assets": []}]
    fake = use(monkeypatch, FakeGitHub(files, releases=other))
    assert rp.publish(REPO, TAG, files) == [] and "create" in verbs(fake)


def test_nothing_is_created_when_a_file_is_missing_or_empty(files, monkeypatch):
    fake = use(monkeypatch, FakeGitHub(files))
    (files / "sbom" / SBOM).write_text("", encoding="utf-8")
    (files / "release-notes.md").unlink()
    found = rp.publish(REPO, TAG, files)
    assert (
        len(found) == 1 and "nothing was published" in found[0] and SBOM in found[0] and "release-notes.md" in found[0]
    )
    assert fake.calls == []


def test_a_tag_for_another_version_than_the_files_publishes_nothing(files, monkeypatch):
    fake = use(monkeypatch, FakeGitHub(files))
    found = rp.publish(REPO, "v0.2.0", files)
    assert found and "nothing was published" in found[0] and "0.2.0" in found[0] and fake.calls == []


def test_a_listing_that_fails_stops_before_anything_is_created(files, monkeypatch):
    fake = use(monkeypatch, FakeGitHub(files, list_fails=True))
    assert "could not list the releases" in rp.publish(REPO, TAG, files)[0]
    assert verbs(fake) == ["list"]


def test_a_draft_that_cannot_be_created_leaves_nothing_public(files, monkeypatch):
    fake = use(monkeypatch, FakeGitHub(files, create_fails=True))
    found = rp.publish(REPO, TAG, files)
    assert len(found) == 1 and "could not create the draft release" in found[0] and "tag does not exist" in found[0]
    assert "PATCH" not in verbs(fake)


@pytest.mark.parametrize("missing", [WHEEL, SDIST, SBOM])
def test_a_draft_missing_one_of_the_three_files_is_never_published(files, monkeypatch, missing):
    fake = use(monkeypatch, FakeGitHub(files, drop=missing))
    found = rp.publish(REPO, TAG, files)
    assert any(f"asset {missing} is not on the release" in p for p in found)
    assert any("draft stays unpublished" in p for p in found)
    assert "PATCH" not in verbs(fake) and fake.releases[0]["draft"] is True


def test_a_draft_with_an_extra_file_is_never_published(files, monkeypatch):
    fake = use(monkeypatch, FakeGitHub(files))
    original = fake.create

    def create_with_stray(args):
        result = original(args)
        fake.releases[0]["assets"].append({"name": "stray.txt", "state": "uploaded"})
        return result

    fake.create = create_with_stray
    found = rp.publish(REPO, TAG, files)
    assert any("asset stray.txt is on the release but is not one of the three expected files" in p for p in found)
    assert "PATCH" not in verbs(fake)


def test_an_asset_that_is_not_fully_uploaded_is_never_published(files, monkeypatch):
    fake = use(monkeypatch, FakeGitHub(files, state="starter"))
    found = rp.publish(REPO, TAG, files)
    assert any("is in state 'starter', not 'uploaded'" in p for p in found) and "PATCH" not in verbs(fake)


def test_an_asset_whose_digest_differs_from_the_attested_file_is_never_published(files, monkeypatch):
    fake = use(monkeypatch, FakeGitHub(files, digest="wrong"))
    found = rp.publish(REPO, TAG, files)
    assert any("not the sha256 of the attested file" in p for p in found) and "PATCH" not in verbs(fake)


def test_a_github_that_reports_no_digest_does_not_block_the_release(files, monkeypatch):
    use(monkeypatch, FakeGitHub(files, digest=None))
    assert rp.publish(REPO, TAG, files) == []


def test_a_draft_that_is_slow_to_appear_in_the_listing_is_waited_for(files, monkeypatch):
    fake = use(monkeypatch, FakeGitHub(files, invisible_lists=3))
    assert rp.publish(REPO, TAG, files) == []
    assert verbs(fake).count("list") == 1 + 4


def test_a_draft_that_never_appears_publishes_nothing(files, monkeypatch):
    fake = use(monkeypatch, FakeGitHub(files, invisible_lists=99))
    found = rp.publish(REPO, TAG, files)
    assert found == [f"the draft release for {TAG} could not be found after it was created; nothing was made public"]
    assert "PATCH" not in verbs(fake)


def test_two_releases_for_the_tag_after_creating_one_publish_nothing(files, monkeypatch):
    fake = use(monkeypatch, FakeGitHub(files))
    original = fake.create

    def create_twice(args):
        result = original(args)
        fake.releases.append({"id": 78, "tag_name": TAG, "draft": True, "assets": []})
        return result

    fake.create = create_twice
    found = rp.publish(REPO, TAG, files)
    assert found and "2 releases now exist" in found[0] and "PATCH" not in verbs(fake)


def test_a_publish_request_that_fails_leaves_the_draft_unpublished(files, monkeypatch):
    use(monkeypatch, FakeGitHub(files, patch_fails=True))
    found = rp.publish(REPO, TAG, files)
    assert "could not make release" in found[0] and any("draft stays unpublished" in p for p in found)


def test_a_release_that_is_still_a_draft_afterwards_is_reported(files, monkeypatch):
    use(monkeypatch, FakeGitHub(files, patch_keeps_draft=True))
    found = rp.publish(REPO, TAG, files)
    assert any("still a draft" in p for p in found) and any("check the release page now" in p for p in found)


def test_pages_of_releases_are_read_one_after_the_other():
    pages = json.dumps([{"tag_name": "a"}]) + "\n" + json.dumps([{"tag_name": "b"}]) + json.dumps([])
    assert [p[0]["tag_name"] if p else None for p in rp.decode_json_values(pages)] == ["a", "b", None]
    assert rp.decode_json_values("  ") == []


def test_unreadable_answers_from_github_are_reported_not_raised(files, monkeypatch):
    class Garbage(FakeGitHub):
        def __call__(self, *args):
            if args[:2] == ("api", "--paginate"):
                return _Done(0, "{not json", "")
            return super().__call__(*args)

    use(monkeypatch, Garbage(files))
    assert "could not read the list of releases" in rp.publish(REPO, TAG, files)[0]
    monkeypatch.setattr(rp, "gh", lambda *a: _Done(0, "[1]", ""))
    assert rp.get_release(REPO, 1) == (None, "release 1 did not come back as an object")
    monkeypatch.setattr(rp, "gh", lambda *a: _Done(0, "nope", ""))
    assert rp.get_release(REPO, 1)[1].startswith("could not read release 1")
    monkeypatch.setattr(rp, "gh", lambda *a: _Done(1, "", "HTTP 404"))
    assert rp.get_release(REPO, 1) == (None, "could not read release 1: HTTP 404")


def test_a_release_that_cannot_be_read_back_is_reported(files, monkeypatch):
    fake = use(monkeypatch, FakeGitHub(files))
    original = fake.__call__

    def fail_reread(*args):
        if args[0] == "api" and "--paginate" not in args and "PATCH" not in args:
            return _Done(1, "", "HTTP 502")
        return original(*args)

    monkeypatch.setattr(rp, "gh", fail_reread)
    found = rp.publish(REPO, TAG, files)
    assert "could not read release 77: HTTP 502" in found[0] and "check the release page" in found[0]


# --- the command line ------------------------------------------------------------------------------------------------


def test_the_command_line_runs_both_steps_and_prints_annotations_under_actions(files, monkeypatch, capsys):
    use(monkeypatch, FakeGitHub(files))
    args = ["verify-attestations", "--dir", str(files / "dist"), "--repo", REPO, "--workflow", WORKFLOW]
    assert rp.main([*args, "--source-ref", REF, "--source-digest", SHA]) == 0
    assert rp.main(["publish", "--repo", REPO, "--tag", TAG, "--dir", str(files)]) == 0
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert rp.main(["publish", "--repo", REPO, "--tag", TAG, "--dir", str(files)]) == 1
    assert f"::error::{TAG} already has a public release" in capsys.readouterr().out
    monkeypatch.delenv("GITHUB_ACTIONS")
    assert rp.main(["publish", "--repo", REPO, "--tag", TAG, "--dir", str(files)]) == 1
    assert f"error: {TAG} already has a public release" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        rp.main(["verify-attestations", "--dir", str(files / "dist"), "--repo", REPO])  # strict flags are required


def test_the_real_gh_wrapper_runs_gh_without_a_shell(monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"], seen["kwargs"] = command, kwargs
        return _Done(0, "ok", "")

    monkeypatch.setattr(rp.subprocess, "run", fake_run)
    assert rp.gh("release", "view").stdout == "ok"
    assert seen["command"] == ["gh", "release", "view"] and not seen["kwargs"].get("shell")
    slept = []
    monkeypatch.setattr(rp.time, "sleep", slept.append)
    REAL_SLEEP(2.5)
    assert slept == [2.5]
