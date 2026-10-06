"""Wraps the "pipeline" action's TRANSCRIBING stage in the GPU lease (ADR
D3). Factored out of supervisor.py to stay under the file size limit, same
trust boundary as a Supervisor method (see generation_supervisor.py for the
pattern this follows): launch/wait need the supervisor's own lock and
process slot, so they take the Supervisor instance itself.

The lease covers `before_transcribe` (which unloads Ollama's models) and the
TRANSCRIBING stage itself, and is released before CORRECTING runs: chat and
CORRECTING/STUDY both call Ollama and may run concurrently once the
transcription is done.
"""

from typing import TYPE_CHECKING

from sbobina.web.gpu_lock import LeaseCancelledError
from sbobina.web.job_models import JobStage, WorkItem

if TYPE_CHECKING:
    from sbobina.web.supervisor import Supervisor

TRANSCRIBING_STAGE_LABEL = "transcribing"


def execute_pipeline_action(supervisor: "Supervisor", item: WorkItem) -> bool:
    """True once TRANSCRIBING (and, if configured, CORRECTING) succeeded."""
    record = supervisor._store.get(job_id=item.job_id)
    if record.config.transcription_engine == "assemblyai":
        # Remote transcription: no GPU to lease and no Ollama model to unload,
        # so chat keeps the GPU while the audio is processed elsewhere.
        if not supervisor._run_stage(item=item, stage=JobStage.TRANSCRIBING):
            return False
        return _run_correction(
            supervisor=supervisor, record_correct=record.config.correct, item=item
        )
    try:
        with supervisor._gpu_arbiter.transcription_lease(
            stage=TRANSCRIBING_STAGE_LABEL
        ):
            if supervisor._before_transcribe is not None:
                supervisor._before_transcribe()
            if not supervisor._run_stage(item=item, stage=JobStage.TRANSCRIBING):
                return False
    except LeaseCancelledError:
        return False
    return _run_correction(
        supervisor=supervisor, record_correct=record.config.correct, item=item
    )


def _run_correction(
    supervisor: "Supervisor", record_correct: bool, item: WorkItem
) -> bool:
    if not record_correct:
        return True
    return supervisor._run_stage(item=item, stage=JobStage.CORRECTING)
