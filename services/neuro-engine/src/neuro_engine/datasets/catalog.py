"""Supported datasets. Facts verified against the official sources on 2026-10-30 (ADR-0010)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from neuro_engine.datasets.errors import DatasetError

AnatomyKind = Literal["template", "reference-subject", "personal"]
AcquisitionSource = Literal["sidecar", "dataset-readme", "site-documentation", "user-declared", "not-applicable"]

# Downloads above this size need --confirm-large.
LARGE_DOWNLOAD_BYTES = 500_000_000


@dataclass(frozen=True, slots=True)
class LicenseInfo:
    id: str
    name: str
    url: str
    attribution: str
    requires_acceptance: bool
    notes: str = ""


@dataclass(frozen=True, slots=True)
class MriAcquisitionFacts:
    """Structural MRI facts and where they come from. Unknown values stay None."""

    field_strength_tesla: float | None
    sequence: str | None
    scanner: str | None
    source: AcquisitionSource
    parameters: tuple[tuple[str, str], ...] = ()
    spatial_units_assumed_mm: bool = False


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    id: str
    title: str
    version: str
    anatomy_kind: AnatomyKind
    description: str
    homepage: str
    doi: str | None
    license: LicenseInfo
    method: Literal["mne-fetch-fsaverage", "openneuro-graphql", "ixi-tar-range", "local-import"]
    approx_download_bytes: int | None
    modalities: tuple[str, ...]
    acquisition: MriAcquisitionFacts
    notes: tuple[str, ...] = ()


FREESURFER_LICENSE = LicenseInfo(
    id="LicenseRef-FreeSurfer-1.0",
    name="FreeSurfer Software License Agreement v1.0",
    url="https://surfer.nmr.mgh.harvard.edu/fswiki/FreeSurferSoftwareLicense",
    attribution=(
        "fsaverage is part of FreeSurfer (The General Hospital Corporation, Boston MA, USA), "
        "redistributed by MNE-Python. Research use only; not for clinical use."
    ),
    requires_acceptance=True,
    notes=(
        "Redistribution must include the license terms prefaced by the MGH notice and mark modifications; "
        "this project does not redistribute fsaverage or assets derived from it."
    ),
)

CC0_LICENSE = LicenseInfo(
    id="CC0-1.0",
    name="Creative Commons Zero v1.0",
    url="https://creativecommons.org/publicdomain/zero/1.0/",
    attribution=(
        "OpenNeuro ds000248 v1.2.4 (MNE sample data, Gramfort & Hamalainen). Please cite Gramfort et al., "
        "NeuroImage 86 (2014) 446-460 and Frontiers in Neuroscience 7 (2013) 267."
    ),
    requires_acceptance=False,
)

IXI_LICENSE = LicenseInfo(
    id="CC-BY-SA-3.0",
    name="Creative Commons Attribution-ShareAlike 3.0",
    url="https://creativecommons.org/licenses/by-sa/3.0/legalcode",
    attribution="IXI dataset, Information eXtraction from Images (EPSRC GR/S21533/02), https://brain-development.org/ixi-dataset/",
    requires_acceptance=True,
    notes="Derivatives must be shared under the same license if redistributed.",
)

LOCAL_LICENSE = LicenseInfo(
    id="LicenseRef-Local-Private",
    name="Private local data",
    url="https://github.com/jonahcost/neuro-observatory/blob/main/docs/standards/security.md",
    attribution="Imported by the local user; restricted data, never redistributed.",
    requires_acceptance=False,
)

IXI_HH_T1 = MriAcquisitionFacts(
    field_strength_tesla=3.0,
    sequence="T1-weighted gradient echo (TR 9.6 ms, TE 4.6 ms, flip 8 deg)",
    scanner="Philips Intera 3T (Hammersmith Hospital)",
    source="site-documentation",
    parameters=(
        ("RepetitionTimeMs", "9.60000038146972"),
        ("EchoTimeMs", "4.60269975662231"),
        ("FlipAngleDeg", "8.0"),
        ("AcquisitionMatrix", "208 x 208"),
        ("ReconstructionDiameterMm", "240.0"),
        ("PhaseEncodingSteps", "208"),
        ("EchoTrainLength", "208"),
        ("Source", "https://brain-development.org/scanner-philips-medical-systems-intera-3t/"),
    ),
)
IXI_GUYS_T1 = MriAcquisitionFacts(
    field_strength_tesla=1.5,
    sequence=None,
    scanner="Philips Gyroscan Intera 1.5T (Guy's Hospital)",
    source="site-documentation",
)
IXI_IOP_T1 = MriAcquisitionFacts(
    field_strength_tesla=1.5,
    sequence=None,
    scanner="GE 1.5T (Institute of Psychiatry)",
    source="site-documentation",
)

DATASETS: dict[str, DatasetSpec] = {
    "fsaverage": DatasetSpec(
        id="fsaverage",
        title="FreeSurfer fsaverage template (via MNE-Python)",
        version="mne-osf-3bxqt-v2",
        anatomy_kind="template",
        description=(
            "FreeSurfer 6 fsaverage average subject with MNE parcellations, head surface, fiducials and BEMs. "
            "Surface RAS equals MNI305. Default anatomy until another subject is selected."
        ),
        homepage="https://mne.tools/stable/generated/mne.datasets.fetch_fsaverage.html",
        doi=None,
        license=FREESURFER_LICENSE,
        method="mne-fetch-fsaverage",
        approx_download_bytes=195_858_394 + 231_112_532,
        modalities=("surfaces", "parcellations", "mri", "bem"),
        acquisition=MriAcquisitionFacts(None, None, None, "not-applicable"),
        notes=(
            ("Archives pinned by MD5 in MNE 1.13: osf.io/download/3bxqt?version=2 (5133fe92b7b8f03ae19219d5f46e4177) "
            "and osf.io/download/7ve8g?version=4 (b31509cdcf7908af6a83dc5ee8f49fb1)."),
        ),
    ),
    "ds000248": DatasetSpec(
        id="ds000248",
        title="OpenNeuro ds000248: MNE sample data (BIDS)",
        version="1.2.4",
        anatomy_kind="reference-subject",
        description=(
            "One participant (sub-01): 1.5 T MPRAGE T1w, FLASH, simultaneous 306-channel MEG and 60-channel EEG "
            "(audiovisual task, 600.615 Hz) and FreeSurfer derivatives. Suitable for development; not equivalent "
            "to a 3 T acquisition."
        ),
        homepage="https://openneuro.org/datasets/ds000248/versions/1.2.4",
        doi="10.18112/openneuro.ds000248.v1.2.4",
        license=CC0_LICENSE,
        method="openneuro-graphql",
        approx_download_bytes=201_537_926,  # profile "anatomy" (36 files)
        modalities=("anat", "meg", "eeg", "freesurfer"),
        acquisition=MriAcquisitionFacts(1.5, "MPRAGE", "Siemens Sonata 1.5T", "dataset-readme"),
        notes=(
            "Distinct from the MNE 'sample' archive (mne.datasets.sample), which is a separate release.",
            "Field strength and sequence come from the dataset README; the T1w sidecar has no acquisition fields.",
            "Full snapshot: 1 229 files, 2.07 GB (profile 'full', requires --confirm-large).",
        ),
    ),
    "ixi": DatasetSpec(
        id="ixi",
        title="IXI brain MRI dataset (T1)",
        version="ixi-t1-tar-2014-10-07",
        anatomy_kind="reference-subject",
        description=(
            "T1-weighted NIfTI images of healthy adults from three London sites. Only single subjects are "
            "acquired here; the 4.84 GB archive is never downloaded whole."
        ),
        homepage="https://brain-development.org/ixi-dataset/",
        doi=None,
        license=IXI_LICENSE,
        method="ixi-tar-range",
        approx_download_bytes=10_120_330,
        modalities=("anat",),
        acquisition=IXI_HH_T1,
        notes=(
            ("Archive https://biomedic.doc.ic.ac.uk/brain-development/downloads/IXI/IXI-T1.tar, 4 840 816 640 bytes, "
            "Last-Modified 2014-10-07. No upstream checksums are published."),
            "Scanner parameters are documented per site, not per scan; NIfTI headers carry no scanner metadata.",
            "Demographics (IXI.xls) are never downloaded or imported.",
        ),
    ),
    "local": DatasetSpec(
        id="local",
        title="Locally imported MRI and FreeSurfer subjects",
        version="1",
        anatomy_kind="personal",
        description="T1 volumes and FreeSurfer reconstructions imported from local files (e.g. the owner's own MRI).",
        homepage="https://github.com/jonahcost/neuro-observatory/blob/main/services/neuro-engine/README.md",
        doi=None,
        license=LOCAL_LICENSE,
        method="local-import",
        approx_download_bytes=None,
        modalities=("anat", "freesurfer"),
        acquisition=MriAcquisitionFacts(None, None, None, "user-declared"),
    ),
}


def get_dataset(dataset_id: str) -> DatasetSpec:
    try:
        return DATASETS[dataset_id]
    except KeyError:
        raise DatasetError(
            "unknown-dataset",
            f"unknown dataset '{dataset_id}'",
            f"supported datasets: {', '.join(DATASETS)}",
        ) from None
