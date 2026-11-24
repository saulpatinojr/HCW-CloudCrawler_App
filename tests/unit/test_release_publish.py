"""scripts/release-publish.py: the steps that verify the attestations and turn a draft into a public release.

A v* tag cannot be moved or deleted, so a release that goes public with the wrong files, or goes public before
everything has been checked, is permanent. `gh` is replaced by a small fake of the parts of GitHub these steps use, so
every path is exercised without a network."""

from __future__ import annotations

import base64
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
PROV = "cloud_crawler_core-0.1.0.intoto.jsonl"


def _load():
    spec = importlib.util.spec_from_file_location("release_publish", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rp = _load()
REAL_SLEEP = rp.sleep


def bundle(*contents: bytes, predicate: str = "https://slsa.dev/provenance/v1") -> dict:
    """A Sigstore bundle as `actions/attest` writes it, reduced to the parts the script reads: the signed statement."""
    subjects = [
        {"name": f"file{n}", "digest": {"sha256": hashlib.sha256(c).hexdigest()}} for n, c in enumerate(contents)
    ]
    statement = {"_type": "https://in-toto.io/Statement/v1", "subject": subjects, "predicateType": predicate}
    payload = base64.b64encode(json.dumps(statement).encode()).decode()
    return {
        "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
        "verificationMaterial": {"certificate": {"rawBytes": "AA=="}},
        "dsseEnvelope": {"payload": payload, "payloadType": "application/vnd.in-toto+json", "signatures": []},
    }


def make_files(root: Path) -> Path:
    """The downloaded `release-files` artifact, with the provenance artifact beside it as the release job has it."""
    (root / "dist").mkdir(parents=True)
    (root / "sbom").mkdir()
    (root / "provenance").mkdir()
    (root / "dist" / WHEEL).write_bytes(b"wheel bytes")
    (root / "dist" / SDIST).write_bytes(b"sdist bytes")
    (root / "sbom" / SBOM).write_text("{}", encoding="utf-8")
    (root / "provenance" / PROV).write_text(json.dumps(bundle(b"wheel bytes", b"sdist bytes")) + "\n", encoding="utf-8")
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
        self.listing_stale = options.pop("listing_stale", False)  # the listing shows drafts without their files
        self.open_reads = options.pop("open_reads", 0)  # reads by id that show every file in state `open`
        self.reread_fails = options.pop("reread_fails", 0)  # reads of the draft by id that fail
        self.patch_error = options.pop("patch_error", None)  # for example "HTTP 404: Not Found"
        self.verify_results = options.pop("verify_results", [0])  # return codes of the attestation checks, in turn
        self.bundle_result = options.pop("bundle_result", 0)  # return code of a check against the provenance file
        assert not options, options

    def __call__(self, *args: str):
        self.calls.append(args)
        if args[:2] == ("attestation", "verify") and "--bundle" in args:
            return _Done(self.bundle_result, "", "verifying with issuer failed" if self.bundle_result else "")
        if args[:2] == ("attestation", "verify"):
            code = self.verify_results.pop(0) if len(self.verify_results) > 1 else self.verify_results[0]
            return _Done(code, "", "HTTP 404: no attestations found" if code else "")
        if args[:2] == ("api", "--paginate"):
            if self.list_fails:
                return _Done(1, "", "HTTP 500")
            if self.invisible_lists > 0 and any(c[:2] == ("release", "create") for c in self.calls):
                self.invisible_lists -= 1
                return _Done(0, "[]", "")
            listed = [dict(r, assets=[]) if self.listing_stale and r.get("draft") else r for r in self.releases]
            return _Done(0, "".join(json.dumps([release]) for release in listed) or "[]", "")
        if args[:2] == ("release", "create"):
            return self.create(args)
        if args[:3] == ("api", "--method", "PATCH"):
            return self.patch(args)
        if args[0] == "api" and "/releases/" in args[1]:
            release = next(r for r in self.releases if r["id"] == int(args[1].rsplit("/", 1)[1]))
            if release["draft"] and self.reread_fails > 0:
                self.reread_fails -= 1
                return _Done(1, "", "HTTP 502")
            if release["draft"] and self.open_reads > 0:
                self.open_reads -= 1
                release = dict(release, assets=[dict(a, state="open") for a in release["assets"]])
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
        if self.patch_error:
            return _Done(1, "", self.patch_error)
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
    # the same output whether the tests run on a laptop or under Actions; a test that needs them sets them itself
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)


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


