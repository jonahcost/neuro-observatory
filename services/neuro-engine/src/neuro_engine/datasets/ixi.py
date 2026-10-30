"""IXI T1 volumes: single-member ranged fetch from IXI-T1.tar, or local import.

IXI publishes no checksums. Integrity comes from the tar header checksum, the
member size, and the gzip CRC-32 checked on full decompression; the SHA-256 we
observe is recorded. IXI.xls (demographics) is never downloaded or imported.
"""

from __future__ import annotations

import gzip
import os
import re
import shutil
import tarfile
import tempfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from neuro_engine import __version__
from neuro_engine.anatomy.errors import AnatomyError
from neuro_engine.anatomy.volumes import check_mri
from neuro_engine.datasets.catalog import (
    IXI_GUYS_T1,
    IXI_HH_T1,
    IXI_IOP_T1,
    MriAcquisitionFacts,
    get_dataset,
)
from neuro_engine.datasets.download import (
    DownloadTarget,
    Opener,
    Progress,
    fetch,
    read_range,
)
from neuro_engine.datasets.errors import DatasetError
from neuro_engine.datasets.integrity import CHUNK_BYTES, ExpectedChecksum, sha256_file
from neuro_engine.datasets.provenance import (
    AcquiredFile,
    DeclaredAcquisition,
    ToolVersion,
    new_record,
    read_record,
    utc_now,
    write_record,
)
from neuro_engine.datasets.storage import DataRoot, private_mkdir

IXI_T1_TAR_URL = "https://biomedic.doc.ic.ac.uk/brain-development/downloads/IXI/IXI-T1.tar"
ALLOWED = ("biomedic.doc.ic.ac.uk/brain-development/downloads/IXI/IXI-T1.tar",)
# Members are ordered by IXI number; scanning stops well before the archive end.
MAX_SCANNED_MEMBERS = 128
MAX_IXI_MEMBER_BYTES = 250_000_000
MAX_IXI_DECOMPRESSED_BYTES = 2_000_000_000
_NAME = re.compile(r"^(?P<subject>IXI(?P<number>\d{3})-(?P<site>Guys|HH|IOP)-(?P<scan>\d{4}))-T1\.nii\.gz$")
_SUBJECT = re.compile(r"^IXI\d{3}-(Guys|HH|IOP)-\d{4}$")
SITE_FACTS: dict[str, MriAcquisitionFacts] = {"HH": IXI_HH_T1, "Guys": IXI_GUYS_T1, "IOP": IXI_IOP_T1}

RangeReader = Callable[[int, int], bytes]


@dataclass(frozen=True, slots=True)
class IxiT1:
    subject_id: str
    site: str
    file_name: str

    @property
    def acquisition(self) -> MriAcquisitionFacts:
        return SITE_FACTS[self.site]


def parse_ixi_t1_name(file_name: str) -> IxiT1:
    match = _NAME.match(file_name)
    if not match:
        raise DatasetError(
            "not-ixi-t1",
            f"'{file_name}' is not an IXI T1 file name",
            "expected IXI<nnn>-<Guys|HH|IOP>-<nnnn>-T1.nii.gz, e.g. IXI012-HH-1211-T1.nii.gz",
        )
    return IxiT1(subject_id=match["subject"], site=match["site"], file_name=file_name)


def subject_file_name(subject_id: str) -> str:
    if not _SUBJECT.match(subject_id):
        raise DatasetError("not-ixi-subject", f"'{subject_id}' is not an IXI subject ID", "expected e.g. IXI012-HH-1211")
    return f"{subject_id}-T1.nii.gz"


@dataclass(frozen=True, slots=True)
class TarMember:
    name: str
    data_offset: int
    size: int


