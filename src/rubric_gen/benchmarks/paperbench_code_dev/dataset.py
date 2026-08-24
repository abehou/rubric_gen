"""Load pinned PaperBench paper sets into the local Code-Dev task format."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterator

import yaml


PAPERBENCH_REPOSITORY = "openai/frontier-evals"
PAPERBENCH_REVISION = "51052cede8cc608f95bb00346635e03759013e5a"
PAPERBENCH_DEV_PAPERS = (
    "semantic-self-consistency",
    "self-expansion",
    "self-composing-policies",
)
PAPERBENCH_RESULTS_PAPERS = (
    "fre",
    "mechanistic-understanding",
    "bridging-data-gaps",
    "test-time-model-adaptation",
    "all-in-one",
    "sequential-neural-score-estimation",
    "robust-clip",
    "what-will-my-model-forget",
    "pinn",
    "stay-on-topic-with-classifier-free-guidance",
    "rice",
    "sample-specific-masks",
    "adaptive-pruning",
    "sapg",
    "lca-on-the-line",
    "stochastic-interpolants",
    "bbox",
    "lbcs",
    "bam",
    "ftrl",
)
PAPERBENCH_PAPER_SETS = {
    "dev": PAPERBENCH_DEV_PAPERS,
    "all": PAPERBENCH_RESULTS_PAPERS,
}
PAPERBENCH_SCORING_PROTOCOL = "paperbench-code-dev"
_UPSTREAM_BASE = "project/paperbench/data/papers"
_LFS_PREFIX = b"version https://git-lfs.github.com/spec/v1\n"
_ROOT_FILES = (
    "config.yaml",
    "paper.md",
    "addendum.md",
    "blacklist.txt",
    "rubric.json",
)


def paperbench_papers(source_split: str) -> tuple[str, ...]:
    """Return one exact pinned PaperBench paper set."""

    if type(source_split) is not str:
        raise ValueError("PaperBench source split must be dev or all")
    try:
        return PAPERBENCH_PAPER_SETS[source_split]
    except KeyError as exc:
        raise ValueError("PaperBench source split must be dev or all") from exc


def prepare_paperbench_code_dataset(
    source_root: Path,
    output_root: Path,
    *,
    source_split: str,
    revision: str = PAPERBENCH_REVISION,
) -> Path:
    """Convert one hydrated upstream PaperBench tree into local task inputs."""

    paper_ids = paperbench_papers(source_split)
    source = source_root.resolve()
    destination = output_root.expanduser().absolute()
    if os.path.lexists(destination):
        raise FileExistsError(f"PaperBench output already exists: {destination}")
    papers_root = source / "data" / "papers"
    if not papers_root.is_dir():
        raise ValueError(f"PaperBench source has no data/papers directory: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(
        prefix=f".{destination.name}.loading-",
        dir=destination.parent,
    ))
    try:
        records = [
            _prepare_paper(
                papers_root / paper_id,
                staging / paper_id,
                paper_id=paper_id,
                source_split=source_split,
                revision=revision,
            )
            for paper_id in paper_ids
        ]
        _write_json(staging / "manifest.json", {
            "kind": "rubric-gen-paperbench-code-dev-dataset",
            "source_repository": PAPERBENCH_REPOSITORY,
            "source_revision": revision,
            "source_split": source_split,
            "code_only": True,
            "paper_ids": list(paper_ids),
            "papers": records,
        })
        os.replace(staging, destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination


def download_paperbench_code_dataset(
    output_root: Path,
    *,
    source_split: str,
    revision: str = PAPERBENCH_REVISION,
) -> Path:
    """Download one pinned upstream paper set and convert it into tasks."""

    paper_ids = paperbench_papers(source_split)
    with tempfile.TemporaryDirectory(prefix="paperbench-code-source-") as raw:
        source = Path(raw)
        for paper_id in paper_ids:
            paper = source / "data" / "papers" / paper_id
            paper.mkdir(parents=True)
            for name in _ROOT_FILES:
                _download_media_file(
                    f"{_UPSTREAM_BASE}/{paper_id}/{name}",
                    paper / name,
                    revision=revision,
                )
            try:
                _download_media_file(
                    f"{_UPSTREAM_BASE}/{paper_id}/judge.addendum.md",
                    paper / "judge.addendum.md",
                    revision=revision,
                )
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    raise
            for asset in _github_directory_files(
                f"{_UPSTREAM_BASE}/{paper_id}/assets",
                revision=revision,
            ):
                _download_media_file(
                    f"{_UPSTREAM_BASE}/{paper_id}/assets/{asset}",
                    paper / "assets" / asset,
                    revision=revision,
                )
        return prepare_paperbench_code_dataset(
            source,
            output_root,
            source_split=source_split,
            revision=revision,
        )


def validate_paperbench_code_dataset(
    root: Path,
    *,
    source_split: str,
) -> None:
    """Validate one prepared dataset against an exact pinned paper set."""

    paper_ids = paperbench_papers(source_split)
    dataset = root.expanduser().absolute()
    if dataset.is_symlink() or not dataset.is_dir():
        raise ValueError(f"PaperBench dataset is missing or symlinked: {dataset}")
    manifest = _read_json_mapping(dataset / "manifest.json")
    expected_keys = {
        "kind", "source_repository", "source_revision",
        "source_split", "code_only", "paper_ids", "papers",
    }
    if set(manifest) != expected_keys:
        raise ValueError("PaperBench dataset manifest has unexpected keys")
    if (
        manifest["kind"] != "rubric-gen-paperbench-code-dev-dataset"
        or manifest["source_repository"] != PAPERBENCH_REPOSITORY
        or manifest["source_revision"] != PAPERBENCH_REVISION
        or manifest["source_split"] != source_split
        or manifest["code_only"] is not True
        or manifest["paper_ids"] != list(paper_ids)
    ):
        raise ValueError(
            "PaperBench dataset manifest differs from the pinned source split"
        )
    records = manifest["papers"]
    if type(records) is not list or len(records) != len(paper_ids):
        raise ValueError("PaperBench dataset manifest has invalid paper records")
    by_id = {
        record.get("paper_id"): record
        for record in records
        if type(record) is dict and type(record.get("paper_id")) is str
    }
    if set(by_id) != set(paper_ids):
        raise ValueError(
            "PaperBench dataset paper records do not match the source split"
        )
    for paper_id in paper_ids:
        task = dataset / paper_id
        metadata_path = task / "tests" / "paperbench.json"
        metadata = _read_json_mapping(metadata_path)
        if metadata != by_id[paper_id]:
            raise ValueError(f"PaperBench task metadata differs from manifest: {paper_id}")
        required_metadata = {
            "kind", "paper_id", "title",
            "source_repository", "source_revision", "source_split",
            "source_config_id", "code_only",
            "code_development_leaf_count", "scoring_protocol",
            "score_normalization_maximum", "paper_sha256",
            "source_rubric_sha256", "rendered_rubric_sha256",
        }
        if set(metadata) != required_metadata or (
            metadata["kind"] != "rubric-gen-paperbench-code-dev-task"
            or metadata["paper_id"] != paper_id
            or metadata["source_repository"] != PAPERBENCH_REPOSITORY
            or metadata["source_revision"] != PAPERBENCH_REVISION
            or metadata["source_split"] != source_split
            or type(metadata["source_config_id"]) is not str
            or not metadata["source_config_id"]
            or metadata["code_only"] is not True
            or metadata["scoring_protocol"] != PAPERBENCH_SCORING_PROTOCOL
        ):
            raise ValueError(f"PaperBench task metadata is invalid: {paper_id}")
        instruction = task / "instruction.md"
        data = task / "environment" / "data"
        paper = data / "paper.md"
        addendum = data / "addendum.md"
        blacklist = data / "blacklist.txt"
        source_rubric = task / "tests" / "paperbench.source.json"
        rendered_rubric = task / "tests" / "rubric.txt"
        for path in (
            instruction, data, paper, addendum, blacklist, source_rubric,
            rendered_rubric,
        ):
            if path.is_symlink() or not path.exists():
                raise ValueError(f"PaperBench task input is missing or symlinked: {path}")
        source_raw = source_rubric.read_bytes()
        try:
            source_value = json.loads(source_raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"PaperBench source rubric is invalid: {paper_id}") from exc
        rendered, leaf_count, normalization_maximum = render_code_dev_rubric(
            source_value
        )
        if rendered_rubric.read_text(encoding="utf-8") != rendered:
            raise ValueError(f"PaperBench rendered rubric is not reproducible: {paper_id}")
        expected_values = {
            "code_development_leaf_count": leaf_count,
            "score_normalization_maximum": normalization_maximum,
            "paper_sha256": hashlib.sha256(paper.read_bytes()).hexdigest(),
            "source_rubric_sha256": hashlib.sha256(source_raw).hexdigest(),
            "rendered_rubric_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
        }
        for key, expected in expected_values.items():
            if metadata[key] != expected:
                raise ValueError(
                    f"PaperBench task metadata {key} is invalid: {paper_id}"
                )


def render_code_dev_rubric(value: object) -> tuple[str, int, int]:
    """Render the official binary Code-Dev score as exact integer weights."""

    root = _task_node(value, context="root")
    pruned = _prune_code_development(root)
    if pruned is None:
        raise ValueError("PaperBench rubric has no Code Development leaves")
    weighted = list(_effective_leaves(pruned, Fraction(1), ()))
    points, normalization_maximum = _exact_integer_points(
        [weight for _, weight, _ in weighted]
    )
    titles = _criterion_titles(weighted)
    sections = [
        "PaperBench Code-Dev rubric. Judge actual source-code implementation, "
        "not plans, prose claims, or unimplemented documentation.",
        f"Scoring protocol: {PAPERBENCH_SCORING_PROTOCOL}",
        f"Score normalization maximum: {normalization_maximum}",
    ]
    for index, ((node, _, _), title, maximum) in enumerate(
        zip(weighted, titles, points, strict=True),
        start=1,
    ):
        if maximum < 1:
            raise ValueError("PaperBench effective criterion weight is zero")
        sections.append(
            f"Criterion {index}: {title}\n"
            f"PaperBench leaf ID: {node['id']}\n"
            f"Levels: A={maximum} B=0\n"
            "[A]: The submitted code correctly implements the requirement.\n"
            "[B]: The implementation is missing, incorrect, merely described, or not usable."
        )
    return (
        "\n\n".join(sections) + "\n",
        len(weighted),
        normalization_maximum,
    )


def _prepare_paper(
    source: Path,
    destination: Path,
    *,
    paper_id: str,
    source_split: str,
    revision: str,
) -> dict[str, object]:
    if source.is_symlink() or not source.is_dir():
        raise ValueError(f"PaperBench paper directory is invalid: {source}")
    config = _yaml_mapping(_read_hydrated(source / "config.yaml"))
    source_config_id = config.get("id")
    if type(source_config_id) is not str or not source_config_id:
        raise ValueError(f"PaperBench config has no ID: {source}")
    title = config.get("title")
    if type(title) is not str or not title.strip():
        raise ValueError(f"PaperBench paper has no title: {source}")
    paper = _read_hydrated(source / "paper.md")
    addendum = _read_hydrated(source / "addendum.md")
    blacklist = _read_hydrated(source / "blacklist.txt")
    rubric_raw = _read_hydrated(source / "rubric.json")
    try:
        rubric_value = json.loads(rubric_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"PaperBench rubric is invalid JSON: {source}") from exc
    rendered, leaf_count, normalization_maximum = render_code_dev_rubric(
        rubric_value
    )

    data = destination / "environment" / "data"
    tests = destination / "tests"
    data.mkdir(parents=True)
    tests.mkdir()
    (destination / "instruction.md").write_text(
        _instruction(paper_id, title),
        encoding="utf-8",
    )
    (data / "paper.md").write_bytes(paper)
    (data / "addendum.md").write_bytes(addendum)
    (data / "blacklist.txt").write_bytes(blacklist)
    assets = source / "assets"
    if assets.is_symlink():
        raise ValueError(f"PaperBench assets directory is a symlink: {assets}")
    if assets.is_dir():
        _copy_regular_tree(assets, data / "assets")
    (tests / "rubric.txt").write_text(rendered, encoding="utf-8")
    (tests / "paperbench.source.json").write_bytes(rubric_raw)
    judge_addendum = source / "judge.addendum.md"
    if judge_addendum.is_symlink():
        raise ValueError(f"PaperBench judge addendum is a symlink: {judge_addendum}")
    if judge_addendum.is_file():
        (tests / "judge.addendum.md").write_bytes(_read_hydrated(judge_addendum))
    metadata = {
        "kind": "rubric-gen-paperbench-code-dev-task",
        "paper_id": paper_id,
        "title": title,
        "source_repository": PAPERBENCH_REPOSITORY,
        "source_revision": revision,
        "source_split": source_split,
        "source_config_id": source_config_id,
        "code_only": True,
        "code_development_leaf_count": leaf_count,
        "scoring_protocol": PAPERBENCH_SCORING_PROTOCOL,
        "score_normalization_maximum": normalization_maximum,
        "paper_sha256": hashlib.sha256(paper).hexdigest(),
        "source_rubric_sha256": hashlib.sha256(rubric_raw).hexdigest(),
        "rendered_rubric_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
    }
    _write_json(tests / "paperbench.json", metadata)
    return metadata


def _instruction(paper_id: str, title: str) -> str:
    return f"""# PaperBench Code-Dev: {title}