def test_a_slow_attestation_is_waited_for_with_growing_pauses(files, monkeypatch):
    pauses: list[float] = []
    monkeypatch.setattr(rp, "sleep", pauses.append)
    fake = use(monkeypatch, FakeGitHub(files, verify_results=[1, 1, 0]))
    assert rp.verify_attestations(files / "dist", REPO, WORKFLOW, REF, SHA) == []
    assert pauses == [5.0, 10.0]
    assert len(fake.calls) == 6  # the first check needed three tries, the other three passed at once


def test_the_attestation_wait_is_a_few_minutes_with_backoff_and_one_budget_for_the_whole_step(files, monkeypatch):
    pauses: list[float] = []
    monkeypatch.setattr(rp, "sleep", pauses.append)
    assert list(rp.VERIFY_DELAYS) == sorted(rp.VERIFY_DELAYS), "the pauses grow"
    assert 180 <= rp.VERIFY_BUDGET_SECONDS <= 300, "a few minutes"
    fake = use(monkeypatch, FakeGitHub(files, verify_results=[1]))
    found = rp.verify_attestations(files / "dist", REPO, WORKFLOW, REF, SHA)
    assert len(found) == 4, "a wrong attestation still fails, for every file and predicate"
    assert sum(pauses) == rp.VERIFY_BUDGET_SECONDS, "all four checks together wait no longer than the budget"
    assert len(fake.calls) == (1 + len(rp.VERIFY_DELAYS)) + 3, "once the budget is spent each check tries once"


# --- the provenance file ---------------------------------------------------------------------------------------------


def test_the_provenance_file_is_the_attest_bundle_as_json_lines_named_for_the_version(files, tmp_path, capsys):
    source = tmp_path / "attestation.json"
    one = bundle(b"wheel bytes", b"sdist bytes")
    source.write_text(json.dumps(one, indent=2), encoding="utf-8")  # pretty-printed: still one line when written
    out = tmp_path / "out" / "provenance"
    assert rp.write_provenance(source, files / "dist", out) == []
    assert [p.name for p in out.iterdir()] == [PROV] and PROV.endswith(".intoto.jsonl")
    text = (out / PROV).read_text(encoding="utf-8")
    assert text.endswith("\n") and [json.loads(line) for line in text.splitlines()] == [one]
    assert f"1 provenance bundle(s) naming {WHEEL}, {SDIST}" in capsys.readouterr().out


def test_several_bundles_become_one_line_each(files, tmp_path):
    source = tmp_path / "attestation.json"
    both = [bundle(b"wheel bytes"), bundle(b"sdist bytes")]
    source.write_text("".join(json.dumps(b, indent=1) + "\n" for b in both), encoding="utf-8")
    assert rp.write_provenance(source, files / "dist", tmp_path / "out") == []
    lines = (tmp_path / "out" / PROV).read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == both, "valid JSON lines: one bundle per line, nothing else"


@pytest.mark.parametrize(
    ("content", "words"),
    [
        ("", "the provenance is empty"),
        ("<html>not found</html>", "the provenance is not JSON"),
        (json.dumps({"hello": "world"}), "is not a Sigstore bundle with a signed statement"),
        (json.dumps([bundle(b"wheel bytes", b"sdist bytes")]), "is not a Sigstore bundle with a signed statement"),
        (json.dumps({"dsseEnvelope": {"payload": "not base64!"}}), "cannot be read"),
        (
            json.dumps(bundle(b"wheel bytes", b"sdist bytes", predicate="https://cyclonedx.org/bom")),
            "is a 'https://cyclonedx.org/bom' statement, expected https://slsa.dev/provenance/v1",
        ),
        (json.dumps(bundle(b"wheel bytes")), f"the provenance does not name {SDIST} by its sha256"),
        (json.dumps(bundle(b"other", b"files")), f"the provenance does not name {WHEEL}, {SDIST} by its sha256"),
    ],
)
def test_a_bundle_that_is_not_the_provenance_of_these_files_is_never_written(files, tmp_path, content, words):
    source = tmp_path / "attestation.json"
    source.write_text(content, encoding="utf-8")
    found = rp.write_provenance(source, files / "dist", tmp_path / "out")
    assert len(found) == 1 and words in found[0]
    assert not (tmp_path / "out").exists(), "no file is left behind to be attached by mistake"


