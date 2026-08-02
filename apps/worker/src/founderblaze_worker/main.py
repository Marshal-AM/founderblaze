from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from founderblaze.core.config import get_settings
from founderblaze.core.jobs.migrate import migrate
from founderblaze.core.jobs.store import create_pool
from founderblaze.core.logging import setup_logging
from founderblaze_worker.activities import (
    run_apd_activity,
    run_brand_kit_activity,
    run_competitor_research_activity,
    run_outreach_activity,
    run_promo_video_activity,
    run_social_listening_activity,
)
from founderblaze_worker.workflows import (
    ApdWorkflow,
    BrandKitWorkflow,
    CompetitorResearchWorkflow,
    OutreachWorkflow,
    PromoVideoWorkflow,
    SocialListeningWorkflow,
)

log = logging.getLogger("founderblaze.worker")


async def _connect_client() -> Client:
    settings = get_settings()
    kwargs: dict = {"namespace": settings.temporal_namespace}
    if settings.temporal_api_key:
        kwargs["api_key"] = settings.temporal_api_key
    if settings.temporal_tls or settings.temporal_api_key:
        kwargs["tls"] = True
    return await Client.connect(settings.temporal_address, **kwargs)


async def async_main() -> None:
    setup_logging()
    settings = get_settings()
    pool = await create_pool(settings.database_url)
    await migrate(pool)

    client = await _connect_client()
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[
            ApdWorkflow,
            BrandKitWorkflow,
            OutreachWorkflow,
            SocialListeningWorkflow,
            PromoVideoWorkflow,
            CompetitorResearchWorkflow,
        ],
        activities=[
            run_apd_activity,
            run_brand_kit_activity,
            run_outreach_activity,
            run_social_listening_activity,
            run_promo_video_activity,
            run_competitor_research_activity,
        ],
    )
    log.info(
        "FounderBlaze worker listening queue=%s address=%s",
        settings.temporal_task_queue,
        settings.temporal_address,
    )
    await worker.run()


def run() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    run()
