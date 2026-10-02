from pathlib import Path

from sbobina import study_command
from sbobina.render import RenderOptions
from sbobina.settings import Settings
from sbobina.study_pipeline import (
    StudyOptions,
    StudyProgress,
    generate_study,
    source_revision,
)
from sbobina.study_render import save_study


def generate_study_files(
    job_dir: Path, config: Settings, on_progress: StudyProgress
) -> Path:
    paths = study_command.select_study_paths(path=job_dir / "audio.json")
    content = paths.source.read_bytes().decode("utf-8")
    transcript = study_command.TRANSCRIPT_ADAPTER.validate_json(content)
    on_progress(0, 1)
    result = generate_study(
        transcript=transcript,
        chat=study_command._prepare_chat(
            model=config.ollama_model, host=config.ollama_host
        ),
        options=StudyOptions(
            model=config.ollama_model,
            block_words=config.study_block_words,
            num_predict=config.study_num_predict,
            source_variant=paths.variant,
            source_revision=source_revision(content=content),
        ),
        on_progress=on_progress,
    )
    save_study(
        result=result,
        json_path=paths.output,
        transcript=transcript,
        options=_render_options(config=config),
    )
    return paths.output


def _render_options(config: Settings) -> RenderOptions:
    return RenderOptions(
        uncertain_threshold=config.uncertain_threshold,
        paragraph_gap_s=config.paragraph_gap_s,
        paragraph_max_s=config.paragraph_max_s,
    )