def test_no_bundle_no_dist_files_or_an_existing_file_writes_nothing(files, tmp_path):
    assert "left no bundle" in rp.write_provenance(tmp_path / "absent.json", files / "dist", tmp_path / "out")[0]
    assert "exactly one wheel and one sdist" in rp.write_provenance(tmp_path / "absent.json", tmp_path, tmp_path)[0]
    source = tmp_path / "attestation.json"
    source.write_text(json.dumps(bundle(b"wheel bytes", b"sdist bytes")), encoding="utf-8")
    before = (files / "provenance" / PROV).read_bytes()
    found = rp.write_provenance(source, files / "dist", files / "provenance")
    assert "never replaced" in found[0] and (files / "provenance" / PROV).read_bytes() == before


def test_the_provenance_file_is_verified_from_the_file_alone_with_the_same_strict_flags(files, monkeypatch, capsys):
    fake = use(monkeypatch, FakeGitHub(files))
    assert rp.verify_attestations(files / "dist", REPO, WORKFLOW, REF, SHA, files / "provenance") == []
    offline = [c for c in fake.calls if "--bundle" in c]
    assert len(offline) == 2 and len(fake.calls) == 6, "the two files against the file, then the four store checks"
    assert fake.calls[:2] == offline, "the file is checked first"
    assert {Path(c[2]).name for c in offline} == {WHEEL, SDIST}
    for call in offline:
        assert call[call.index("--bundle") + 1] == str(files / "provenance" / PROV)
        assert call[call.index("--predicate-type") + 1] == rp.PROVENANCE
        assert call[call.index("--repo") + 1] == REPO
        assert call[call.index("--signer-workflow") + 1] == f"{REPO}/{WORKFLOW}"
        assert call[call.index("--source-ref") + 1] == REF and call[call.index("--source-digest") + 1] == SHA
    assert f"verified {WHEEL} against the file {PROV}" in capsys.readouterr().out


def test_a_provenance_file_that_does_not_verify_is_a_problem_and_is_not_waited_for(files, monkeypatch):
    pauses: list[float] = []
    monkeypatch.setattr(rp, "sleep", pauses.append)
    fake = use(monkeypatch, FakeGitHub(files, bundle_result=1))
    found = rp.verify_attestations(files / "dist", REPO, WORKFLOW, REF, SHA, files / "provenance")
    assert len(found) == 2 and all(
        f"{PROV} does not verify" in p and "verifying with issuer failed" in p for p in found
    )
    assert pauses == [] and len(fake.calls) == 2, "the proof is on disk: nothing to wait for, and nothing else is tried"


def _rename(files: Path) -> None:
    (files / "provenance" / PROV).rename(files / "provenance" / "cloud-crawler-core.intoto.jsonl")


def _add_stray(files: Path) -> None:
    (files / "provenance" / "extra.intoto.jsonl").write_text("{}", encoding="utf-8")


def _sbom_bundle(files: Path) -> None:
    wrong = bundle(b"wheel bytes", b"sdist bytes", predicate="https://cyclonedx.org/bom")
    (files / "provenance" / PROV).write_text(json.dumps(wrong), encoding="utf-8")


def _other_files(files: Path) -> None:
    (files / "provenance" / PROV).write_text(json.dumps(bundle(b"an earlier wheel", b"sdist bytes")), encoding="utf-8")


