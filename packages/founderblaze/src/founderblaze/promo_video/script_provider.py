from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from genblaze_core import Modality, ProviderCapabilities, SyncProvider

from founderblaze.promo_video._assets import find_input_json, json_file_asset
from founderblaze.promo_video.gemini_chat import gemini_json

log = logging.getLogger("founderblaze.promo_video.script")


class ScriptProvider(SyncProvider):
    """Creative-director Gemini → structured promo script + Seedance prompt.

    Prompt body is ported from services/promo-video-service/src/script.ts
    ``buildScriptPrompt`` (screenshot bits adapted for grounded product brief).
    """

    name = "promo-video-script"

    def __init__(
        self,
        *,
        product_url: str,
        duration: int,
        resolution: str,
        api_key: str | None = None,
        work_dir: str | None = None,
    ) -> None:
        super().__init__()
        self.product_url = product_url
        self.duration = duration
        self.resolution = resolution
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.work_dir = work_dir

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supported_modalities=[Modality.TEXT],
            accepts_chain_input=True,
        )

    def generate(self, step, config=None):  # noqa: ANN001
        model = step.model or os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
        brief = find_input_json(step.inputs, "promo_product_brief")
        duration = int(self.duration)
        aspect = "16:9"
        prompt = _build_script_prompt(
            url=self.product_url,
            duration=duration,
            aspect_ratio=aspect,
            resolution=self.resolution,
            brief=brief,
        )
        data = gemini_json(
            prompt,
            model=model,
            api_key=self.api_key,
            system=(
                "You are an elite advertising creative director — the kind who makes "
                "people say \"wait, play that again\" — not a product-demo narrator. "
                "Return JSON only matching the requested schema. No markdown fences. "
                "Generic SaaS-ad energy is a failure state."
            ),
        )
        seedance_prompt = str(
            data.get("seedance_prompt") or data.get("veo_prompt") or ""
        ).strip()
        if len(seedance_prompt) < 40:
            raise RuntimeError("script missing seedance_prompt")
        voiceover = str(data.get("voiceover") or "").strip()
        if len(voiceover) < 20:
            raise RuntimeError("script missing voiceover")

        script = {
            "concept": str(data.get("concept") or "").strip(),
            "big_idea": str(data.get("big_idea") or "").strip(),
            "tone": str(data.get("tone") or "").strip(),
            "voiceover": voiceover,
            "shot_list": data.get("shot_list") or [],
            "seedance_prompt": seedance_prompt,
            "duration_seconds": duration,
            "resolution": self.resolution,
            "aspect_ratio": aspect,
            "product_url": self.product_url,
            "product_name": brief.get("product_name"),
            "model": model,
        }
        log.info(
            "script ready concept=%s big_idea=%s seedance_chars=%s",
            script["concept"][:80],
            script["big_idea"][:120],
            len(seedance_prompt),
        )
        step.assets.append(
            json_file_asset(
                script,
                work_dir=Path(self.work_dir or "."),
                name="script",
                metadata={"kind": "promo_script"},
            )
        )
        return step


