"""Closed command lexicon. The model may propose one of these; the server validates it."""

from __future__ import annotations

import uuid

from neuro_engine.acquisition.service import AcquisitionState
from neuro_engine.analysis.band_power import Finding, FindingStore, Marker
from neuro_engine.assistant.session import SessionController, SessionError

POSTERIOR = ("O1", "O2", "Pz", "P3", "P4")
DISPLAY_MODES = ("pial", "white", "inflated", "holographic", "grid")
DISPLAY_PHRASES = {
    "show pial": "pial",
    "show the pial surface": "pial",
    "show white matter": "white",
    "show white matter boundary": "white",
    "show the white matter boundary": "white",
    "show inflated": "inflated",
    "show the inflated surface": "inflated",
    "show holographic": "holographic",
    "show the wireframe": "holographic",
    "show grid": "grid",
}
INTENTS = (
    "emphasize_channels",
    "seek_to_finding",
    "add_marker",
    "lock_baseline",
    "set_display_mode",
    "answer",
    "clarify",
)


def normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def parse_text(text: str) -> dict[str, object] | None:
    phrase = normalize(text)
    if phrase in {"show the rear channels", "show rear channels", "show the posterior channels"}:
        return {"intent": "emphasize_channels", "group": "posterior"}
    if phrase in {"show me that segment", "show that segment", "jump to that segment"}:
        return {"intent": "seek_to_finding"}
    if phrase in {"mark this moment", "mark this"}:
        return {"intent": "add_marker", "markerLabel": "marked moment"}
    if phrase in {"lock baseline", "use this as baseline"}:
        return {"intent": "lock_baseline"}
    if "which channels changed most" in phrase:
        return {"intent": "answer", "question": "changed-most"}
    if phrase in DISPLAY_PHRASES:
        return {"intent": "set_display_mode", "displayMode": DISPLAY_PHRASES[phrase]}
    return None


def current_labels(session: SessionController) -> list[str]:
    stream = session.service.current_stream
    if stream is None:
        return []
    return [channel.label for channel in stream.descriptor.channels]


def _result(
    session: SessionController,
    *,
    ok: bool,
    intent: str,
    message: str,
    channels: list[str] | None = None,
    primary: str | None = None,
    finding_ids: list[str] | None = None,
    display_mode: str | None = None,
    seek: int | None = None,
) -> dict[str, object]:
    stream = session.service.current_stream
    text = message.strip()[:400] or "I could not complete that."
    return {
        "type": "assistant.intent-result",
        "schemaVersion": 1,
        "ok": ok,
        "intent": intent,
        "message": text,
        "channels": channels or [],
        "primaryChannel": primary,
        "findingIds": finding_ids or [],
        "displayMode": display_mode,
        "seekSampleIndex": seek,
        "sessionGeneration": session.generation,
        "streamId": None if stream is None else stream.stream_id,
    }


def _latest_finding(findings: list[Finding], finding_id: str | None) -> Finding | None | str:
    if finding_id is not None:
        match = [item for item in findings if item.finding_id == finding_id]
        return match[0] if len(match) == 1 else "missing"
    if not findings:
        return None
    newest = max(item.last_sample_index for item in findings)
    tied = [item for item in findings if item.last_sample_index == newest]
    ranges = {(item.first_sample_index, item.last_sample_index) for item in tied}
    if len(ranges) > 1:
        return "ambiguous"
    return tied[0]


async def execute(
    proposal: dict[str, object],
    session: SessionController,
    store: FindingStore,
    *,
    requested_generation: int | None,
) -> dict[str, object]:
    if requested_generation is not None and requested_generation != session.generation:
        return _result(
            session,
            ok=False,
            intent="cancelled",
            message="Cancelled because the session changed. Ask again if you still want that.",
        )
    intent = str(proposal.get("intent") or "clarify")
    if intent not in INTENTS:
        return _result(session, ok=False, intent="clarify", message="That command is not one I can run.")
    try:
        if intent == "emphasize_channels":
            return _emphasize(proposal, session)
        if intent == "seek_to_finding":
            return await _seek(proposal, session, store)
        if intent == "add_marker":
            return _mark(proposal, session, store)
        if intent == "lock_baseline":
            return _lock(session)
        if intent == "set_display_mode":
            return _display(proposal, session)
        if intent == "answer":
            return _answer(proposal, session, store)
        clarification = str(proposal.get("clarification") or "Which segment or channels do you mean?")
        return _result(session, ok=False, intent="clarify", message=clarification[:400])
    except SessionError as exc:
        return _result(session, ok=False, intent="clarify", message=exc.message)


def _emphasize(proposal: dict[str, object], session: SessionController) -> dict[str, object]:
    labels = current_labels(session)
    requested = proposal.get("channels")
    if isinstance(requested, list) and requested:
        chosen = [str(label) for label in requested]
        unknown = [label for label in chosen if label not in labels]
        if unknown:
            return _result(
                session,
                ok=False,
                intent="clarify",
                message=f"Those channels are not in this stream: {', '.join(unknown)}.",
            )
    else:
        chosen = [label for label in POSTERIOR if label in labels]
        if not chosen:
            return _result(
                session,
                ok=False,
                intent="clarify",
                message="This montage has none of the posterior channels O1, O2, Pz, P3, and P4.",
            )
    return _result(
        session,
        ok=True,
        intent="emphasize_channels",
        message=f"Selected {', '.join(chosen)}.",
        channels=chosen,
        primary=chosen[0],
    )