PROVENANCE_REFUSALS = [
    (lambda files: (files / "provenance" / PROV).unlink(), f"must hold exactly {PROV}"),
    (lambda files: __import__("shutil").rmtree(files / "provenance"), f"must hold exactly {PROV}"),
    (_rename, "found ['cloud-crawler-core.intoto.jsonl']"),
    (_add_stray, "found ['cloud_crawler_core-0.1.0.intoto.jsonl', 'extra.intoto.jsonl']"),
    (_sbom_bundle, "is a 'https://cyclonedx.org/bom' statement"),
    (_other_files, f"the provenance does not name {WHEEL} by its sha256"),
]


@pytest.mark.parametrize(("spoil", "words"), PROVENANCE_REFUSALS)
def test_a_missing_misnamed_extra_or_wrong_provenance_file_fails_the_verification(files, monkeypatch, spoil, words):
    fake = use(monkeypatch, FakeGitHub(files))
    spoil(files)
    found = rp.verify_attestations(files / "dist", REPO, WORKFLOW, REF, SHA, files / "provenance")
    assert len(found) == 1 and words in found[0]
    assert fake.calls == [], "gh is not asked about a file that is not the provenance file"


@pytest.mark.parametrize(("spoil", "words"), PROVENANCE_REFUSALS)
def test_a_missing_misnamed_extra_or_wrong_provenance_file_publishes_nothing(files, monkeypatch, spoil, words):
    fake = use(monkeypatch, FakeGitHub(files))
    spoil(files)
    found = rp.publish(REPO, TAG, files)
    assert found and all("nothing was published" in p for p in found)
    assert any(words in p or PROV in p for p in found)
    assert fake.calls == [], "no listing, no draft: the release needs all four files before anything is created"


def test_a_provenance_file_for_another_version_than_the_tag_publishes_nothing(files, monkeypatch):
    fake = use(monkeypatch, FakeGitHub(files))
    (files / "provenance" / PROV).rename(files / "provenance" / "cloud_crawler_core-0.0.9.intoto.jsonl")
    found = rp.publish(REPO, TAG, files)
    assert len(found) == 1 and "missing or empty, nothing was published" in found[0] and PROV in found[0]
    assert fake.calls == []


# --- publish: draft first, public last -----------------------------------------------------------------------------


def test_the_release_is_created_as_a_draft_checked_and_only_then_made_public(files, monkeypatch, capsys):
    fake = use(monkeypatch, FakeGitHub(files))
    assert rp.publish(REPO, TAG, files) == []
    assert verbs(fake) == ["list", "create", "list", "get", "PATCH", "get"], (
        "check for a release, draft, look, re-read the draft by id, publish, re-read"
    )
    by_id = [c for c in fake.calls if c[0] == "api" and c[1].startswith("repos/")]
    assert [c[1] for c in by_id] == [f"repos/{REPO}/releases/77"] * 2
    create = next(c for c in fake.calls if c[0] == "release")
    assert create[:3] == ("release", "create", TAG)
    for flag in ("--draft", "--verify-tag"):
        assert flag in create
    assert "--clobber" not in create and "--latest" not in create
    assert [Path(a).name for a in create[create.index("--notes-file") + 2 :]] == [WHEEL, SDIST, SBOM, PROV]
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
    assert "could not create the draft release" in found[0] and "tag does not exist" in found[0]
    assert "nothing was made public" in found[1] and "A draft may be left behind" in found[1]
    assert "PATCH" not in verbs(fake)


@pytest.mark.parametrize("missing", [WHEEL, SDIST, SBOM, PROV])
def test_a_draft_missing_one_of_the_four_files_is_never_published(files, monkeypatch, missing):
    fake = use(monkeypatch, FakeGitHub(files, drop=missing))
    found = rp.publish(REPO, TAG, files)
    assert any(f"asset {missing} is not on the release" in p for p in found)
    assert any("nothing was made public" in p and f"https://github.com/{REPO}/releases" in p for p in found)
    assert "PATCH" not in verbs(fake) and fake.releases[0]["draft"] is True
    assert verbs(fake).count("get") == rp.SETTLE_TRIES, "bounded: it waited, then gave up"
    assert f"after {rp.SETTLE_TRIES} reads of the draft" in found[0]


