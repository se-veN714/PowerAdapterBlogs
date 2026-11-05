from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from .config import Settings
from .generator import ProfileGenerationError, generate_profile
from .models import ActionRequest, ActionResponse, LogsResponse, ProfileResponse, StatusResponse
from .services import build_status, read_log_tail, start_chain, stop_chain


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings.from_environment()
    app = FastAPI(title="PA-pipe Client", version="0.1.0")
    app.state.settings = config
    app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:8744", "http://localhost:8744"], allow_methods=["GET", "POST"], allow_headers=["*"])
    static_dir = Path(__file__).parent / "static"

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/status", response_model=StatusResponse)
    def status() -> StatusResponse:
        return build_status(config)

    @app.get("/api/logs", response_model=LogsResponse)
    def logs(lines: int = Query(default=200, ge=1, le=500)) -> LogsResponse:
        return LogsResponse(path=str(config.log_file), lines=read_log_tail(config, lines))

    @app.post("/api/actions/{action}", response_model=ActionResponse)
    def action(action: Literal["start", "stop", "restart"], request: ActionRequest | None = None) -> ActionResponse:
        try:
            if action == "start":
                start_chain(config, bool(request and request.restart_clash))
                message = "已请求启动 wstunnel 和 Clash Party"
            elif action == "stop":
                stop_chain(config)
                message = "已请求停止 wstunnel 转发"
            else:
                stop_chain(config)
                start_chain(config, bool(request and request.restart_clash))
                message = "已请求重启 PA-pipe 链路"
        except (OSError, RuntimeError, TimeoutError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return ActionResponse(action=action, accepted=True, message=message)

    @app.post("/api/profile", response_model=ProfileResponse)
    def profile() -> ProfileResponse:
        try:
            target, contract = generate_profile(config)
        except (OSError, ProfileGenerationError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return ProfileResponse(filename=target.name, path=str(target), download_url=f"/api/profile/download/{target.name}", contract=contract)

    @app.get("/api/profile/download/{filename}")
    def profile_download(filename: str) -> FileResponse:
        if Path(filename).name != filename or not filename.endswith(".yaml"):
            raise HTTPException(status_code=400, detail="非法配置文件名")
        target = (config.generated_dir / filename).resolve()
        if config.generated_dir.resolve() not in target.parents or not target.is_file():
            raise HTTPException(status_code=404, detail="配置文件不存在")
        return FileResponse(target, filename=target.name, media_type="application/yaml")

    @app.get("/api/stream")
    async def stream():
        async def events():
            last_signature = None
            for _ in range(600):
                snapshot = {"status": build_status(config).model_dump(mode="json"), "logs": read_log_tail(config, 120)}
                signature = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
                if signature != last_signature:
                    last_signature = signature
                    yield f"event: state\ndata: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
                else:
                    yield ": keep-alive\n\n"
                await asyncio.sleep(1)
        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/{path:path}", include_in_schema=False)
    def static_files(path: str) -> FileResponse:
        candidate = (static_dir / path).resolve()
        if candidate.is_file() and static_dir.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(static_dir / "index.html")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = Settings.from_environment()
    uvicorn.run(app, host=settings.host, port=settings.port)
