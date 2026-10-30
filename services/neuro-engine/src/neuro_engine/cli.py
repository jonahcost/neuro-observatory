"""`neuro-engine` command line: dataset acquisition and anatomy preparation.

Exit status: 0 success, 1 a dataset/anatomy error or failed validation, 2 usage error.
Output never includes absolute source paths of imported personal files.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from neuro_engine.anatomy.errors import AnatomyError
from neuro_engine.datasets.errors import DatasetError
from neuro_engine.datasets.storage import DataRoot, resolve_data_root


class _Output:
    def __init__(self, as_json: bool) -> None:
        self.as_json = as_json

    def emit(self, value: Any, text: Callable[[], str] | str) -> None:
        if self.as_json:
            print(json.dumps(value, indent=2, default=str))
        else:
            print(text() if callable(text) else text)


def _progress() -> Callable[[str, int, int | None], None]:
    state = {"label": "", "at": 0.0}

    def report(label: str, received: int, total: int | None) -> None:
        now = time.monotonic()
        done = total is not None and received >= total
        if label == state["label"] and now - float(state["at"]) < 1.0 and not done:
            return
        state.update(label=label, at=now)
        size = f"{received / 1e6:.1f}/{total / 1e6:.1f} MB" if total else f"{received / 1e6:.1f} MB"
        print(f"  {label}: {size}", file=sys.stderr)

    return report


def _findings_text(findings: Sequence[Any]) -> str:
    return "\n".join(f"  {f.level:<7} {f.code}: {f.message}" for f in findings) or "  (no findings)"


# --- datasets -------------------------------------------------------------------------------


def _datasets_list(args: argparse.Namespace, root: DataRoot, out: _Output) -> int:
    from neuro_engine.datasets.catalog import DATASETS
    from neuro_engine.datasets.provenance import read_record

    rows = []
    for spec in DATASETS.values():
        record = read_record(root, spec.id, spec.version)
        rows.append(
            {
                "id": spec.id,
                "version": spec.version,
                "anatomyKind": spec.anatomy_kind,
                "license": spec.license.id,
                "acquiredFiles": len(record.files) if record else 0,
                "approxDownloadBytes": spec.approx_download_bytes,
            }
        )
    out.emit(
        {"dataRoot": "private-local", "datasets": rows},
        lambda: "data root: private local directory\n"
        + "\n".join(
            f"  {r['id']:<10} {r['version']:<24} {r['anatomyKind']:<18} {r['license']:<28} "
            f"{'acquired ' + str(r['acquiredFiles']) + ' files' if r['acquiredFiles'] else 'not acquired'}"
            for r in rows
        ),
    )
    return 0


def _datasets_info(args: argparse.Namespace, root: DataRoot, out: _Output) -> int:
    from dataclasses import asdict

    from neuro_engine.datasets.catalog import get_dataset
    from neuro_engine.datasets.provenance import read_record

    spec = get_dataset(args.dataset)
    record = read_record(root, spec.id, spec.version)
    value = {**asdict(spec), "acquisition_record": record.model_dump(mode="json") if record else None}
    out.emit(
        value,
        lambda: "\n".join(
            [
                f"{spec.title}",
                f"  id/version:   {spec.id} {spec.version}",
                f"  kind:         {spec.anatomy_kind}",
                f"  license:      {spec.license.name} [{spec.license.id}] ({spec.license.url})",
                f"  attribution:  {spec.license.attribution}",
                f"  homepage:     {spec.homepage}",
                f"  DOI:          {spec.doi or '-'}",
                (f"  MRI:          {spec.acquisition.field_strength_tesla or '-'} T, {spec.acquisition.sequence or '-'}, "
                f"{spec.acquisition.scanner or '-'} (source: {spec.acquisition.source})"),
                f"  description:  {spec.description}",
                *(f"  note:         {n}" for n in spec.notes),
                f"  acquired:     {len(record.files)} files, updated {record.updated_at_utc}" if record else "  acquired:     no",
            ]
        ),
    )
    return 0


def _datasets_fetch(args: argparse.Namespace, root: DataRoot, out: _Output) -> int:
    if args.dataset == "fsaverage":
        from neuro_engine.datasets.fsaverage import fetch_fsaverage

        path = fetch_fsaverage(root, accept_license=args.accept_license)
        relative = path.relative_to(root.path).as_posix()
        out.emit({"dataset": "fsaverage", "subjectDir": relative}, f"fsaverage ready: {relative}")
    elif args.dataset == "ds000248":
        from neuro_engine.datasets.openneuro import fetch_openneuro

        report = fetch_openneuro(root, profile=args.profile, confirm_large=args.confirm_large, progress=_progress())
        out.emit(
            {"dataset": report.dataset_id, "version": report.version, "downloaded": report.downloaded,
             "alreadyPresent": report.already_present, "totalBytes": report.total_bytes},
            f"{report.dataset_id} {report.version}: {report.downloaded} downloaded, {report.already_present} already present "
            f"({report.total_bytes / 1e6:.1f} MB selected)",
        )
    elif args.dataset == "ixi":
        from neuro_engine.datasets.ixi import fetch_ixi_subject

        if not args.subject:
            raise DatasetError("missing-subject", "IXI fetches one subject at a time", "pass --subject IXI012-HH-1211")
        path = fetch_ixi_subject(
            root,
            args.subject,
            accept_license=args.accept_license,
            assume_mm=args.assume_mm,
            progress=_progress(),
        )
        out.emit({"dataset": "ixi", "file": path.name}, f"IXI {args.subject} verified: {path.name}")
    else:
        raise DatasetError("not-fetchable", f"'{args.dataset}' cannot be fetched", "use 'datasets import-mri' for local data")
    return 0


def _datasets_import_ixi(args: argparse.Namespace, root: DataRoot, out: _Output) -> int:
    from neuro_engine.datasets.ixi import import_ixi_file

    path = import_ixi_file(root, Path(args.file), accept_license=args.accept_license, assume_mm=args.assume_mm)
    out.emit({"dataset": "ixi", "file": path.name}, f"imported and verified {path.name}")
    return 0


def _datasets_import_mri(args: argparse.Namespace, root: DataRoot, out: _Output) -> int:
    from neuro_engine.datasets.local import import_mri

    path = import_mri(
        root,
        Path(args.file),
        args.label,
        field_strength_tesla=args.field_strength,
        sequence=args.sequence,
        scanner=args.scanner,
        assume_mm=args.assume_mm,
    )
    out.emit({"subject": f"local/{args.label}", "file": path.name}, f"imported T1 for local/{args.label}")
    return 0


def _datasets_import_freesurfer(args: argparse.Namespace, root: DataRoot, out: _Output) -> int:
    from neuro_engine.datasets.local import import_freesurfer

    import_freesurfer(
        root,
        Path(args.subject_dir),
        args.label,
        tool_name=args.tool,
        tool_version=args.tool_version,
        command_summary=args.command_summary,
        qc_status=args.qc_status,
        qc_notes=args.qc_notes or "",
    )
    out.emit({"subject": f"local/{args.label}"}, f"imported FreeSurfer subject as local/{args.label}")
    return 0


def _datasets_register_reconstruction(args: argparse.Namespace, root: DataRoot, out: _Output) -> int:
    from neuro_engine.datasets.reconstruction import write_reconstruction_record
    from neuro_engine.datasets.subjects import resolve_subject

    subject = resolve_subject(root, args.subject)
    path = write_reconstruction_record(
        root,
        subject,
        tool_name=args.tool,
        tool_version=args.tool_version,
        command_summary=args.command_summary,
        qc_status=args.qc_status,
        qc_notes=args.qc_notes or "",
    )
    out.emit(
        {"subject": subject.key, "record": path.name, "qcStatus": args.qc_status},
        f"recorded reconstruction provenance for {subject.key}: QC {args.qc_status}",
    )
    return 0


def _datasets_validate(args: argparse.Namespace, root: DataRoot, out: _Output) -> int:
    from neuro_engine.datasets.catalog import get_dataset
    from neuro_engine.datasets.provenance import read_record, verify_record

    spec = get_dataset(args.dataset)
    record = read_record(root, spec.id, spec.version)
    if record is None:
        raise DatasetError("not-acquired", f"{spec.id} {spec.version} has not been acquired", f"fetch or import {spec.id} first")
    problems = verify_record(root, record)
    out.emit(
        {"dataset": spec.id, "version": spec.version, "files": len(record.files), "problems": problems},
        lambda: f"{spec.id} {spec.version}: {len(record.files)} files checked, "
        + ("all match their recorded SHA-256" if not problems else f"{len(problems)} problems\n  " + "\n  ".join(problems)),
    )
    return 1 if problems else 0


def _datasets_subjects(args: argparse.Namespace, root: DataRoot, out: _Output) -> int:
    from neuro_engine.datasets.subjects import list_subjects

    subjects = [s.summary() for s in list_subjects(root)]
    out.emit(
        {"subjects": subjects},
        lambda: "\n".join(
            f"  {s['key']:<28} {s['anatomyKind']:<18} T1={'yes' if s['t1'] else 'no ':<4} "
            f"surfaces={'yes' if s['surfacesAvailable'] else 'no'}"
            for s in subjects
        )
        or "  no subjects yet; see 'neuro-engine datasets fetch --help'",
    )
    return 0


def _datasets_check_subject(args: argparse.Namespace, root: DataRoot, out: _Output) -> int:
    from neuro_engine.datasets.subjects import check_subject, resolve_subject

    subject = resolve_subject(root, args.subject)
    findings = check_subject(subject)
    out.emit(
        {"subject": subject.summary(), "findings": [{"level": f.level, "code": f.code, "message": f.message} for f in findings]},
        lambda: f"{subject.key}\n{_findings_text(findings)}",
    )
    return 1 if any(f.level == "error" for f in findings) else 0


def _datasets_inspect_eeg(args: argparse.Namespace, root: DataRoot, out: _Output) -> int:
    from neuro_engine.datasets.eeg import inspect_eeg
    from neuro_engine.datasets.subjects import resolve_subject

    result = inspect_eeg(resolve_subject(root, args.subject))
    summary = result.summary()
    out.emit(summary, lambda: "\n".join(f"  {k}: {v}" for k, v in summary.items()))
    return 0


# --- anatomy --------------------------------------------------------------------------------


def _anatomy_check_mri(args: argparse.Namespace, root: DataRoot, out: _Output) -> int:
    from neuro_engine.anatomy.volumes import check_mri

    check = check_mri(Path(args.file), read_data=True, assume_mm=args.assume_mm)
    out.emit(
        {"volume": check.info.summary(), "findings": [{"level": f.level, "code": f.code, "message": f.message} for f in check.findings]},
        lambda: "\n".join(f"  {k}: {v}" for k, v in check.info.summary().items()) + "\n" + _findings_text(check.findings),
    )
    return 0 if check.ok else 1


def _anatomy_prepare(args: argparse.Namespace, root: DataRoot, out: _Output) -> int:
    from neuro_engine.anatomy.assets import prepare_asset
    from neuro_engine.datasets.subjects import resolve_subject

    subject = resolve_subject(root, args.subject)
    surfaces = [s.strip() for s in args.surfaces.split(",") if s.strip()]
    prepared = prepare_asset(root, subject, surfaces=surfaces, atlases=args.atlas or None)
    out.emit(
        {"assetId": prepared.asset_id, "created": prepared.created},
        f"{'prepared' if prepared.created else 'already prepared'}: {prepared.asset_id}",
    )
    return 0


def _anatomy_assets(args: argparse.Namespace, root: DataRoot, out: _Output) -> int:
    from neuro_engine.anatomy.assets import AssetStore
    from neuro_engine.protocol.anatomy_v1 import to_wire_dict

    store = AssetStore(root)
    catalog = store.catalog()
    _, problems = store.assets()
    out.emit(
        {**to_wire_dict(catalog), "problems": problems},
        lambda: "\n".join(
            [
                *(
                    f"  {'*' if a.asset_id == catalog.default_asset_id else ' '} {a.asset_id:<44} {a.anatomy_kind:<18} "
                    f"{','.join(a.surfaces)}  atlases: {','.join(a.atlases) or '-'}"
                    for a in catalog.assets
                ),
                *(f"  invalid: {p}" for p in problems),
            ]
        )
        or "  no assets; run 'neuro-engine anatomy prepare <subject>'",
    )
    return 0


def _anatomy_info(args: argparse.Namespace, root: DataRoot, out: _Output) -> int:
    from neuro_engine.anatomy.assets import AssetStore
    from neuro_engine.protocol.anatomy_v1 import to_wire_dict

    asset = AssetStore(root).manifest(args.asset_id)
    wire = to_wire_dict(asset)

    def text() -> str:
        lines = [
            f"{asset.asset_id}: {asset.subject.display_name} [{asset.anatomy_kind}]",
            f"  frame: {asset.coordinate_frame} ({asset.units}); license: {asset.license.id}",
            f"  MRI: {asset.acquisition.field_strength_tesla or '-'} T {asset.acquisition.sequence or ''} (source: {asset.acquisition.source})",
        ]
        lines += [
            f"  {s.hemisphere}.{s.surface:<9} {s.vertex_count:>8} vertices {s.triangle_count:>8} triangles  "
            f"bounds {[round(v, 1) for v in s.bounds_mm.min]}..{[round(v, 1) for v in s.bounds_mm.max]} mm"
            for s in asset.surfaces
        ]
        lines += [f"  atlas {p.hemisphere}.{p.atlas}: {len(p.labels)} labels" for p in asset.parcellations]
        lines += [f"  transform {t.from_} -> {t.to} ({t.source})" for t in asset.transforms]
        return "\n".join(lines)

    out.emit(wire, text)
    return 0


def _anatomy_verify(args: argparse.Namespace, root: DataRoot, out: _Output) -> int:
    from neuro_engine.anatomy.assets import AssetStore

    problems = AssetStore(root).verify(args.asset_id)
    out.emit(
        {"assetId": args.asset_id, "problems": problems},
        lambda: f"{args.asset_id}: " + ("verified" if not problems else "\n  ".join(["FAILED", *problems])),
    )
    return 1 if problems else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="neuro-engine", description="Neuro Observatory engine tools.")
    parser.add_argument("--data-dir", help="data root (default: $NEURO_ENGINE_DATA_DIR or the per-user data directory)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    groups = parser.add_subparsers(dest="group", required=True)

    datasets = groups.add_parser("datasets", help="acquire, import and validate datasets").add_subparsers(dest="command", required=True)
    p = datasets.add_parser("list", help="supported datasets and acquisition status")
    p.set_defaults(handler=_datasets_list)
    p = datasets.add_parser("info", help="license, provenance and acquisition facts of one dataset")
    p.add_argument("dataset")
    p.set_defaults(handler=_datasets_info)
    p = datasets.add_parser("fetch", help="download a dataset (verified, resumable)")
    p.add_argument("dataset", choices=["fsaverage", "ds000248", "ixi"])
    p.add_argument("--accept-license", action="store_true", help="confirm you accept the dataset license (fsaverage, IXI)")
    p.add_argument("--profile", default="anatomy", choices=["anatomy", "full"], help="ds000248 file selection")
    p.add_argument("--confirm-large", action="store_true", help="allow downloads above 500 MB")
    p.add_argument("--subject", help="IXI subject, e.g. IXI012-HH-1211")
    p.add_argument("--assume-mm", action="store_true", help="explicitly treat unset NIfTI spatial units as millimetres")
    p.set_defaults(handler=_datasets_fetch)
    p = datasets.add_parser("import", help="import an IXI T1 file you downloaded yourself")
    p.add_argument("dataset", choices=["ixi"])
    p.add_argument("file")
    p.add_argument("--accept-license", action="store_true")
    p.add_argument("--assume-mm", action="store_true", help="explicitly treat unset NIfTI spatial units as millimetres")
    p.set_defaults(handler=_datasets_import_ixi)
    p = datasets.add_parser("import-mri", help="import a personal T1 volume (NIfTI or MGZ)")
    p.add_argument("file")
    p.add_argument("--label", required=True, help="pseudonymous subject label, e.g. 'me'")
    p.add_argument("--field-strength", type=float, help="tesla, as declared by you")
    p.add_argument("--sequence")
    p.add_argument("--scanner")
    p.add_argument("--assume-mm", action="store_true", help="explicitly treat unset NIfTI spatial units as millimetres")
    p.set_defaults(handler=_datasets_import_mri)
    p = datasets.add_parser("import-freesurfer", help="import an existing FreeSurfer subject directory")
    p.add_argument("subject_dir")
    p.add_argument("--label", required=True)
    p.add_argument("--tool", required=True, help="reconstruction tool, e.g. freesurfer or fastsurfer")
    p.add_argument("--tool-version", required=True)
    p.add_argument("--command-summary", required=True, help="privacy-safe command/config summary without identifying paths")
    p.add_argument("--qc-status", required=True, choices=["passed", "failed", "not-reviewed"])
    p.add_argument("--qc-notes")
    p.set_defaults(handler=_datasets_import_freesurfer)
    p = datasets.add_parser("register-reconstruction", help="record tool, inputs, outputs and QC for an external reconstruction")
    p.add_argument("subject")
    p.add_argument("--tool", required=True)
    p.add_argument("--tool-version", required=True)
    p.add_argument("--command-summary", required=True, help="privacy-safe command/config summary without identifying paths")
    p.add_argument("--qc-status", required=True, choices=["passed", "failed", "not-reviewed"])
    p.add_argument("--qc-notes")
    p.set_defaults(handler=_datasets_register_reconstruction)
    p = datasets.add_parser("validate", help="re-hash acquired files against the provenance record")
    p.add_argument("dataset")
    p.set_defaults(handler=_datasets_validate)
    p = datasets.add_parser("subjects", help="subjects available under the data root")
    p.set_defaults(handler=_datasets_subjects)
    p = datasets.add_parser("check-subject", help="consistency checks for one subject")
    p.add_argument("subject")
    p.set_defaults(handler=_datasets_check_subject)
    p = datasets.add_parser("inspect-eeg", help="EEG recording metadata (needs the neuroimaging extra)")
    p.add_argument("subject")
    p.set_defaults(handler=_datasets_inspect_eeg)

    anatomy = groups.add_parser("anatomy", help="validate MRI and prepare app-ready anatomy").add_subparsers(dest="command", required=True)
    p = anatomy.add_parser("check-mri", help="validate a T1 volume as FreeSurfer input")
    p.add_argument("file")
    p.add_argument("--assume-mm", action="store_true", help="explicitly treat unset NIfTI spatial units as millimetres")
    p.set_defaults(handler=_anatomy_check_mri)
    p = anatomy.add_parser("prepare", help="convert a subject's FreeSurfer surfaces into an anatomy asset")
    p.add_argument("subject", help="subject key, e.g. fsaverage or ds000248/sub-01")
    p.add_argument("--surfaces", default="pial,white,inflated")
    p.add_argument("--atlas", action="append", help="aparc, aparc.a2009s or aparc.DKTatlas (repeatable; default: all present)")
    p.set_defaults(handler=_anatomy_prepare)
    p = anatomy.add_parser("assets", help="list prepared assets")
    p.set_defaults(handler=_anatomy_assets)
    p = anatomy.add_parser("info", help="describe one asset")
    p.add_argument("asset_id")
    p.set_defaults(handler=_anatomy_info)
    p = anatomy.add_parser("verify", help="re-verify one asset's buffers")
    p.add_argument("asset_id")
    p.set_defaults(handler=_anatomy_verify)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out = _Output(args.json)
    try:
        root = resolve_data_root(args.data_dir)
        return int(args.handler(args, root, out))
    except (DatasetError, AnatomyError) as exc:
        hint = getattr(exc, "hint", None)
        if args.json:
            print(json.dumps({"error": {"code": exc.code, "message": exc.message, "hint": hint}}), file=sys.stderr)
        else:
            print(f"error [{exc.code}]: {exc.message}", file=sys.stderr)
            if hint:
                print(f"hint: {hint}", file=sys.stderr)
        return 1
