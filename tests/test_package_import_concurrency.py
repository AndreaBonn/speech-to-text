from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from zipfile import ZipFile

import pytest
from package_import_fixtures import IMPORT_TIME, make_package

from sbobina import package_import
from sbobina.package_import import ImportResult
from sbobina.package_import_load import LoadedPackage, load_package
from sbobina.package_models import Manifest


def test_import_package_concurrent_reimports_keep_distinct_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = make_package(directory=tmp_path)
    ready = Barrier(parties=2)

    def synchronized_load(archive: ZipFile, manifest: Manifest) -> LoadedPackage:
        loaded = load_package(archive=archive, manifest=manifest)
        ready.wait(timeout=5)
        return loaded

    def run_import() -> ImportResult:
        return package_import.import_package(
            source=source, data_dir=tmp_path / "destination", now=IMPORT_TIME
        )

    monkeypatch.setattr(package_import, "load_package", synchronized_load)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run_import) for _ in range(2)]
        results = [future.result(timeout=10) for future in futures]
    assert len({result.course.id for result in results}) == 2
    assert len({result.course.key for result in results}) == 2
    assert sum(result.warning is not None for result in results) == 1