Replicate as many core contributions of `{paper_id}` as possible. Read the
source paper at `./data/paper.md` and the author guidance at
`./data/addendum.md`. Supporting assets, if any, are under `./data/assets`.

Write the replication codebase under `./submission`. Include a README that maps
the implementation to the paper and explains how to use it. The grader checks
the source code only. It does not run a reproduction stage. Documentation by
itself does not satisfy an implementation requirement.

Do not use the original paper codebase or any resource named in
`./data/blacklist.txt`. The run environment has no network access. Make the best
valid implementation that you can from the supplied paper and local tools.
"""


def _task_node(value: object, *, context: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError(f"PaperBench rubric node is not an object: {context}")
    required = {"id", "requirements", "weight", "sub_tasks"}
    if not required.issubset(value):
        raise ValueError(f"PaperBench rubric node is incomplete: {context}")
    if (
        type(value["id"]) is not str
        or not value["id"]
        or type(value["requirements"]) is not str
        or not value["requirements"].strip()
        or not isinstance(value["weight"], (int, float))
        or isinstance(value["weight"], bool)
        or value["weight"] < 0
        or type(value["sub_tasks"]) is not list
    ):
        raise ValueError(f"PaperBench rubric node has invalid fields: {context}")
    node = dict(value)
    node["sub_tasks"] = [
        _task_node(child, context=f"{context}/{index}")
        for index, child in enumerate(value["sub_tasks"])
    ]
    return node


def _prune_code_development(node: dict[str, Any]) -> dict[str, Any] | None:
    children = node["sub_tasks"]
    if not children:
        return node if node.get("task_category") == "Code Development" else None
    kept = [
        pruned
        for child in children
        if (pruned := _prune_code_development(child)) is not None
    ]
    return {**node, "sub_tasks": kept} if kept else None


def _effective_leaves(
    node: dict[str, Any],
    weight: Fraction,
    ancestors: tuple[str, ...],
) -> Iterator[tuple[dict[str, Any], Fraction, tuple[str, ...]]]:
    children = node["sub_tasks"]
    if not children:
        yield node, weight, ancestors
        return
    total = sum(Fraction(str(child["weight"])) for child in children)
    if total <= 0:
        raise ValueError("PaperBench rubric has a zero-weight internal branch")
    next_ancestors = ancestors + (_single_line(node["requirements"]),)
    for child in children:
        child_weight = Fraction(str(child["weight"]))
        yield from _effective_leaves(
            child,
            weight * child_weight / total,
            next_ancestors,
        )


def _criterion_titles(
    weighted: list[tuple[dict[str, Any], Fraction, tuple[str, ...]]],
) -> list[str]:
    """Add the shortest stable suffix that makes repeated titles distinct."""

    titles = [_single_line(node["requirements"]) for node, _, _ in weighted]
    groups: dict[str, list[int]] = {}
    for index, title in enumerate(titles):
        groups.setdefault(_normalized_title(title), []).append(index)

    for indices in groups.values():
        if len(indices) == 1:
            continue
        contexts = [weighted[index][2] for index in indices]
        maximum_depth = min(len(context) for context in contexts)
        selected: list[str] | None = None
        for depth in range(1, maximum_depth + 1):
            candidates = [
                " > ".join(context[-depth:])
                for context in contexts
            ]
            if len({_normalized_title(value) for value in candidates}) == len(
                candidates
            ):
                selected = candidates
                break
        if selected is None:
            leaf_ids = [str(weighted[index][0]["id"]) for index in indices]
            if len({_normalized_title(value) for value in leaf_ids}) != len(
                leaf_ids
            ):
                raise ValueError(
                    "PaperBench duplicate leaves lack distinct ancestor context "
                    "and leaf IDs"
                )
            selected = [f"Leaf ID: {leaf_id}" for leaf_id in leaf_ids]
        for index, context in zip(indices, selected, strict=True):
            titles[index] = f"{titles[index]} [Context: {context}]"

    if len({_normalized_title(title) for title in titles}) != len(titles):
        raise ValueError("PaperBench rendered criterion titles are not unique")
    return titles


def _single_line(value: object) -> str:
    return " ".join(str(value).split())


def _normalized_title(value: str) -> str:
    return " ".join(value.lower().split())


def _exact_integer_points(weights: list[Fraction]) -> tuple[list[int], int]:
    if not weights or sum(weights) != 1:
        raise ValueError("PaperBench effective rubric weights do not sum to one")
    normalization_maximum = math.lcm(*(weight.denominator for weight in weights))
    points = [int(weight * normalization_maximum) for weight in weights]
    common = math.gcd(*points)
    if common > 1:
        points = [point // common for point in points]
        normalization_maximum //= common
    if sum(points) != normalization_maximum:
        raise ValueError("PaperBench integer weights do not preserve the total")
    return points, normalization_maximum


def _copy_regular_tree(source: Path, destination: Path) -> None:
    destination.mkdir()
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        value = os.lstat(path)
        target = destination / relative
        if path.is_symlink() or not (
            path.is_dir() or path.is_file()
        ):
            raise ValueError(f"PaperBench asset is not regular: {path}")
        if path.is_dir():
            target.mkdir()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)


def _read_hydrated(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"PaperBench source file is missing or symlinked: {path}")
    value = path.read_bytes()
    if value.startswith(_LFS_PREFIX):
        raise ValueError(f"PaperBench source is an unhydrated Git LFS pointer: {path}")
    return value


def _yaml_mapping(value: bytes) -> dict[str, object]:
    loaded = yaml.safe_load(value.decode("utf-8"))
    if type(loaded) is not dict:
        raise ValueError("PaperBench config is not a YAML mapping")
    return loaded


def _github_directory_files(path: str, *, revision: str) -> tuple[str, ...]:
    encoded = urllib.parse.quote(path, safe="/")
    url = (
        f"https://api.github.com/repos/{PAPERBENCH_REPOSITORY}/contents/"
        f"{encoded}?ref={revision}"
    )
    request = urllib.request.Request(url, headers=_github_headers())
    with urllib.request.urlopen(request, timeout=60) as response:
        value = json.load(response)
    if type(value) is not list:
        raise ValueError(f"GitHub directory response is invalid: {path}")
    names = []
    for item in value:
        if type(item) is not dict or item.get("type") not in {"file", "dir"}:
            raise ValueError(f"GitHub returned an unsupported asset entry: {path}")
        name = item.get("name")
        if type(name) is not str or Path(name).name != name:
            raise ValueError(f"GitHub returned an unsafe asset name: {name!r}")
        if item["type"] == "file":
            names.append(name)
        else:
            names.extend(
                f"{name}/{child}"
                for child in _github_directory_files(
                    f"{path}/{name}", revision=revision
                )
            )
    return tuple(sorted(names))


def _download_media_file(path: str, destination: Path, *, revision: str) -> None:
    encoded = urllib.parse.quote(path, safe="/")
    raw_url = (
        f"https://raw.githubusercontent.com/{PAPERBENCH_REPOSITORY}/"
        f"{revision}/{encoded}"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(raw_url, headers=_github_headers())
    with urllib.request.urlopen(request, timeout=180) as response:
        value = response.read()
    if value.startswith(_LFS_PREFIX):
        media_url = (
            f"https://media.githubusercontent.com/media/{PAPERBENCH_REPOSITORY}/"
            f"{revision}/{encoded}"
        )
        request = urllib.request.Request(media_url, headers=_github_headers())
        with urllib.request.urlopen(request, timeout=180) as response:
            value = response.read()
        if value.startswith(_LFS_PREFIX):
            raise RuntimeError(f"GitHub did not hydrate the LFS object for {path}")
    destination.write_bytes(value)


def _github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "rubric-gen-paperbench-loader",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _read_json_mapping(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"PaperBench JSON file is missing or symlinked: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"PaperBench JSON file is invalid: {path}") from exc
    if type(value) is not dict:
        raise ValueError(f"PaperBench JSON file is not an object: {path}")
    return value
