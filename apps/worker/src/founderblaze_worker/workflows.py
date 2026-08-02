from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from founderblaze_worker.activities import (
        run_apd_activity,
        run_app_kit_activity,
        run_brand_kit_activity,
        run_competitor_research_activity,
        run_outreach_activity,
        run_promo_video_activity,
        run_social_listening_activity,
    )


@workflow.defn(name="ApdWorkflow")
class ApdWorkflow:
    @workflow.run
    async def run(self, job_id: str) -> dict:
        return await workflow.execute_activity(
            run_apd_activity,
            job_id,
            start_to_close_timeout=timedelta(minutes=45),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )


@workflow.defn(name="BrandKitWorkflow")
class BrandKitWorkflow:
    @workflow.run
    async def run(self, job_id: str) -> dict:
        return await workflow.execute_activity(
            run_brand_kit_activity,
            job_id,
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )


@workflow.defn(name="OutreachWorkflow")
class OutreachWorkflow:
    @workflow.run
    async def run(self, job_id: str) -> dict:
        return await workflow.execute_activity(
            run_outreach_activity,
            job_id,
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )


@workflow.defn(name="SocialListeningWorkflow")
class SocialListeningWorkflow:
    @workflow.run
    async def run(self, job_id: str) -> dict:
        return await workflow.execute_activity(
            run_social_listening_activity,
            job_id,
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )


@workflow.defn(name="PromoVideoWorkflow")
class PromoVideoWorkflow:
    @workflow.run
    async def run(self, job_id: str) -> dict:
        return await workflow.execute_activity(
            run_promo_video_activity,
            job_id,
            start_to_close_timeout=timedelta(minutes=45),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )


@workflow.defn(name="CompetitorResearchWorkflow")
class CompetitorResearchWorkflow:
    @workflow.run
    async def run(self, job_id: str) -> dict:
        return await workflow.execute_activity(
            run_competitor_research_activity,
            job_id,
            start_to_close_timeout=timedelta(minutes=45),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )


@workflow.defn(name="AppKitWorkflow")
class AppKitWorkflow:
    @workflow.run
    async def run(self, job_id: str) -> dict:
        return await workflow.execute_activity(
            run_app_kit_activity,
            job_id,
            start_to_close_timeout=timedelta(minutes=45),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