async def _seek(proposal: dict[str, object], session: SessionController, store: FindingStore) -> dict[str, object]:
    finding_id = proposal.get("findingId")
    if finding_id is not None and not isinstance(finding_id, str):
        finding_id = None
    current = store.query(generation=session.generation)
    # A replay of the same recording may cite the previous generation.
    if session.recording_id is not None:
        same_recording = [
            item
            for item in store.findings
            if item.recording_id == session.recording_id and item.quality == "good"
        ]
    else:
        same_recording = [item for item in current if item.quality == "good"]
    if session.source != "replay" or session.recording_id is None:
        return _result(
            session,
            ok=False,
            intent="clarify",
            message="That segment is not open for replay. The live synthetic stream cannot jump backward.",
        )
    picked = _latest_finding(same_recording or current, finding_id if isinstance(finding_id, str) else None)
    if picked == "ambiguous":
        return _result(
            session,
            ok=False,
            intent="clarify",
            message="More than one recent segment matches. Name the finding you want.",
        )
    if picked in (None, "missing") or not isinstance(picked, Finding):
        return _result(
            session,
            ok=False,
            intent="clarify",
            message="I don't have a qualified segment to show in this session.",
        )
    if picked.recording_id not in (None, session.recording_id):
        return _result(
            session,
            ok=False,
            intent="clarify",
            message="That finding belongs to a different recording, so I did not seek.",
            finding_ids=[picked.finding_id],
        )
    await session.seek(picked.first_sample_index)
    return _result(
        session,
        ok=True,
        intent="seek_to_finding",
        message=(
            f"Opened samples {picked.first_sample_index}–{picked.last_sample_index} "
            f"on a new stream. The previous trace is no longer the live window."
        ),
        channels=[channel.label for channel in picked.channels],
        primary=picked.channels[0].label,
        finding_ids=[picked.finding_id],
        seek=picked.first_sample_index,
    )


def _mark(proposal: dict[str, object], session: SessionController, store: FindingStore) -> dict[str, object]:
    stream = session.service.current_stream
    newest = session.analyzer.newest_index
    if stream is None or newest is None:
        return _result(session, ok=False, intent="clarify", message="There is no sample to mark yet.")
    label = str(proposal.get("markerLabel") or "marked moment")[:128]
    marker = Marker(
        marker_id=uuid.uuid4().hex,
        session_generation=session.generation,
        stream_id=stream.stream_id,
        sample_index=newest,
        label=label,
    )
    store.add_marker(marker)
    return _result(session, ok=True, intent="add_marker", message=f"Marked sample {newest} as {label}.")


def _lock(session: SessionController) -> dict[str, object]:
    if session.analyzer.lock_baseline():
        return _result(session, ok=True, intent="lock_baseline", message="Locked the current clean windows as the baseline.")
    return _result(
        session,
        ok=False,
        intent="clarify",
        message="Not enough clean data to lock a baseline yet.",
    )


def _display(proposal: dict[str, object], session: SessionController) -> dict[str, object]:
    mode = proposal.get("displayMode")
    if mode not in DISPLAY_MODES:
        return _result(session, ok=False, intent="clarify", message="That is not one of the display modes.")
    names = {
        "pial": "Pial",
        "white": "White matter boundary",
        "inflated": "Inflated",
        "holographic": "Holographic",
        "grid": "Grid",
    }
    return _result(
        session,
        ok=True,
        intent="set_display_mode",
        message=f"Showing {names[str(mode)]}.",
        display_mode=str(mode),
    )


def _answer(proposal: dict[str, object], session: SessionController, store: FindingStore) -> dict[str, object]:
    question = proposal.get("question")
    supplied = proposal.get("findingIds")
    findings = [item for item in store.query(generation=session.generation) if item.quality == "good" and item.method == "band-power"]
    if isinstance(supplied, list) and supplied:
        allowed = {item.finding_id for item in findings}
        if not {str(item) for item in supplied} <= allowed:
            return _result(
                session,
                ok=False,
                intent="answer",
                message="I could not tie that claim to a current finding.",
            )
        findings = [item for item in findings if item.finding_id in set(map(str, supplied))]
    if question == "changed-most" or not proposal.get("answer"):
        if not findings:
            evidence = session.analyzer.evidence
            if evidence in {"insufficient", "warming", "waiting", "baseline-unlocked"}:
                message = "I don't have a qualified change in this session. The evidence is insufficient or the baseline is not locked yet."
            else:
                message = "I don't have a qualified change in this session."
            return _result(session, ok=True, intent="answer", message=message)
        ranked: list[tuple[float, Finding, str]] = []
        for finding in findings:
            for channel in finding.channels:
                ranked.append((abs(channel.change_db), finding, channel.label))
        ranked.sort(key=lambda item: item[0], reverse=True)
        top = ranked[0][0]
        chosen = [(change, finding, label) for change, finding, label in ranked if change >= top - 0.05]
        ids = list(dict.fromkeys(finding.finding_id for _, finding, _ in chosen))
        bits = []
        for _, finding, label in chosen:
            channel = next(item for item in finding.channels if item.label == label)
            bits.append(
                f"{label} {channel.change_db:+.1f} dB ({finding.band}, samples {finding.first_sample_index}–{finding.last_sample_index})"
            )
        return _result(
            session,
            ok=True,
            intent="answer",
            message="The largest changes I can cite are " + "; ".join(bits) + ".",
            channels=[label for _, _, label in chosen],
            primary=chosen[0][2],
            finding_ids=ids,
        )
    text = str(proposal.get("answer") or "")
    ids = [str(item) for item in supplied] if isinstance(supplied, list) else []
    return _result(session, ok=True, intent="answer", message=text[:400] or "I don't have more to add from the current findings.", finding_ids=ids)


def stream_running(session: SessionController) -> bool:
    return session.service.state is AcquisitionState.STREAMING