def locate_tar_member(name: str, read: RangeReader, *, max_members: int = MAX_SCANNED_MEMBERS) -> TarMember:
    """Walk ustar headers (512 bytes each, checksum-verified) until `name` is found."""
    offset = 0
    for _ in range(max_members):
        block = read(offset, tarfile.BLOCKSIZE)
        if block == b"\0" * tarfile.BLOCKSIZE:
            break
        try:
            info = tarfile.TarInfo.frombuf(block, "utf-8", "surrogateescape")
        except tarfile.HeaderError:
            raise DatasetError(
                "corrupt-archive", f"invalid tar header at byte {offset}", "use local import instead"
            ) from None
        if info.type in (tarfile.GNUTYPE_LONGNAME, tarfile.XHDTYPE, tarfile.XGLTYPE):
            raise DatasetError("unsupported-archive", "the archive uses extended tar headers", "use local import instead")
        data_offset = offset + tarfile.BLOCKSIZE
        if info.name == name and info.isfile():
            if not 0 < info.size <= MAX_IXI_MEMBER_BYTES:
                raise DatasetError(
                    "invalid-member-size",
                    f"{name} has implausible size {info.size}",
                    "use local import after independently verifying the archive",
                )
            return TarMember(name=name, data_offset=data_offset, size=info.size)
        offset = data_offset + -(-info.size // tarfile.BLOCKSIZE) * tarfile.BLOCKSIZE
    raise DatasetError(
        "member-not-found",
        f"{name} is not among the first {max_members} members of IXI-T1.tar",
        "choose an earlier subject or download the file yourself and use 'datasets import ixi'",
    )


def verify_gzip(path: Path) -> None:
    """Decompress fully; gzip checks the CRC-32 and length trailer."""
    try:
        decoded = 0
        with gzip.open(path, "rb") as f:
            while chunk := f.read(CHUNK_BYTES):
                decoded += len(chunk)
                if decoded > MAX_IXI_DECOMPRESSED_BYTES:
                    raise DatasetError(
                        "invalid-volume",
                        f"{path.name}: decompressed data exceeds {MAX_IXI_DECOMPRESSED_BYTES} bytes",
                    )
    except (OSError, EOFError, zlib.error) as exc:
        raise DatasetError("corrupt-file", f"{path.name}: gzip integrity check failed ({type(exc).__name__})") from None


def _validate_volume(path: Path, *, assume_mm: bool = False) -> None:
    try:
        check = check_mri(path, read_data=True, assume_mm=assume_mm)
    except AnatomyError as exc:
        raise DatasetError("invalid-volume", exc.message, "the file is not a usable T1 volume") from None
    errors = [f for f in check.findings if f.level == "error"]
    if errors:
        raise DatasetError("invalid-volume", f"{path.name}: {errors[0].message}")


def _record(root: DataRoot, entry: AcquiredFile, ixi: IxiT1, *, assume_mm: bool) -> None:
    spec = get_dataset("ixi")
    record = read_record(root, spec.id, spec.version) or new_record(
        spec, tools=[ToolVersion(name="neuro-engine", version=__version__)]
    )
    record.license_accepted_at_utc = record.license_accepted_at_utc or utc_now()
    record.upsert_files([entry])
    record.declared_acquisition[ixi.subject_id] = DeclaredAcquisition(
        field_strength_tesla=ixi.acquisition.field_strength_tesla,
        sequence=ixi.acquisition.sequence,
        scanner=ixi.acquisition.scanner,
        spatial_units_assumed_mm=assume_mm,
    )
    if ixi.site != "HH":
        note = f"{ixi.subject_id}: {SITE_FACTS[ixi.site].scanner} (1.5 T), not the 3 T Hammersmith cohort"
        if note not in record.notes:
            record.notes.append(note)
    write_record(root, record)


def _require_license(accept_license: bool) -> None:
    spec = get_dataset("ixi")
    if not accept_license:
        raise DatasetError(
            "license-not-accepted",
            f"IXI is distributed under {spec.license.name} ({spec.license.url})",
            "re-run with --accept-license",
        )


def fetch_ixi_subject(
    root: DataRoot,
    subject_id: str,
    *,
    accept_license: bool,
    assume_mm: bool = False,
    opener: Opener | None = None,
    progress: Progress | None = None,
) -> Path:
    _require_license(accept_license)
    ixi = parse_ixi_t1_name(subject_file_name(subject_id))
    spec = get_dataset("ixi")
    destination = root.raw(spec.id, spec.version) / ixi.file_name
    record = read_record(root, spec.id, spec.version)
    previous = record.file_index().get(ixi.file_name) if record else None
    if destination.is_file() and previous is None:
        raise DatasetError(
            "unverified-existing-file",
            f"{ixi.file_name} exists without recorded provenance",
            "move it aside and fetch again, or import it explicitly",
        )
    member = locate_tar_member(
        ixi.file_name, lambda start, length: read_range(IXI_T1_TAR_URL, start, length, allowed=ALLOWED, opener=opener)
    )

    def validate_download(path: Path) -> None:
        verify_gzip(path)
        _validate_volume(path, assume_mm=assume_mm)

    root.prepare_for_writing()
    fetch(
        DownloadTarget(
            url=IXI_T1_TAR_URL,
            destination=destination,
            partial=root.downloads(spec.id, spec.version) / f".{ixi.file_name}.part.nii.gz",
            size=member.size,
            checksum=ExpectedChecksum("sha256", previous.sha256) if previous is not None else None,
            label=f"ixi/{ixi.file_name}",
            member_offset=member.data_offset,
        ),
        allowed=ALLOWED,
        opener=opener,
        progress=progress,
        validate=validate_download,
    )
    _record(
        root,
        AcquiredFile(
            path=ixi.file_name,
            bytes=destination.stat().st_size,
            sha256=sha256_file(destination),
            upstream_checksum=f"tar-member:IXI-T1.tar@{member.data_offset}+{member.size};gzip-crc32-verified",
            source_url=IXI_T1_TAR_URL,
        ),
        ixi,
        assume_mm=assume_mm,
    )
    return destination


def import_ixi_file(root: DataRoot, source: Path, *, accept_license: bool, assume_mm: bool = False) -> Path:
    _require_license(accept_license)
    ixi = parse_ixi_t1_name(source.name)
    if not source.is_file():
        raise DatasetError("missing-file", f"{source.name} not found", "check the path")
    spec = get_dataset("ixi")
    root.prepare_for_writing()
    destination = root.raw(spec.id, spec.version) / ixi.file_name
    private_mkdir(destination.parent)
    descriptor, tmp_name = tempfile.mkstemp(prefix=".stage-ixi-", suffix=".nii.gz", dir=destination.parent)
    tmp = Path(tmp_name)
    try:
        with source.open("rb") as source_stream, os.fdopen(descriptor, "wb") as target_stream:
            shutil.copyfileobj(source_stream, target_stream)
            target_stream.flush()
            os.fsync(target_stream.fileno())
        verify_gzip(tmp)
        _validate_volume(tmp, assume_mm=assume_mm)
        digest = sha256_file(tmp)
        if destination.is_symlink():
            raise DatasetError("unsafe-path", f"refusing symlinked destination {destination.name}")
        if destination.is_file():
            if sha256_file(destination) != digest:
                raise DatasetError(
                    "existing-file-mismatch",
                    f"a different {ixi.file_name} is already imported",
                    "raw files are never overwritten; move the existing file aside first",
                )
            if os.name == "posix":
                destination.chmod(0o600)
        else:
            try:
                os.link(tmp, destination)
            except FileExistsError:
                if destination.is_symlink():
                    raise DatasetError("unsafe-path", f"destination {destination.name} became a symlink") from None
                if sha256_file(destination) != digest:
                    raise DatasetError("existing-file-mismatch", f"a different {ixi.file_name} was imported concurrently") from None
            if os.name == "posix":
                destination.chmod(0o600)
    finally:
        tmp.unlink(missing_ok=True)
    _record(
        root,
        AcquiredFile(path=ixi.file_name, bytes=destination.stat().st_size, sha256=digest, upstream_checksum=None, source_url=None),
        ixi,
        assume_mm=assume_mm,
    )
    return destination
