import unittest

from fastapi import FastAPI

from agent import shorts_studio_routes as agent_routes
from backend import shorts_studio_routes as backend_routes


def methods_for(app, path):
    methods = set()
    for route in app.routes:
        if getattr(route, "path", None) == path:
            methods.update(getattr(route, "methods", None) or set())
    return methods


class ShortsDeleteRouteMethodTests(unittest.TestCase):
    def test_agent_adds_delete_without_replacing_existing_get(self):
        app = FastAPI()

        @app.get("/api/shorts-jobs/{job_id}")
        def existing_get(job_id: str):
            return {"id": job_id}

        agent_routes.install_routes(app)

        methods = methods_for(app, "/api/shorts-jobs/{job_id}")
        self.assertIn("GET", methods)
        self.assertIn("DELETE", methods)

    def test_backend_adds_delete_without_replacing_existing_get(self):
        app = FastAPI()

        @app.get("/api/mlx/shorts-jobs/{job_id}")
        def existing_get(job_id: str):
            return {"id": job_id}

        backend_routes.install_routes(app, lambda *args, **kwargs: {})

        methods = methods_for(app, "/api/mlx/shorts-jobs/{job_id}")
        self.assertIn("GET", methods)
        self.assertIn("DELETE", methods)


if __name__ == "__main__":
    unittest.main()
