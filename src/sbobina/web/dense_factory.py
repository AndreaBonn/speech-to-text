import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from threading import Lock

from ollama import Client

from sbobina.ollama_embed import EmbeddingUnavailableError, ModelStatus, model_status
from sbobina.settings import Settings
from sbobina.web.dense_retrieval import DenseRanker, RetrievalReport
from sbobina.web.vector_store import VectorStore

logger = logging.getLogger(__name__)
_BUILD_LOCK = Lock()
_WARNING_LOCK = Lock()
_VECTORS: dict[Path, VectorStore] = {}
_RANKERS: dict[tuple[Path, str, str], "DenseRuntime"] = {}
_DIGESTS: dict[tuple[Path, str, str], str] = {}
_LAST_CHECKED: dict[tuple[Path, str, str], float] = {}
_clock: Callable[[], float] = time.monotonic
_WARNED: set[str] = set()
_QUERY_WARNING = "Dense query unavailable: model=%s reason=%s"
VECTOR_FILENAME = "vectors.sqlite3"
RECHECK_INTERVAL_S = 60.0


def vector_store_for_process(*, data_dir: Path) -> VectorStore:
    """Reuse the process's vector store independently of semantic search settings."""
    path = data_dir.resolve() / VECTOR_FILENAME
    with _BUILD_LOCK:
        if path not in _VECTORS:
            _VECTORS[path] = VectorStore(path=path)
        return _VECTORS[path]


def _first_warning(reason: str) -> bool:
    with _WARNING_LOCK:
        if reason in _WARNED:
            return False
        _WARNED.add(reason)
        return True


class _QueryWarningFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # The existing ranker logs before returning its report. Share that warning
        # with the call-site reporter, leaving all unrelated log records intact.
        if record.msg != _QUERY_WARNING:
            return True
        args = record.args
        if isinstance(args, tuple) and len(args) == 2 and isinstance(args[1], str):
            return _first_warning(reason=args[1])
        return True


logging.getLogger("sbobina.web.dense_retrieval").addFilter(_QueryWarningFilter())


@dataclass(frozen=True, kw_only=True)
class DenseRuntime:
    ranker: DenseRanker | None = None
    reason: str | None = "disabled"
    model: str = ""

    def metadata(self, report: RetrievalReport) -> dict[str, object]:
        if self.ranker is None:
            report = replace(report, reason=self.reason)
        if (
            report.mode == "bm25"
            and report.reason not in (None, "disabled")
            and _first_warning(reason=report.reason)
        ):
            logger.warning(
                "Dense retrieval unavailable: model=%s reason=%s",
                self.model,
                report.reason,
            )
        payload: dict[str, object] = {"mode": report.mode, "reason": report.reason}
        if report.coverage is not None:
            payload["coverage"] = asdict(report.coverage)
        return payload


def dense_for_process(settings: Settings, data_dir: Path) -> DenseRuntime:
    """Reuse a ranker per configuration and a vector store per data directory.

    Parameters
    ----------
    settings : Settings
        Effective runtime settings; disabled search performs no I/O.
    data_dir : Path
        Actual application directory, including any web entry-point override.
    """
    if not settings.semantic_search:
        return DenseRuntime(model=settings.embedding_model)
    path = data_dir.resolve() / VECTOR_FILENAME
    key = (path, settings.ollama_host, settings.embedding_model)
    with _BUILD_LOCK:
        if key in _RANKERS and _clock() - _LAST_CHECKED[key] < RECHECK_INTERVAL_S:
            return _RANKERS[key]
        return _build(settings=settings, path=path, key=key)


def _build(settings: Settings, path: Path, key: tuple[Path, str, str]) -> DenseRuntime:
    """Check model identity and build or refresh the runtime under the build lock.

    Parameters
    ----------
    settings : Settings
        Effective embedding configuration.
    path : Path
        Shared vector store location.
    key : tuple[Path, str, str]
        Cache identity for the store, host and model.
    """
    try:
        status = model_status(
            host=settings.ollama_host,
            model=settings.embedding_model,
            timeout_s=settings.embedding_timeout_s,
        )
    except EmbeddingUnavailableError as error:
        if key in _RANKERS:
            # A transient status failure must not discard a working ranker.
            _LAST_CHECKED[key] = _clock()
            return _RANKERS[key]
        return DenseRuntime(reason=error.reason, model=settings.embedding_model)
    _LAST_CHECKED[key] = _clock()
    if key in _RANKERS and _DIGESTS[key] == status.digest:
        return _RANKERS[key]
    return _create_runtime(settings=settings, path=path, key=key, status=status)


def _create_runtime(
    settings: Settings,
    path: Path,
    key: tuple[Path, str, str],
    status: ModelStatus,
) -> DenseRuntime:
    if path not in _VECTORS:
        _VECTORS[path] = VectorStore(path=path)
    runtime = DenseRuntime(
        ranker=DenseRanker(
            vectors=_VECTORS[path],
            model=settings.embedding_model,
            status=status,
            client=Client(
                host=settings.ollama_host,
                timeout=settings.embedding_timeout_s,
            ),
        ),
        reason=None,
        model=settings.embedding_model,
    )
    _RANKERS[key] = runtime
    _DIGESTS[key] = status.digest
    return runtime
