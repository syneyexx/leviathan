"""Nested FastAPI + PEP 563 must still produce /openapi.json."""

from __future__ import annotations

import unittest

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel, Field

import fastapi_nested_annotations  # noqa: F401
from fastapi_nested_annotations import install_nested_annotation_patch


class NestedOpenApiAnnotationTests(unittest.TestCase):
    def test_nested_pydantic_body_is_not_a_query_forwardref(self) -> None:
        install_nested_annotation_patch()

        class Payload(BaseModel):
            goal: str = Field(default="")

        def mount_sample() -> APIRouter:
            router = APIRouter()

            class BuildPlanInput(BaseModel):
                edits: list[str] = Field(default_factory=list)
                goal: str = Field(default="")

            @router.post("/build/plan")
            async def build_plan(values: BuildPlanInput) -> dict[str, str]:
                del values
                return {"ok": "1"}

            @router.post("/run")
            async def run_project(payload: Payload | None = None) -> dict[str, str]:
                del payload
                return {"ok": "1"}

            return router

        app = FastAPI()
        app.include_router(mount_sample(), prefix="/api")
        spec = app.openapi()
        plan = spec["paths"]["/api/build/plan"]["post"]
        self.assertIn("requestBody", plan)
        query_names = {
            item.get("name")
            for item in (plan.get("parameters") or [])
            if item.get("in") == "query"
        }
        self.assertNotIn("edits", query_names)
        self.assertNotIn("goal", query_names)


if __name__ == "__main__":
    unittest.main()