def _build_script_prompt(
    *,
    url: str,
    duration: int,
    aspect_ratio: str,
    resolution: str,
    brief: dict,
) -> str:
    """Port of services/promo-video-service/src/script.ts ``buildScriptPrompt``.

    Screenshots → grounded product brief (no browser capture in this stack).
    """
    catalog = json.dumps(brief, indent=2, default=str)

    return f"""You are an elite advertising creative director — the kind who makes people say
"wait, play that again" — not a product-demo narrator. You've been hired to
write a {duration}-second promo AD for the product at this URL, in the style
of a real brand commercial (think: Apple, Nike, Duolingo, Liquid Death — bold,
funny, emotional, or weird, never a screen-recording with a voiceover on top).

PRODUCT URL: {url}
TARGET RESOLUTION: {resolution}
ASPECT RATIO: {aspect_ratio}

You have a GROUNDED PRODUCT BRIEF researched from the live web about this product.
These facts are your only source of truth for what the product is and does —
use them for specificity in visuals and VO. Do NOT invent fake UI chrome, fake
pricing, or fake customer logos. When the ad needs a "product proof" beat,
stage a cinematic reveal of the product's real capability using concrete details
from the brief (name, one-liner, features, proof points) — never a generic
"app screen" montage.

GROUNDED PRODUCT BRIEF:
{catalog}

═══════════════════════════════════════════════════════════════════
YOUR ACTUAL JOB: THIS IS AN ADVERT, NOT A UI WALKTHROUGH
═══════════════════════════════════════════════════════════════════

The brief is ingredients, not the whole meal. A killer {duration}s ad
for this product should feel like a real campaign spot: it needs a HOOK, a
BIG IDEA (a metaphor, a joke, a tension, a world), and a payoff — with a
product-proof beat dropped in at the 1–2 moments where showing the product
truth actually lands harder than metaphor alone.

Most of the shots in this ad should NOT be product UI. They should be
fully-generated cinematic content that Seedance creates from scratch:
real people, environments, objects, abstract visuals, physical metaphors,
humor beats, before/after moments — whatever best sells the emotional core
of what this product does for someone. Only cut to a product-proof beat when
it's the strongest way to prove a specific claim ("look, it actually does this").

Think like these are the two types of shots you're directing:
  (A) CINEMATIC / GENERATED shots — shot_type "cinematic". Fully imagined by Seedance:
      actors, locations, objects, motion graphics, metaphor visuals, physical
      comedy, environments — whatever the concept calls for. This should be
      the majority of the runtime.
  (B) PRODUCT PROOF shots — shot_type "product_proof". Used sparingly, at the
      exact moment the ad needs to prove the product is real and show what it
      actually does, using SPECIFIC facts from the brief. These should feel like
      a reveal, not a slide — camera pushes in, detail is large and legible,
      held just long enough to land.

Before writing anything, invent a BIG IDEA for this specific product — a
metaphor, a scenario, a character, a running joke, an emotional truth about
the problem it solves — something that would make this ad memorable even to
someone with zero interest in the product category. Do not default to
"person struggles with problem, discovers app, life is now easy" unless you
can make that specific version genuinely funny, surprising, or emotionally
sharp. Generic SaaS-ad energy is a failure state.

═══════════════════════════════════════════════════════════════════
HARD CONSTRAINTS
═══════════════════════════════════════════════════════════════════
- Duration: EXACTLY {duration} seconds. Not "about" — exactly.
- Voiceover must be spoken in FULL within {duration}s at a fast, punchy,
  trailer-paced read (~2.5-3 words/second is a safe budget for energetic VO —
  count your words and check the math before finalizing). No dead air, no
  wasted beats, no line you write that gets cut for time.
- At least one shot_type "product_proof" must appear, grounded in a real detail
  from the brief. Never invent UI that isn't supported by the brief.
- Every shot in the shot list must have a start_s/end_s that fits inside
  [0, {duration}], shots must be contiguous and non-overlapping, and the
  final shot's end_s must equal {duration} exactly.
- End on a clear, deliberate BRAND/PRODUCT ENDCARD moment — name, logo-style
  treatment, or a final line that unmistakably identifies the product. This
  is the last thing viewers see; don't let it get crowded out.
- Sound is not an afterthought. Direct music and SFX like a real ad: describe
  the actual sonic personality (e.g. "plucky, mischievous, slightly unhinged
  synth-pop" or "tense stripped-back percussion that explodes into a bright
  drop at the reveal") — never generic "upbeat corporate background music."
  SFX should be specific and diegetic where possible (UI clicks, whooshes,
  a real-world sound tied to the metaphor) not generic stock sweeteners.
- ON-SCREEN TEXT: If the video will include any generated text (titles, captions,
  endcard typography, labels, etc.), it must be ONLY in English and must use
  proper, error-free English — correct spelling, grammar, and punctuation with
  zero typos or broken words. Your seedance_prompt MUST include an explicit
  instruction to Seedance enforcing this rule.

═══════════════════════════════════════════════════════════════════
CREATIVE DIRECTION — HOW TO ACTUALLY MAKE IT GOOD
═══════════════════════════════════════════════════════════════════
- OPEN WITH A HOOK, NOT A LOGO. The first 1-2 seconds must earn attention —
  a visual surprise, a bold claim, a joke, an in-media-res moment. Nobody
  is contractually obligated to keep watching; earn every second.
- STRUCTURE: give the ad a shape — tension/release, setup/punchline,
  before/after, escalating chaos resolved by the product, or a single
  sustained joke/metaphor carried through to a satisfying product reveal.
  Don't just list features in order.
- SPECIFICITY BEATS POLISH. Reference something TRUE and SPECIFIC about this
  product (from the brief) rather than vague category language.
  "Never lose the thread on a 40-tab research binge" beats "stay organized."
- ONE BIG IDEA, not five small ones. If you have a good metaphor, commit to
  it visually across multiple shots rather than touching it once and moving on.
- CAMERA LANGUAGE MATTERS for a generated-video prompt — direct it like a DP:
  whip pans, match cuts, push-ins, rack focus, needle-drop-timed cuts on the
  beat, physical comedy timing. Give Seedance real blocking, not just "shows
  a scene."
- VOICEOVER PERSONALITY: write it like a person with a point of view, not a
  narrator reading feature bullets. Confident, a little cheeky, rhythmically
  tight. Match the tone to the product's actual vibe (inferred from the
  brief) rather than defaulting to generic "startup enthusiasm."
- PACING: vary shot length deliberately — quick cuts for energy/chaos beats,
  one longer held shot for the emotional or reveal beat. Uniform 2-second
  shots all the way through reads as lazy, not punchy.

═══════════════════════════════════════════════════════════════════
seedance_prompt REQUIREMENTS
═══════════════════════════════════════════════════════════════════
The seedance_prompt field must be a COMPLETE, ready-to-send prompt for
ByteDance Seedance 2.0, including:
- Aspect ratio: {aspect_ratio}, resolution: {resolution}, duration: {duration}s
- A full "Shot N | start–end" script covering every shot, describing EACH
  shot's visual action/blocking/camera move in enough detail to generate
  directly — clearly marking which shots are cinematic/generated vs. which
  are product-proof beats grounded in brief facts
- The full VO text, broken into per-shot slices matching the shot list,
  with pacing/delivery notes (e.g. "fast, deadpan," "building energy," "warm,
  slows down here")
- Explicit music/SFX direction as described above — specific personality,
  not corporate-generic, including where the music hits a beat/drop/turn
- An instruction block telling Seedance to generate synced dialogue/VO audio
  and music together with the visuals (generate_audio-style instruction),
  not as a silent video to be scored separately
- A closing line locking in the endcard moment (branding, logo treatment,
  final product name callout)
- A mandatory instruction block directed at Seedance: if the model generates any
  on-screen text in the video (titles, captions, typography, labels, etc.), that
  text must be ONLY in English and must be proper, error-free English — correct
  spelling, grammar, and punctuation with no typos, no garbled words, and no
  other languages. Include this instruction verbatim in the seedance_prompt so
  Segmind receives it with every generation request.

═══════════════════════════════════════════════════════════════════
OUTPUT — return JSON matching exactly this shape:
═══════════════════════════════════════════════════════════════════
{{
  "concept": "short concept title + one-line premise (the big idea, stated sharply)",
  "big_idea": "1-3 sentences explaining the metaphor/hook/emotional core and why it fits this specific product",
  "tone": "tone keywords",
  "voiceover": "full spoken script as one string, exactly as it will be read",
  "shot_list": [
    {{
      "start_s": 0,
      "end_s": 2,
      "shot_type": "cinematic or product_proof",
      "visual": "detailed description of the action/blocking/camera move for this shot",
      "voiceover_slice": "...",
      "sound_notes": "music/SFX detail specific to this moment, if relevant"
    }}
  ],
  "seedance_prompt": "full ready-to-send prompt string to send to Seedance, per the requirements above"
}}

Before returning, self-check:
1. Does the VO word count actually fit {duration}s at a fast trailer pace? Recount if unsure.
2. Do shots cover [0, {duration}] exactly, contiguous, no gaps or overlaps?
3. Is the big idea specific to THIS product, or could it be pasted onto any SaaS site? If the latter, rewrite it.
4. Is there at least one product_proof beat grounded in the brief (not invented UI)?
5. Does it end on an unmistakable brand/product endcard moment?
6. Does the seedance_prompt include an explicit instruction to Seedance that any
   generated on-screen text must be ONLY in English and proper, error-free English?
"""
