"""Vickrey durable observation sync — Temporal.

Wraps the offline -> online path so a dropped signal retries and resumes instead
of losing a sealed observation:

    sync_observation -> POST to the Messages API -> poll solid / milestone

Status: scaffold. It needs a Temporal server and a running Messages API to
execute; it has not been run yet. Partner mapping lives in docs/SPONSORS.md.

Run (once Temporal and the API are up):

    pip install -r services/sync/requirements.txt
    python -m services.sync.worker

Environment:
    TEMPORAL_ADDRESS   default localhost:7233
    TEMPORAL_NAMESPACE default default
    TEMPORAL_TASK_QUEUE default vickrey-sync
"""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta

import httpx
from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.worker import Worker

TASK_QUEUE = os.environ.get("TEMPORAL_TASK_QUEUE", "vickrey-sync")
TEMPORAL_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
TEMPORAL_NAMESPACE = os.environ.get("TEMPORAL_NAMESPACE", "default")

POST_RETRY = RetryPolicy(maximum_attempts=10)
ANCHOR_RETRY = RetryPolicy(maximum_attempts=30)


@activity.defn
async def post_observation(payload: dict) -> str:
    """Insert one sealed observation through the Messages API; return the block id."""
    messages_url = payload["messages_url"]
    body = {"tag": payload["tag"], "message": payload["message"]}
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(messages_url, json=body)
        response.raise_for_status()
        data = response.json()
    return data.get("blockId") or data.get("block_id")


@activity.defn
async def wait_for_anchor(block_id: str, hornet_url: str) -> dict:
    """Read block metadata until Hornet returns it (retried by the workflow)."""
    url = f"{hornet_url.rstrip('/')}/api/core/v2/blocks/{block_id}/metadata"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


@workflow.defn
class SyncObservationWorkflow:
    @workflow.run
    async def run(self, payload: dict) -> dict:
        block_id = await workflow.execute_activity(
            post_observation,
            payload,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=POST_RETRY,
        )
        metadata = await workflow.execute_activity(
            wait_for_anchor,
            args=[block_id, payload["hornet_url"]],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=ANCHOR_RETRY,
        )
        return {"block_id": block_id, "metadata": metadata}


async def main() -> None:
    client = await Client.connect(TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE)
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[SyncObservationWorkflow],
        activities=[post_observation, wait_for_anchor],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
