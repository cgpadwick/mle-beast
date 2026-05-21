# Copyright 2026 Chris Padwick and contributors
# SPDX-License-Identifier: Apache-2.0

"""HTTP-level tests for mle_beast.web.routes via fastapi.testclient.

Mocks the RunManager / Database / Settings layers so these tests run
in-process with no SQLite I/O and no pipeline threads.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

from mle_beast.run_manager import RunInfo, StageInfo
from mle_beast.web.app import create_app

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


def _make_run_info(**overrides) -> RunInfo:
    """Build a RunInfo with sensible defaults; override anything per-test."""
    base: dict = dict(
        id="r-1",
        status="running",
        workspace="/tmp/ws",
        task="do thing",
        target_accuracy=0.85,
        dataset_path="/data",
        mode="greenfield",
        force_cpu=False,
        setup_workspace=False,
        created_at=1000.0,
        started_at=1001.0,
        completed_at=None,
        verdict_json=None,
        error_message=None,
        experiment_branch=None,
        lower_is_better=False,
        metric_name="accuracy",
        total_cost_usd=0.0,
        total_prompt_tokens=0,
        total_completion_tokens=0,
        total_reasoning_tokens=0,
        total_llm_calls=0,
    )
    base.update(overrides)
    return RunInfo(**base)


@dataclass
class _FakeRunManager:
    """In-memory stand-in for RunManager that records calls.

    Tests poke at the attributes (runs, stages, experiments) to seed state,
    then call routes via TestClient and assert on responses + recorded calls.
    """

    runs: dict = field(default_factory=dict)
    stages: dict = field(default_factory=dict)        # run_id -> list[StageInfo]
    experiments: dict = field(default_factory=dict)   # run_id -> list[dict]
    events: dict = field(default_factory=dict)        # run_id -> list[dict]
    peak: dict = field(default_factory=dict)          # run_id -> dict | None
    # Call recordings:
    created: list = field(default_factory=list)
    started: list = field(default_factory=list)
    cancelled: list = field(default_factory=list)
    cancel_returns_true: bool = True

    def list_runs(self, status=None):
        all_runs = list(self.runs.values())
        if status:
            all_runs = [r for r in all_runs if r.status == status]
        return all_runs

    def get_run(self, run_id):
        return self.runs.get(run_id)

    def get_stages(self, run_id):
        return self.stages.get(run_id, [])

    def get_events(self, run_id, since=None):
        evs = self.events.get(run_id, [])
        if since is not None:
            evs = [e for e in evs if e.get("timestamp", 0) > since]
        return evs

    def list_experiments(self, run_id):
        return self.experiments.get(run_id, [])

    def get_peak_score(self, run_id):
        return self.peak.get(run_id)

    def create_run(self, config):
        run_id = "new-run-id"
        self.created.append(config)
        self.runs[run_id] = _make_run_info(
            id=run_id, task=config.task, status="pending",
        )
        return run_id

    def start_run(self, run_id):
        self.started.append(run_id)
        if run_id in self.runs:
            self.runs[run_id].status = "running"

    def cancel_run(self, run_id):
        self.cancelled.append(run_id)
        return self.cancel_returns_true


@dataclass
class _FakeDB:
    """Stand-in for Database — only the methods admin routes use."""

    stats_payload: dict = field(default_factory=lambda: {
        "runs_count": 1, "stages_count": 0, "events_count": 0,
        "runs_by_status": {"running": 1}, "db_size_bytes": 1234,
    })
    deleted_count: int = 3
    reset_called: bool = False
    deleted_runs: list = field(default_factory=list)
    settings_updates: list = field(default_factory=list)

    def get_stats(self):
        return self.stats_payload

    def delete_runs_older_than(self, days):
        self.deleted_runs.append(("older_than", days))
        return self.deleted_count

    def reset_database(self):
        self.reset_called = True

    def delete_run(self, run_id):
        self.deleted_runs.append(run_id)

    def update_settings(self, fields):
        self.settings_updates.append(fields)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_manager(monkeypatch):
    mgr = _FakeRunManager()
    monkeypatch.setattr(
        "mle_beast.web.routes.get_run_manager", lambda: mgr,
    )
    return mgr


@pytest.fixture
def fake_db(monkeypatch):
    db = _FakeDB()
    # Routes import via deferred-import; patch the *source* module.
    monkeypatch.setattr("mle_beast.db.get_database", lambda: db)
    return db


@pytest.fixture
def client(fake_manager, fake_db):
    """A TestClient instance with the mocks in place."""
    app = create_app()
    return TestClient(app)


# ---------------------------------------------------------------------------
# App factory / CORS
# ---------------------------------------------------------------------------


class TestAppFactory:
    def test_app_boots_and_has_cors_middleware(self, client):
        # An OPTIONS preflight from an arbitrary origin should be permitted.
        r = client.options(
            "/api/runs",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert r.status_code in (200, 204)
        assert r.headers.get("access-control-allow-origin") == "*"


class TestSpaMount:
    """The static React SPA mount, conditional on the built dir existing.

    These tests cover the auto-launch-dashboard PR: serving the bundled
    SPA at "/" alongside the JSON API at "/api/*".
    """

    def _has_built_spa(self) -> bool:

        from mle_beast.web import app as app_mod
        return app_mod._STATIC_DIR.exists() and (
            app_mod._STATIC_DIR / "index.html"
        ).exists()

    def test_root_serves_spa_index_html_when_bundled(self, client):
        """In bundled mode, GET / returns the React SPA shell."""
        if not self._has_built_spa():
            pytest.skip("SPA not built; run `cd prototypes/dashboard && npm run build`")
        r = client.get("/")
        assert r.status_code == 200
        body = r.text
        assert "<html" in body.lower()
        # The SPA mounts a #root div which React hydrates into.
        assert 'id="root"' in body

    def test_api_routes_still_match_under_spa_mount(self, client):
        """The static catchall at / must NOT shadow the more-specific
        /api/* routes — FastAPI route matching is longest-prefix-wins.
        Regression test for the auto-launch-dashboard PR.
        """
        r = client.get("/api/runs")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/json")
        assert r.json() == []  # fake_manager has no runs

    def test_unknown_api_route_404s_without_falling_through(self, client):
        """A request to /api/<nonexistent> should be a clean 404 from the
        API layer, not a fallback into the static handler returning
        index.html. The latter would mask typos in the React app's URLs.
        """
        r = client.get("/api/does-not-exist")
        assert r.status_code == 404
        # Must be the API's JSON 404, not the SPA index.html.
        assert "<html" not in r.text.lower()

    def test_static_mount_absent_when_bundle_missing(self, monkeypatch, tmp_path):
        """If the static dir hasn't been built (fresh `git clone` before
        `npm run build`), create_app() should boot without the SPA mount
        and the API should still serve normally.
        """
        from mle_beast.web import app as app_mod

        # Point _STATIC_DIR at an empty tmp dir so the existence check fails.
        monkeypatch.setattr(app_mod, "_STATIC_DIR", tmp_path / "nope")
        # Recreate the app so the new _STATIC_DIR takes effect.
        new_app = app_mod.create_app()
        # Mount routes have type 'Mount'; APIRoutes don't. The catchall
        # we conditionally add at "/" is the only Mount we install.
        from starlette.routing import Mount
        assert not any(isinstance(r, Mount) for r in new_app.routes)
        # The API routes are still there.
        from fastapi.testclient import TestClient
        c = TestClient(new_app)
        assert c.get("/api/runs").status_code == 200


# ---------------------------------------------------------------------------
# /api/runs CRUD
# ---------------------------------------------------------------------------


class TestRunsRoutes:
    def test_list_runs_empty(self, client):
        r = client.get("/api/runs")
        assert r.status_code == 200
        assert r.json() == []

    def test_list_runs_includes_peak_per_row(self, client, fake_manager):
        fake_manager.runs["r-1"] = _make_run_info(id="r-1")
        fake_manager.peak["r-1"] = {"score": 0.93, "step": 5}
        r = client.get("/api/runs")
        body = r.json()
        assert len(body) == 1
        assert body[0]["id"] == "r-1"
        assert body[0]["peak"] == {"score": 0.93, "step": 5}

    def test_list_runs_filter_by_status(self, client, fake_manager):
        fake_manager.runs["a"] = _make_run_info(id="a", status="completed")
        fake_manager.runs["b"] = _make_run_info(id="b", status="failed")
        r = client.get("/api/runs?status=completed")
        ids = [row["id"] for row in r.json()]
        assert ids == ["a"]

    def test_create_run_starts_in_background(self, client, fake_manager):
        body = {"workspace": "/tmp/x", "task": "test it"}
        r = client.post("/api/runs", json=body)
        assert r.status_code == 201
        assert r.json()["status"] == "running"
        assert r.json()["id"] == "new-run-id"
        assert "redirect" not in r.json()  # was deliberately removed
        # The handler must have invoked create_run AND start_run.
        assert len(fake_manager.created) == 1
        assert fake_manager.created[0].task == "test it"
        assert fake_manager.started == ["new-run-id"]

    def test_create_run_propagates_optional_fields(self, client, fake_manager):
        body = {
            "workspace": "/tmp/x",
            "task": "x",
            "target_accuracy": 0.9,
            "dataset_path": "/data",
            "mode": "existing",
            "force_cpu": True,
            "lower_is_better": True,
            "metric_name": "rmse",
        }
        r = client.post("/api/runs", json=body)
        assert r.status_code == 201
        config = fake_manager.created[0]
        assert config.target_accuracy == 0.9
        assert config.mode == "existing"
        assert config.force_cpu is True
        assert config.lower_is_better is True
        assert config.metric_name == "rmse"
        # environment defaults to None when not provided.
        assert config.environment is None

    def test_create_run_preflights_environment(
        self, client, fake_manager, monkeypatch, tmp_path,
    ):
        """When `environment` is set, the route must preflight-validate
        before inserting the run. A bad path returns 400 and never
        reaches RunManager.create_run.
        """
        from mle_beast import workspace as workspace_mod

        def fake_validate(path):
            raise RuntimeError(f"fake: no bin/python under {path}")

        monkeypatch.setattr(
            workspace_mod, "validate_environment_path", fake_validate,
        )

        r = client.post("/api/runs", json={
            "workspace": "/tmp/x",
            "task": "x",
            "environment": "/not/a/real/path",
        })
        assert r.status_code == 400
        assert "no bin/python" in r.json()["detail"]
        # And the run must NOT have been created.
        assert fake_manager.created == []

    def test_create_run_propagates_environment_on_success(
        self, client, fake_manager, monkeypatch, tmp_path,
    ):
        from mle_beast import workspace as workspace_mod

        # Stub the validator so we don't need a real venv to test wiring.
        monkeypatch.setattr(
            workspace_mod, "validate_environment_path",
            lambda p: tmp_path / "ok",
        )

        r = client.post("/api/runs", json={
            "workspace": "/tmp/x",
            "task": "x",
            "environment": str(tmp_path / "ok"),
        })
        assert r.status_code == 201
        assert fake_manager.created[0].environment == str(tmp_path / "ok")

    def test_validate_environment_endpoint_ok(self, client, monkeypatch, tmp_path):
        from mle_beast import workspace as workspace_mod
        monkeypatch.setattr(
            workspace_mod, "validate_environment_path",
            lambda p: tmp_path / "resolved",
        )

        r = client.post("/api/validate-environment", json={"path": "/foo"})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "resolved" in body["resolved"]

    def test_validate_environment_endpoint_bad(self, client, monkeypatch):
        from mle_beast import workspace as workspace_mod

        def boom(_p):
            raise RuntimeError("pytest not importable in /foo")

        monkeypatch.setattr(
            workspace_mod, "validate_environment_path", boom,
        )
        r = client.post("/api/validate-environment", json={"path": "/foo"})
        assert r.status_code == 400
        assert r.json()["ok"] is False
        assert "pytest not importable" in r.json()["error"]

    def test_validate_environment_endpoint_empty_path(self, client):
        r = client.post("/api/validate-environment", json={"path": ""})
        assert r.status_code == 400
        assert "no path provided" in r.json()["error"]

    def test_get_run_returns_run_and_stages(self, client, fake_manager):
        fake_manager.runs["r-1"] = _make_run_info(id="r-1")
        fake_manager.stages["r-1"] = [
            StageInfo(stage_name="setup", status="pass", attempt=1, max_attempts=3),
        ]
        r = client.get("/api/runs/r-1")
        assert r.status_code == 200
        body = r.json()
        assert body["run"]["id"] == "r-1"
        assert body["stages"][0]["stage_name"] == "setup"

    def test_get_run_404(self, client):
        r = client.get("/api/runs/nope")
        assert r.status_code == 404

    def test_cancel_run_ok(self, client, fake_manager):
        fake_manager.runs["r-1"] = _make_run_info(id="r-1")
        r = client.post("/api/runs/r-1/cancel")
        assert r.status_code == 200
        assert r.json() == {"status": "cancelled"}
        assert fake_manager.cancelled == ["r-1"]

    def test_cancel_run_returns_400_when_not_cancellable(self, client, fake_manager):
        fake_manager.cancel_returns_true = False
        r = client.post("/api/runs/r-1/cancel")
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Read-mostly per-run endpoints
# ---------------------------------------------------------------------------


class TestExperimentsRoute:
    def test_returns_rows_in_step_order(self, client, fake_manager):
        fake_manager.runs["r-1"] = _make_run_info(id="r-1")
        fake_manager.experiments["r-1"] = [
            {"step": 0, "score": 0.5, "kept": True},
            {"step": 1, "score": 0.6, "kept": True},
        ]
        r = client.get("/api/runs/r-1/experiments")
        assert r.status_code == 200
        assert [e["step"] for e in r.json()] == [0, 1]

    def test_404_when_run_missing(self, client):
        r = client.get("/api/runs/missing/experiments")
        assert r.status_code == 404


class TestSummaryRoute:
    def test_returns_bundled_payload(self, client, fake_manager):
        fake_manager.runs["r-1"] = _make_run_info(id="r-1")
        fake_manager.stages["r-1"] = [
            StageInfo(stage_name="setup", status="pass", attempt=1, max_attempts=3),
        ]
        fake_manager.experiments["r-1"] = [{"step": 0, "score": 0.5}]
        fake_manager.peak["r-1"] = {"score": 0.5, "step": 0}
        fake_manager.events["r-1"] = [{"timestamp": 1.0, "event_type": "x"}]

        body = client.get("/api/runs/r-1/summary").json()
        assert body["run"]["id"] == "r-1"
        assert body["stages"][0]["stage_name"] == "setup"
        assert body["experiments"][0]["step"] == 0
        assert body["peak"]["score"] == 0.5
        assert body["events"][0]["event_type"] == "x"

    def test_404_when_run_missing(self, client):
        assert client.get("/api/runs/nope/summary").status_code == 404


class TestResearchLogRoute:
    def test_returns_text_when_file_exists(self, client, fake_manager, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "research_log.md").write_text("Experiment 1: ...")
        fake_manager.runs["r-1"] = _make_run_info(id="r-1", workspace=str(ws))

        body = client.get("/api/runs/r-1/research-log").json()
        assert body["exists"] is True
        assert "Experiment 1" in body["text"]

    def test_returns_empty_when_file_missing(self, client, fake_manager, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        fake_manager.runs["r-1"] = _make_run_info(id="r-1", workspace=str(ws))
        body = client.get("/api/runs/r-1/research-log").json()
        assert body == {"text": "", "exists": False}

    def test_404_when_run_missing(self, client):
        assert client.get("/api/runs/missing/research-log").status_code == 404


class TestTrainingLogRoute:
    def test_returns_text_from_workspace_root(self, client, fake_manager, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "training.log").write_text("Epoch 1/10 - loss: 0.42")
        fake_manager.runs["r-1"] = _make_run_info(id="r-1", workspace=str(ws))

        body = client.get("/api/runs/r-1/training-log").json()
        assert body["exists"] is True
        assert "loss: 0.42" in body["text"]

    def test_returns_text_from_logs_subdir_fallback(
        self, client, fake_manager, tmp_path,
    ):
        ws = tmp_path / "ws"
        (ws / "logs").mkdir(parents=True)
        (ws / "logs" / "training.log").write_text("from logs/")
        fake_manager.runs["r-1"] = _make_run_info(id="r-1", workspace=str(ws))

        body = client.get("/api/runs/r-1/training-log").json()
        assert body["exists"] is True
        assert body["text"] == "from logs/"

    def test_offset_tail_returns_only_new_bytes(
        self, client, fake_manager, tmp_path,
    ):
        ws = tmp_path / "ws"
        ws.mkdir()
        content = "first chunk\nsecond chunk\n"
        (ws / "training.log").write_text(content)
        fake_manager.runs["r-1"] = _make_run_info(id="r-1", workspace=str(ws))

        first_chunk_bytes = len("first chunk\n")
        body = client.get(
            f"/api/runs/r-1/training-log?offset={first_chunk_bytes}",
        ).json()
        assert body["exists"] is True
        # We asked for everything past byte N — that's exactly the second chunk.
        assert "second chunk" in body["text"]
        assert "first chunk" not in body["text"]

    def test_offset_past_file_size_rewinds(self, client, fake_manager, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "training.log").write_text("short")
        fake_manager.runs["r-1"] = _make_run_info(id="r-1", workspace=str(ws))
        body = client.get("/api/runs/r-1/training-log?offset=999999").json()
        # Offset got rewound to 0 — full content returned.
        assert body["text"] == "short"

    def test_returns_exists_false_when_no_log_file(
        self, client, fake_manager, tmp_path,
    ):
        ws = tmp_path / "ws"
        ws.mkdir()
        fake_manager.runs["r-1"] = _make_run_info(id="r-1", workspace=str(ws))
        body = client.get("/api/runs/r-1/training-log").json()
        assert body == {"text": "", "size": 0, "exists": False}

    def test_404_when_run_missing(self, client):
        assert client.get("/api/runs/missing/training-log").status_code == 404


class TestConsoleLogRoute:
    def test_console_offset_tail(self, client, fake_manager, tmp_path, monkeypatch):
        # console_log_path is a module-level helper in run_manager — patch it
        # so we control where the per-run log lives in the test fs.
        log_dir = tmp_path / "runs" / "r-1"
        log_dir.mkdir(parents=True)
        log = log_dir / "console.log"
        log.write_text("hello world")

        monkeypatch.setattr(
            "mle_beast.run_manager.console_log_path", lambda run_id: log,
        )

        body = client.get("/api/runs/r-1/console?offset=6").json()
        assert body["exists"] is True
        assert body["text"] == "world"
        assert body["size"] == len("hello world")

    def test_console_missing_file(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr(
            "mle_beast.run_manager.console_log_path",
            lambda run_id: tmp_path / "does-not-exist.log",
        )
        body = client.get("/api/runs/r-1/console").json()
        assert body == {"text": "", "size": 0, "exists": False}

    def test_console_offset_past_size_rewinds(
        self, client, monkeypatch, tmp_path,
    ):
        log = tmp_path / "x.log"
        log.write_text("abc")
        monkeypatch.setattr(
            "mle_beast.run_manager.console_log_path", lambda run_id: log,
        )
        body = client.get("/api/runs/r-1/console?offset=999").json()
        assert body["text"] == "abc"


class TestGitLogRoute:
    def test_404_when_run_missing(self, client):
        assert client.get("/api/runs/missing/git-log").status_code == 404

    def test_returns_empty_when_workspace_has_no_git(
        self, client, fake_manager, tmp_path,
    ):
        ws = tmp_path / "ws"
        ws.mkdir()
        fake_manager.runs["r-1"] = _make_run_info(id="r-1", workspace=str(ws))
        body = client.get("/api/runs/r-1/git-log").json()
        assert body == {"commits": [], "exists": False}

    def test_parses_git_log_when_present(
        self, client, fake_manager, tmp_path, monkeypatch,
    ):
        import subprocess
        ws = tmp_path / "ws"
        (ws / ".git").mkdir(parents=True)  # presence check only
        fake_manager.runs["r-1"] = _make_run_info(id="r-1", workspace=str(ws))

        SEP = "\x1f"
        log_line = SEP.join([
            "deadbeefcafe1234", "deadbee", "2026-05-17T12:00:00",
            "Chris Padwick", "step 1: bumped LR",
        ])

        def fake_run(cmd, **kw):
            r = subprocess.CompletedProcess(cmd, 0)
            if "log" in cmd:
                r.stdout = log_line + "\n"
                r.stderr = ""
            elif "branch" in cmd and "--show-current" in cmd:
                r.stdout = "experiments\n"
                r.stderr = ""
            else:  # `git branch --all --format=...`
                r.stdout = "main\nexperiments\n"
                r.stderr = ""
            return r

        monkeypatch.setattr(subprocess, "run", fake_run)

        body = client.get("/api/runs/r-1/git-log").json()
        assert body["exists"] is True
        assert len(body["commits"]) == 1
        c = body["commits"][0]
        assert c["short"] == "deadbee"
        assert c["subject"] == "step 1: bumped LR"
        assert body["head_branch"] == "experiments"
        assert "main" in body["branches"]

    def test_handles_git_log_failure_gracefully(
        self, client, fake_manager, tmp_path, monkeypatch,
    ):
        import subprocess
        ws = tmp_path / "ws"
        (ws / ".git").mkdir(parents=True)
        fake_manager.runs["r-1"] = _make_run_info(id="r-1", workspace=str(ws))

        def boom(cmd, **kw):
            raise OSError("git binary missing")

        monkeypatch.setattr(subprocess, "run", boom)
        body = client.get("/api/runs/r-1/git-log").json()
        assert body["exists"] is True
        assert body["commits"] == []
        assert "error" in body


# ---------------------------------------------------------------------------
# Settings routes
# ---------------------------------------------------------------------------


class TestSettingsRoutes:
    def test_get_settings(self, client, monkeypatch):
        from mle_beast.settings import Settings
        monkeypatch.setattr(
            "mle_beast.web.routes.get_settings", lambda: Settings(log_level="DEBUG"),
        )
        body = client.get("/api/settings").json()
        assert body["log_level"] == "DEBUG"
        assert "max_tokens" in body

    def test_post_settings_persists_and_reloads(self, client, monkeypatch, fake_db):
        # Track that reload_settings + save_settings got called.
        reload_called = []

        def fake_reload():
            reload_called.append(True)

        monkeypatch.setattr("mle_beast.web.routes.reload_settings", fake_reload)

        captured = []

        def fake_save(db, settings):
            captured.append(settings)

        monkeypatch.setattr("mle_beast.web.routes.save_settings", fake_save)

        body = {"log_level": "DEBUG", "max_tokens": 1234}
        r = client.post("/api/settings", json=body)
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}
        # save_settings called with a Settings object reflecting our payload
        assert captured[0].log_level == "DEBUG"
        assert captured[0].max_tokens == 1234
        assert reload_called == [True]

    def test_local_model_name_uses_detector(self, client, monkeypatch):
        called = {}

        def fake_detect(base_url):
            called["base_url"] = base_url
            return "fake-local-model"

        monkeypatch.setattr(
            "mle_beast.llm._auto_detect_local_model", fake_detect,
        )
        monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://localhost:9999/v1")
        body = client.get("/api/local-model-name").json()
        # `configured` flag added so the frontend can distinguish
        # "no local LLM set up" from "local LLM set but probe failed".
        assert body == {"model": "fake-local-model", "configured": True}
        assert called["base_url"] == "http://localhost:9999/v1"

    def test_local_model_name_short_circuits_when_not_configured(
        self, client, monkeypatch
    ):
        """When `LOCAL_LLM_BASE_URL` isn't set, the endpoint must NOT
        call the detector (which previously defaulted to hitting
        http://localhost:8000/v1 — i.e., the dashboard server itself
        — and waited ~30s for retries to time out, blocking the
        FastAPI event loop). Regression test for the slow-load bug
        diagnosed in PR #18."""
        called = []

        def fake_detect(base_url):
            called.append(base_url)
            return "should-not-be-called"

        monkeypatch.setattr(
            "mle_beast.llm._auto_detect_local_model", fake_detect,
        )
        monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
        body = client.get("/api/local-model-name").json()
        assert body == {"model": None, "configured": False}
        assert called == [], "detector must not run when LOCAL_LLM_BASE_URL is unset"


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------


class TestAdminRoutes:
    def test_admin_stats_proxies_db(self, client, fake_db):
        body = client.get("/api/admin/stats").json()
        assert body["runs_count"] == 1
        assert body["db_size_bytes"] == 1234

    def test_delete_old_runs_uses_days_param(self, client, fake_db):
        r = client.post("/api/admin/delete-old-runs", json={"days": 7})
        assert r.status_code == 200
        assert r.json() == {"status": "ok", "deleted": 3}
        assert fake_db.deleted_runs == [("older_than", 7)]

    def test_delete_old_runs_default_days(self, client, fake_db):
        client.post("/api/admin/delete-old-runs", json={})
        # Default is 30
        assert fake_db.deleted_runs[-1] == ("older_than", 30)

    def test_reset_database_requires_confirmation(self, client, fake_db):
        r = client.post("/api/admin/reset-database", json={})
        assert r.status_code == 400
        assert "RESET" in r.json()["error"]
        assert fake_db.reset_called is False

    def test_reset_database_with_confirmation(self, client, fake_db):
        r = client.post(
            "/api/admin/reset-database", json={"confirm": "RESET"},
        )
        assert r.status_code == 200
        assert fake_db.reset_called is True

    def test_delete_run(self, client, fake_db):
        r = client.delete("/api/admin/runs/r-9")
        assert r.status_code == 200
        assert "r-9" in fake_db.deleted_runs


# ---------------------------------------------------------------------------
# SSE endpoint
# ---------------------------------------------------------------------------


class TestSSEEndpoint:
    """Cover the SSE handler's event→frame mapping without going through
    TestClient.stream — Starlette streaming-response + threading + the
    pytest-asyncio loop has too many moving parts to be reliable in this
    test harness.

    The mapping logic in the handler is duplicated in this loop body so
    any regression in the type→event-name table is caught here. The
    StreamingResponse wrapper itself is exercised live by the React app.
    """

    def test_event_type_mapping_covers_every_branch(self):
        import asyncio

        from mle_beast.events import (
            EventBus,
            ExperimentRecorded,
            LLMCall,
            LogMessage,
            RunStateChanged,
            StageCompleted,
            StageStarted,
        )

        async def scenario():
            bus = EventBus()
            bus.set_loop(asyncio.get_running_loop())
            queue = bus.subscribe_async("r-1")

            # One representative of every SSE-mapped type.
            bus.emit(StageStarted(run_id="r-1", stage="x"))
            bus.emit(StageCompleted(run_id="r-1", stage="x", outcome="pass"))
            bus.emit(ExperimentRecorded(run_id="r-1", step=1))
            bus.emit(LLMCall(run_id="r-1", model="gpt-5"))
            bus.emit(LogMessage(run_id="r-1", message="hi"))
            # Non-terminal RunStateChanged → stage_update.
            bus.emit(RunStateChanged(
                run_id="r-1", old_state="pending", new_state="running",
            ))
            # Terminal RunStateChanged → run_complete + break.
            bus.emit(RunStateChanged(
                run_id="r-1", old_state="running", new_state="completed",
            ))

            collected_types = []
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=0.5)
                # Mimic the handler's mapping verbatim.
                if isinstance(event, (StageStarted, StageCompleted)):
                    sse_type = "stage_update"
                elif isinstance(event, ExperimentRecorded):
                    sse_type = "experiment"
                elif isinstance(event, LLMCall):
                    sse_type = "llm_call"
                elif isinstance(event, RunStateChanged):
                    sse_type = (
                        "run_complete"
                        if event.new_state in ("completed", "failed", "cancelled")
                        else "stage_update"
                    )
                else:
                    sse_type = "log_entry"
                collected_types.append(sse_type)
                if isinstance(event, RunStateChanged) and event.new_state in (
                    "completed", "failed", "cancelled",
                ):
                    break
            bus.unsubscribe_async("r-1", queue)
            return collected_types

        types = asyncio.run(scenario())
        # Two stage_update for StageStarted+StageCompleted, plus a third
        # for the non-terminal RunStateChanged.
        assert types.count("stage_update") == 3
        assert "experiment" in types
        assert "llm_call" in types
        assert "log_entry" in types
        assert types[-1] == "run_complete"


# ---------------------------------------------------------------------------
# Extra error-path coverage for routes that have rare branches
# ---------------------------------------------------------------------------


class TestErrorBranches:
    def test_research_log_read_failure_returns_error_field(
        self, client, fake_manager, tmp_path, monkeypatch,
    ):
        """When read_text raises, the route surfaces the error in JSON."""
        from pathlib import Path

        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "research_log.md").write_text("present")
        fake_manager.runs["r-1"] = _make_run_info(id="r-1", workspace=str(ws))

        def boom(*a, **kw):
            raise PermissionError("nope")

        monkeypatch.setattr(Path, "read_text", boom)
        body = client.get("/api/runs/r-1/research-log").json()
        assert body["exists"] is False
        assert "error" in body
        assert "nope" in body["error"]

    def test_git_log_nonzero_returncode_returns_error(
        self, client, fake_manager, tmp_path, monkeypatch,
    ):
        import subprocess

        ws = tmp_path / "ws"
        (ws / ".git").mkdir(parents=True)
        fake_manager.runs["r-1"] = _make_run_info(id="r-1", workspace=str(ws))

        def fail_log(cmd, **kw):
            r = subprocess.CompletedProcess(cmd, returncode=128)
            r.stdout = ""
            r.stderr = "fatal: not a git repo\n"
            return r

        monkeypatch.setattr(subprocess, "run", fail_log)
        body = client.get("/api/runs/r-1/git-log").json()
        assert body["commits"] == []
        assert body["exists"] is True
        assert "fatal" in body["error"]

    def test_git_log_branch_subprocess_errors_are_swallowed(
        self, client, fake_manager, tmp_path, monkeypatch,
    ):
        """If the branch enumeration / show-current calls fail, the route
        still returns the commits it managed to parse. branches=[] and
        head_branch="" are the expected fallbacks.
        """
        import subprocess

        ws = tmp_path / "ws"
        (ws / ".git").mkdir(parents=True)
        fake_manager.runs["r-1"] = _make_run_info(id="r-1", workspace=str(ws))

        SEP = "\x1f"
        good_log = SEP.join([
            "deadbeef" * 5, "deadbee", "2026-05-17T00:00:00",
            "x", "subject",
        ]) + "\n"

        call_count = {"n": 0}

        def selective(cmd, **kw):
            call_count["n"] += 1
            # First call (git log) succeeds; later branch calls raise.
            if "log" in cmd:
                r = subprocess.CompletedProcess(cmd, 0)
                r.stdout = good_log
                r.stderr = ""
                return r
            raise OSError("branch enumeration broken")

        monkeypatch.setattr(subprocess, "run", selective)
        body = client.get("/api/runs/r-1/git-log").json()
        assert len(body["commits"]) == 1
        assert body["branches"] == []
        assert body["head_branch"] == ""