def test_a_draft_with_an_extra_file_is_never_published(files, monkeypatch):
    fake = use(monkeypatch, FakeGitHub(files))
    original = fake.create

    def create_with_stray(args):
        result = original(args)
        fake.releases[0]["assets"].append({"name": "stray.txt", "state": "uploaded"})
        return result

    fake.create = create_with_stray
    found = rp.publish(REPO, TAG, files)
    assert any("asset stray.txt is on the release but is not one of the four expected files" in p for p in found)
    assert "PATCH" not in verbs(fake)


def test_an_asset_that_stays_open_is_never_published(files, monkeypatch):
    fake = use(monkeypatch, FakeGitHub(files, state="open"))  # GitHub's real states are `uploaded` and `open`
    found = rp.publish(REPO, TAG, files)
    assert any("is in state 'open', not 'uploaded'" in p for p in found) and "PATCH" not in verbs(fake)
    assert verbs(fake).count("get") == rp.SETTLE_TRIES


def test_a_listed_draft_with_stale_or_missing_files_is_not_trusted_the_draft_is_re_read_by_id(files, monkeypatch):
    fake = use(monkeypatch, FakeGitHub(files, listing_stale=True))
    assert rp.publish(REPO, TAG, files) == []
    assert verbs(fake).count("get") == 2, "one read of the draft before publishing, one of the release afterwards"


def test_files_that_are_still_open_when_the_draft_first_appears_are_waited_for(files, monkeypatch):
    pauses: list[float] = []
    monkeypatch.setattr(rp, "sleep", pauses.append)
    fake = use(monkeypatch, FakeGitHub(files, listing_stale=True, open_reads=3))
    assert rp.publish(REPO, TAG, files) == []
    assert verbs(fake).count("get") == 3 + 1 + 1, "three reads still open, one settled, one after publishing"
    assert pauses.count(rp.SETTLE_PAUSE_SECONDS) == 3


def test_a_draft_that_cannot_be_read_by_id_for_a_moment_is_retried(files, monkeypatch):
    fake = use(monkeypatch, FakeGitHub(files, reread_fails=2))
    assert rp.publish(REPO, TAG, files) == []
    assert verbs(fake).count("get") == 2 + 1 + 1


def test_a_draft_that_can_never_be_read_by_id_publishes_nothing(files, monkeypatch):
    fake = use(monkeypatch, FakeGitHub(files, reread_fails=999))
    found = rp.publish(REPO, TAG, files)
    assert f"after {rp.SETTLE_TRIES} reads of the draft: could not read release 77: HTTP 502" in found[0]
    assert "PATCH" not in verbs(fake) and verbs(fake).count("get") == rp.SETTLE_TRIES


def test_a_problem_that_time_cannot_fix_ends_the_wait_at_once(files, monkeypatch):
    fake = use(monkeypatch, FakeGitHub(files, digest="wrong"))
    found = rp.publish(REPO, TAG, files)
    assert verbs(fake).count("get") == 1 and "PATCH" not in verbs(fake)
    assert any("not the sha256 of the attested file" in p for p in found)


def test_an_asset_whose_digest_differs_from_the_attested_file_is_never_published(files, monkeypatch):
    fake = use(monkeypatch, FakeGitHub(files, digest="wrong"))
    found = rp.publish(REPO, TAG, files)
    assert any("not the sha256 of the attested file" in p for p in found) and "PATCH" not in verbs(fake)


def test_a_github_that_reports_no_digest_does_not_block_the_release_but_says_so(files, monkeypatch, capsys):
    use(monkeypatch, FakeGitHub(files, digest=None))
    assert rp.publish(REPO, TAG, files) == []
    out = capsys.readouterr().out
    assert "notice: GitHub reports no sha256 for " in out
    for name in (WHEEL, SDIST, SBOM, PROV):
        assert name in out
    assert "integrity rests on the sha256 list checked in this job and on the attestations" in out


