from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent import shorts_studio_routes as agent_routes
from backend import shorts_studio_routes as web_routes


def test_agent_scene_revision_route_starts_durable_revision_job():
    app = FastAPI()
    agent_routes.install_routes(app)
    client = TestClient(app)
    revised = {
        "id": "0123456789abcdef01234567",
        "status": "queued",
        "project": {
            "scenes": [{"id": "scene-1"}],
        },
    }

    with (
        mock.patch.object(
            agent_routes,
            "create_scene_revision",
            return_value=revised,
        ) as create_revision,
        mock.patch.object(
            agent_routes.shorts_jobs,
            "start_short_job",
        ) as start_job,
    ):
        response = client.post(
            "/api/shorts/jobs/source-job/scenes/scene-1/revise",
            json={
                "narration": "Updated narration",
                "voice": "Pervin",
                "voice_speed": 1.15,
            },
        )

    assert response.status_code == 202, response.text
    assert response.json() == {"job": revised}
    create_revision.assert_called_once_with(
        "source-job",
        "scene-1",
        narration="Updated narration",
        video_prompt=None,
        force_regenerate_video=False,
        voice="Pervin",
        voice_speed=1.15,
    )
    start_job.assert_called_once_with(revised["id"])


def test_agent_scene_revision_route_maps_invalid_revision_to_400():
    app = FastAPI()
    agent_routes.install_routes(app)
    client = TestClient(app)

    with mock.patch.object(
        agent_routes,
        "create_scene_revision",
        side_effect=ValueError("short revision requires a change"),
    ):
        response = client.post(
            "/api/shorts/jobs/source-job/scenes/scene-1/revise",
            json={},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "short revision requires a change"


def test_web_scene_revision_route_proxies_to_loopback_agent():
    calls = []

    def agent_json_request(method, path, payload=None, timeout=10):
        calls.append((method, path, payload, timeout))
        return {"job": {"id": "revision-job", "status": "queued"}}

    app = FastAPI()
    web_routes.install_routes(app, agent_json_request)
    client = TestClient(app)

    payload = {
        "video_prompt": "New cinematic skyline",
        "force_regenerate_video": True,
    }
    response = client.post(
        "/api/mlx/shorts-jobs/source-job/scenes/scene-1/revise",
        json=payload,
    )

    assert response.status_code == 202, response.text
    assert response.json()["job"]["id"] == "revision-job"
    assert calls == [(
        "POST",
        "/api/shorts/jobs/source-job/scenes/scene-1/revise",
        payload,
        30,
    )]


def test_route_installers_are_idempotent():
    agent_app = FastAPI()
    agent_routes.install_routes(agent_app)
    count = len(agent_app.routes)
    agent_routes.install_routes(agent_app)
    assert len(agent_app.routes) == count

    web_app = FastAPI()
    web_routes.install_routes(web_app, lambda *args, **kwargs: {})
    count = len(web_app.routes)
    web_routes.install_routes(web_app, lambda *args, **kwargs: {})
    assert len(web_app.routes) == count
