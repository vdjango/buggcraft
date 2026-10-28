"""Deterministic catalogue responses; all file bytes use loopback HTTP."""
from threading import Event
from copy import deepcopy


class DownloadCatalogueFixtures:
    def __init__(self, files):
        self.files = files
        self.calls = []
        self.failed_sources = set()
        self.version_error = False
        self.project_error = False
        self.many_files = False
        self.slow_kind = None
        self.slow_source = None
        self.slow_started = Event()
        self.release_slow = Event()
        self.hold_project = False
        self.versions_started = Event()
        self.project_started = Event()
        self.release_project = Event()

    def project_row(self, kind, source="Modrinth", index=0):
        return dict(source=source, project_id=f"fixture-{kind}-{index}",
                    title=f"Fixture {kind} {index}", description="Original resource introduction",
                    author="Fixture Author", body="Original resource body",
                    game_versions=["1.21.8"], loaders=["fabric"], categories=["utility"])

    def search(self, query, kind, game="", loader="", source="自动", **kwargs):
        offset = kwargs.get("offset", 0)
        self.calls.append(dict(action="search", query=query, kind=kind, source=source, offset=offset))
        if (query == "slow" and (self.slow_kind is None or kind == self.slow_kind)
                and (self.slow_source is None or source == self.slow_source)):
            self.slow_started.set()
            self.release_slow.wait(10)
        if source in self.failed_sources or query == "error":
            raise ConnectionError(source + " catalogue unavailable: fixture 503")
        if query == "empty":
            return dict(hits=[], has_more=False)
        count = 20 if query == "pages" and offset == 0 else 5 if query == "pages" else 1
        origin = "Modrinth" if source == "自动" else source
        rows = [dict(self.project_row(kind, origin, offset + i), title=query or f"Fixture {kind}")
                for i in range(count)]
        return dict(hits=rows, has_more=query == "pages" and offset == 0)

    def versions(self, project, game="", loader="", kind="mod", **kwargs):
        self.calls.append(dict(action="versions", kind=kind, game=game, loader=loader, offset=kwargs.get("offset", 0)))
        error = self.version_error
        if self.hold_project:
            self.versions_started.set()
            self.release_project.wait(10)
        if error:
            raise ConnectionError("Version files unavailable: fixture 503")
        base = self.files.version(kind)
        if game:
            base["game_versions"] = [game]
        if not self.many_files:
            rows = [base]
        else:
            rows = [dict(deepcopy(base), id=f"file-{i}", name=f"Build {i:02d}",
                         version_number=f"{i:02d}") for i in range(45)]
        return dict(versions=rows, has_more=False) if kwargs.get("page_info") else rows

    def project(self, project, kind="mod"):
        self.calls.append(dict(action="project", kind=kind))
        error = self.project_error
        if self.hold_project:
            self.project_started.set()
            self.release_project.wait(10)
        if error:
            raise ConnectionError("Project details unavailable: fixture 503")
        return dict(project, body="Original resource body", authors=["Fixture Author"],
                    game_versions=["1.21.8"], website_url="")

    def close(self):
        self.release_slow.set()
        self.release_project.set()