def test_no_notice_is_printed_when_github_reports_the_digests(files, monkeypatch, capsys):
    use(monkeypatch, FakeGitHub(files))
    assert rp.publish(REPO, TAG, files) == []
    assert "no sha256" not in capsys.readouterr().out


def test_the_missing_digest_notice_is_an_annotation_under_actions(files, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    use(monkeypatch, FakeGitHub(files, digest=None))
    rp.publish(REPO, TAG, files)
    assert "::notice::GitHub reports no sha256" in capsys.readouterr().out


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


@pytest.mark.parametrize("error", ["HTTP 403: Resource not accessible by integration", "HTTP 404: Not Found"])
def test_a_publish_request_refused_with_403_or_404_leaves_the_draft_with_clear_instructions(files, monkeypatch, error):
    fake = use(monkeypatch, FakeGitHub(files, patch_error=error))
    found = rp.publish(REPO, TAG, files)
    assert f"could not make release {TAG} public: {error}" == found[0]
    assert any("nothing was made public" in p and f"https://github.com/{REPO}/releases" in p for p in found)
    assert any("the tag stays" in p for p in found)
    assert rp.WORKFLOWS_NOTE in found, "the likely cause is named: a token cannot modify a release touching workflows"
    assert fake.releases[0]["draft"] is True, "the draft is left as it is, unpublished"


def test_a_publish_request_that_fails_for_another_reason_still_says_nothing_is_public(files, monkeypatch):
    use(monkeypatch, FakeGitHub(files, patch_error="HTTP 500: server error"))
    found = rp.publish(REPO, TAG, files)
    assert "could not make release" in found[0] and any("nothing was made public" in p for p in found)
    assert rp.WORKFLOWS_NOTE not in found


def test_a_draft_that_cannot_be_created_because_of_workflow_permission_says_why(files, monkeypatch):
    class Refused(FakeGitHub):
        def create(self, args):
            return _Done(
                1,
                "",
                "HTTP 403: refusing to allow a GitHub App to create or update workflow without workflows permission",
            )

    use(monkeypatch, Refused(files))
    found = rp.publish(REPO, TAG, files)
    assert "could not create the draft release" in found[0] and rp.WORKFLOWS_NOTE in found
    assert any("nothing was made public" in p for p in found)


def test_a_failed_step_is_also_written_to_the_job_summary(tmp_path, monkeypatch, capsys):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    rp.report(["one thing", "another"])
    assert summary.read_text(encoding="utf-8") == "### The release step stopped\n\n- one thing\n- another\n\n"
    rp.report([])  # nothing to say, nothing written
    assert summary.read_text(encoding="utf-8").count("The release step stopped") == 1
    capsys.readouterr()


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
        published = any(c[:3] == ("api", "--method", "PATCH") for c in fake.calls)
        if published and args[0] == "api" and "--paginate" not in args and "PATCH" not in args:
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
    assert (
        rp.main([*args, "--source-ref", REF, "--source-digest", SHA, "--provenance-dir", str(files / "provenance")])
        == 0
    )
    source = files / "attestation.json"
    source.write_text(json.dumps(bundle(b"wheel bytes", b"sdist bytes")), encoding="utf-8")
    write = ["write-provenance", "--bundle", str(source), "--dir", str(files / "dist")]
    assert rp.main([*write, "--out-dir", str(files / "fresh")]) == 0 and (files / "fresh" / PROV).is_file()
    assert rp.main([*write, "--out-dir", str(files / "fresh")]) == 1, "a provenance file is never replaced"
    capsys.readouterr()
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
    assert seen["kwargs"]["timeout"] == rp.GH_TIMEOUT_SECONDS, "a hung gh must not hold the job"

    def hang(command, **kwargs):
        raise rp.subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(rp.subprocess, "run", hang)
    cut_off = rp.gh("release", "create")
    assert cut_off.returncode == 124 and "did not answer within" in cut_off.stderr
    slept = []
    monkeypatch.setattr(rp.time, "sleep", slept.append)
    REAL_SLEEP(2.5)
    assert slept == [2.5]
