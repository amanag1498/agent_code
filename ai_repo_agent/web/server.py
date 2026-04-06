"""FastAPI server for AI Repo Analyst."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from dataclasses import asdict, is_dataclass
from pathlib import Path
import platform
import subprocess
import threading
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

from ai_repo_agent.core.logging_config import get_memory_log_handler, set_logging_level
from ai_repo_agent.core.models import AppSettings
from ai_repo_agent.llm.factory import create_provider
from ai_repo_agent.reports.generator import ReportGenerator
from ai_repo_agent.services.app_context import AppContext
from ai_repo_agent.services.chat_orchestrator import ChatOrchestrator
from ai_repo_agent.services.compare_orchestrator import CompareOrchestrator
from ai_repo_agent.services.patch_orchestrator import PatchOrchestrator
from ai_repo_agent.services.precommit_service import PreCommitService
from ai_repo_agent.services.scan_orchestrator import ScanOrchestrator

LOGGER = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))


class ScanRequest(BaseModel):
    path: str


class ChatRequest(BaseModel):
    repo_id: int
    snapshot_id: int
    question: str


class PatchRequest(BaseModel):
    repo_path: str
    snapshot_id: int
    finding_id: int


class SettingsRequest(BaseModel):
    llm_provider: str
    llm_api_key: str
    llm_model: str
    llm_base_url: str
    analyzer_backend: str
    lsp_enabled: bool
    llm_timeout_seconds: int
    llm_retry_count: int
    llm_max_findings_per_scan: int
    embedding_chunk_lines: int
    watch_mode_enabled: bool
    logging_level: str


class PrecommitRequest(BaseModel):
    repo_path: str


@dataclass(slots=True)
class ScanJob:
    job_id: str
    path: str
    status: str = "queued"
    stage: str = "Queued"
    progress: int = 0
    error: str | None = None
    snapshot_payload: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


def create_app() -> FastAPI:
    """Create the FastAPI application."""
    context = AppContext("ai_repo_analyst.db")
    app = FastAPI(title="AI Repo Analyst", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.context = context
    app.state.log_handler = get_memory_log_handler()
    app.state.scan_jobs: dict[str, ScanJob] = {}
    app.state.scan_jobs_lock = threading.Lock()
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(request, "index.html", {"request": request})

    @app.get("/api/bootstrap")
    async def bootstrap() -> JSONResponse:
        payload = {
            "repositories": [_serialize(repo) for repo in context.repositories.list_all()],
            "settings": _serialize(context.settings.load()),
            "logs": app.state.log_handler.get_entries()[-100:],
        }
        return JSONResponse(payload)

    @app.get("/api/repositories")
    async def repositories() -> JSONResponse:
        return JSONResponse({"repositories": [_serialize(repo) for repo in context.repositories.list_all()]})

    @app.post("/api/scan")
    async def scan_repo(request: ScanRequest) -> JSONResponse:
        job_id = f"scan-{int(time.time() * 1000)}"
        job = ScanJob(job_id=job_id, path=request.path)
        with app.state.scan_jobs_lock:
            app.state.scan_jobs[job_id] = job
        worker = threading.Thread(
            target=_run_scan_job,
            args=(app, context.settings.load().database_path, job_id, request.path),
            daemon=True,
        )
        worker.start()
        return JSONResponse({"job_id": job_id, "status": job.status, "stage": job.stage, "progress": job.progress})

    @app.get("/api/scan-jobs/{job_id}")
    async def scan_job_status(job_id: str) -> JSONResponse:
        with app.state.scan_jobs_lock:
            job = app.state.scan_jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Scan job not found.")
        payload = {
            "job_id": job.job_id,
            "path": job.path,
            "status": job.status,
            "stage": job.stage,
            "progress": job.progress,
            "error": job.error,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "result": job.snapshot_payload,
        }
        return JSONResponse(payload)

    @app.get("/api/pick-folder")
    async def pick_folder() -> JSONResponse:
        try:
            path = _pick_folder_path()
        except RuntimeError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
        return JSONResponse({"path": path})

    @app.get("/api/repositories/{repo_id}/latest")
    async def repo_latest(repo_id: int) -> JSONResponse:
        snapshot = context.snapshots.latest_for_repo(repo_id)
        if not snapshot:
            raise HTTPException(status_code=404, detail="No snapshot found for repository.")
        return JSONResponse(_snapshot_payload(context, repo_id, snapshot.id or 0))

    @app.get("/api/repositories/{repo_id}/compare")
    async def repo_compare(repo_id: int) -> JSONResponse:
        compare = CompareOrchestrator(context.snapshots, context.findings, context.dependencies, context.files, context.symbols).compare_latest(repo_id)
        return JSONResponse({"compare": _serialize(compare) if compare else None})

    @app.get("/api/repositories/{repo_id}/tree")
    async def repo_tree(repo_id: int) -> JSONResponse:
        latest = context.snapshots.latest_for_repo(repo_id)
        if not latest:
            raise HTTPException(status_code=404, detail="No snapshot available.")
        compare = CompareOrchestrator(context.snapshots, context.findings, context.dependencies, context.files, context.symbols).compare_latest(repo_id)
        files = context.files.list_for_repo(repo_id)
        return JSONResponse(
            {
                "tree": _build_tree(files, set(compare.changed_files if compare else [])),
                "changed_files": compare.changed_files if compare else [],
            }
        )

    @app.get("/api/repositories/{repo_id}/file")
    async def repo_file(repo_id: int, path: str) -> JSONResponse:
        repo = context.repositories.get_by_id(repo_id)
        full_path = Path(repo.path) / path
        if not full_path.exists():
            raise HTTPException(status_code=404, detail="File not found.")
        if full_path.is_dir():
            return JSONResponse({"path": path, "type": "directory", "content": ""})
        content = full_path.read_text(encoding="utf-8", errors="ignore")
        return JSONResponse({"path": path, "type": "file", "content": content[:12000]})

    @app.post("/api/chat")
    async def repo_chat(request: ChatRequest) -> JSONResponse:
        answer = ChatOrchestrator(context.chat, context.embeddings, context.reviews, _provider(context)).ask(
            request.repo_id,
            request.snapshot_id,
            request.question,
        )
        return JSONResponse({"answer": answer})

    @app.post("/api/patch")
    async def repo_patch(request: PatchRequest) -> JSONResponse:
        patch = PatchOrchestrator(
            context.findings,
            context.embeddings,
            context.symbols,
            context.reviews,
            context.patches,
            _provider(context),
            context.settings.load(),
        ).suggest(request.repo_path, request.snapshot_id, request.finding_id)
        return JSONResponse({"patch": patch})

    @app.post("/api/settings")
    async def save_settings(request: SettingsRequest) -> JSONResponse:
        current = context.settings.load()
        settings = AppSettings(
            database_path=current.database_path,
            llm_provider=request.llm_provider,
            llm_api_key=request.llm_api_key,
            llm_model=request.llm_model,
            llm_base_url=request.llm_base_url,
            analyzer_backend=request.analyzer_backend,
            lsp_enabled=request.lsp_enabled,
            llm_timeout_seconds=request.llm_timeout_seconds,
            llm_retry_count=request.llm_retry_count,
            llm_max_findings_per_scan=request.llm_max_findings_per_scan,
            embedding_chunk_lines=request.embedding_chunk_lines,
            watch_mode_enabled=request.watch_mode_enabled,
            logging_level=request.logging_level.upper(),
        )
        context.settings.save(settings)
        set_logging_level(settings.logging_level)
        LOGGER.info(
            "Web settings updated: provider=%s model=%s timeout=%s",
            settings.llm_provider,
            settings.llm_model,
            settings.llm_timeout_seconds,
        )
        return JSONResponse({"settings": _serialize(settings)})

    @app.get("/api/logs")
    async def logs() -> JSONResponse:
        return JSONResponse({"logs": app.state.log_handler.get_entries()[-300:]})

    @app.post("/api/precommit")
    async def install_precommit(request: PrecommitRequest) -> JSONResponse:
        hook_path = PrecommitService().install_hook(request.repo_path)
        return JSONResponse({"hook_path": str(hook_path)})

    @app.get("/api/report/{snapshot_id}")
    async def report(snapshot_id: int, format: str = "json"):
        snapshot = context.snapshots.get(snapshot_id)
        repo = context.repositories.get_by_id(snapshot.repo_id)
        findings = context.findings.list_for_snapshot(snapshot_id)
        compare = CompareOrchestrator(context.snapshots, context.findings, context.dependencies, context.files, context.symbols).compare_latest(repo.id or 0)
        reviews = [dict(row) for row in context.reviews.list_for_snapshot(snapshot_id)]
        generator = ReportGenerator()
        payload = generator.build_payload(repo, snapshot, findings, compare, reviews)
        export_dir = Path(repo.path)
        if format == "json":
            target = export_dir / f"repo_report_{snapshot_id}.json"
            generator.export_json(target, payload)
            return FileResponse(target)
        if format == "html":
            target = export_dir / f"repo_report_{snapshot_id}.html"
            generator.export_html(target, payload)
            return FileResponse(target)
        target = export_dir / f"repo_report_{snapshot_id}.md"
        generator.export_markdown(target, payload)
        return FileResponse(target)

    return app


def _provider(context: AppContext):
    return create_provider(context.settings.load())


def _run_scan_job(app: FastAPI, database_path: str, job_id: str, path: str) -> None:
    job_context = AppContext(database_path)

    def update(stage: str, progress: int) -> None:
        with app.state.scan_jobs_lock:
            job = app.state.scan_jobs.get(job_id)
            if not job:
                return
            job.status = "running"
            job.stage = stage
            job.progress = progress
            job.updated_at = time.time()

    try:
        update("Loading repository context", 5)
        orchestrator = _scan_orchestrator(job_context)
        result = orchestrator.scan(path, progress_callback=update)
        snapshot_id = result.snapshot.id or 0
        repo = job_context.repositories.get_by_id(result.snapshot.repo_id)
        payload = _snapshot_payload(job_context, repo.id or 0, snapshot_id)
        with app.state.scan_jobs_lock:
            job = app.state.scan_jobs.get(job_id)
            if job:
                job.status = "completed"
                job.stage = "Scan complete"
                job.progress = 100
                job.snapshot_payload = payload
                job.updated_at = time.time()
    except Exception as exc:
        LOGGER.exception("Background scan job failed for %s", path)
        with app.state.scan_jobs_lock:
            job = app.state.scan_jobs.get(job_id)
            if job:
                job.status = "failed"
                job.stage = "Scan failed"
                job.progress = 100
                job.error = str(exc)
                job.updated_at = time.time()
    finally:
        job_context.connection.close()


def _scan_orchestrator(context: AppContext) -> ScanOrchestrator:
    return ScanOrchestrator(
        context.repositories,
        context.snapshots,
        context.files,
        context.dependencies,
        context.symbols,
        context.embeddings,
        context.findings,
        context.reviews,
        context.scan_runs,
        context.settings.load(),
    )


def _snapshot_payload(context: AppContext, repo_id: int, snapshot_id: int) -> dict[str, Any]:
    snapshot = context.snapshots.get(snapshot_id)
    repo = context.repositories.get_by_id(repo_id)
    findings = context.findings.list_for_snapshot(snapshot_id)
    compare = CompareOrchestrator(context.snapshots, context.findings, context.dependencies, context.files, context.symbols).compare_latest(repo_id)
    symbols = context.symbols.list_for_snapshot(snapshot_id)
    chunks = context.embeddings.list_for_snapshot(snapshot_id)
    patches = context.patches.list_for_snapshot(snapshot_id)
    reviews = [dict(row) for row in context.reviews.list_for_snapshot(snapshot_id)]
    scan_runs = [
        dict(row)
        for row in context.connection.execute(
            "SELECT scanner_name, status, message, finished_at FROM scan_runs WHERE snapshot_id = ? ORDER BY id DESC",
            (snapshot_id,),
        ).fetchall()
    ]
    scan_metadata = _safe_json(snapshot.scan_metadata)
    files = context.files.list_for_repo(repo_id)
    return {
        "repository": _serialize(repo),
        "snapshot": _serialize(snapshot),
        "findings": [_serialize(finding) for finding in findings],
        "compare": _serialize(compare) if compare else None,
        "symbols": [_serialize(symbol) for symbol in symbols[:250]],
        "chunks": [_serialize(chunk) for chunk in chunks[:60]],
        "patches": [_serialize(patch) for patch in patches[:50]],
        "reviews": reviews,
        "scan_runs": scan_runs,
        "scan_metadata": scan_metadata,
        "files": [_serialize(file_record) for file_record in files],
    }


def _serialize(value: Any) -> Any:
    if value is None:
        return None
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _safe_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except Exception:
        return {}


def _build_tree(files: list[Any], changed_paths: set[str]) -> list[dict[str, Any]]:
    root: dict[str, Any] = {}
    for file_record in files:
        cursor = root
        parts = file_record.path.split("/")
        path_accumulator = ""
        for index, part in enumerate(parts):
            path_accumulator = f"{path_accumulator}/{part}" if path_accumulator else part
            is_leaf = index == len(parts) - 1
            node = cursor.setdefault(
                part,
                {
                    "name": part,
                    "path": path_accumulator,
                    "children": {},
                    "language": file_record.language if is_leaf else "",
                    "size": file_record.size if is_leaf else 0,
                    "changed": False,
                    "leaf": is_leaf,
                },
            )
            node["changed"] = node["changed"] or path_accumulator in changed_paths or any(
                changed_path.startswith(f"{path_accumulator}/") for changed_path in changed_paths
            )
            cursor = node["children"]
    return _normalize_tree(root)


def _normalize_tree(tree: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = []
    for key in sorted(tree):
        node = tree[key]
        nodes.append(
            {
                "name": node["name"],
                "path": node["path"],
                "language": node["language"],
                "size": node["size"],
                "changed": node["changed"],
                "leaf": node["leaf"],
                "children": _normalize_tree(node["children"]),
            }
        )
    return nodes


def _pick_folder_path() -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            selected = filedialog.askdirectory(title="Select repository or folder")
            return selected or ""
        finally:
            root.destroy()
    except ModuleNotFoundError:
        pass

    if platform.system() == "Darwin":
        script = 'POSIX path of (choose folder with prompt "Select repository or folder")'
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        if "User canceled" in result.stderr:
            return ""
        raise RuntimeError(f"macOS folder picker failed: {result.stderr.strip() or 'unknown error'}")

    if platform.system() == "Windows":
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$dialog.Description = 'Select repository or folder'; "
            "$dialog.ShowNewFolderButton = $false; "
            "$result = $dialog.ShowDialog(); "
            "if ($result -eq [System.Windows.Forms.DialogResult]::OK) { "
            "  [Console]::Write($dialog.SelectedPath) "
            "}"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        raise RuntimeError(f"Windows folder picker failed: {result.stderr.strip() or 'unknown error'}")

    raise RuntimeError(
        "Native folder picker is unavailable in this Python environment. Enter the path manually in the scan field."
    )
