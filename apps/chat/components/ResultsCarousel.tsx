"use client";

import { useEffect, useRef } from "react";

export type ShowcaseItem = {
  id: string;
  service: string;
  src: string;
  kind: "video" | "image";
};

export const SHOWCASE_ITEMS: ShowcaseItem[] = [
  {
    id: "promo",
    service: "Promo Video",
    src: "/showcase/promo-video.mp4",
    kind: "video",
  },
  {
    id: "demo",
    service: "Product Demo",
    src: "/showcase/product-demo.mp4",
    kind: "video",
  },
  {
    id: "brand",
    service: "Brand Kit",
    src: "/showcase/brand-kit.png",
    kind: "image",
  },
  {
    id: "outreach",
    service: "Investor Outreach",
    src: "/showcase/outreach.png",
    kind: "image",
  },
  {
    id: "social",
    service: "Social Listening",
    src: "/showcase/social-listening.png",
    kind: "image",
  },
  {
    id: "competitors",
    service: "Competitor Research",
    src: "/showcase/competitor-research.png",
    kind: "image",
  },
];

function ShowcaseCard({ item }: { item: ShowcaseItem }) {
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    const el = videoRef.current;
    if (!el) return;
    el.muted = true;
    const play = () => {
      void el.play().catch(() => undefined);
    };
    play();
  }, []);

  return (
    <article className="showcase-card">
      <div className="showcase-media">
        {item.kind === "video" ? (
          <video
            ref={videoRef}
            src={item.src}
            muted
            loop
            playsInline
            autoPlay
            preload="metadata"
          />
        ) : (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={item.src} alt={item.service} loading="lazy" />
        )}
      </div>
      <p className="showcase-caption">{item.service}</p>
    </article>
  );
}

/** Infinite CSS marquee — duplicated track, pauses on hover / reduced motion. */
export function ResultsCarousel() {
  const track = [...SHOWCASE_ITEMS, ...SHOWCASE_ITEMS];

  return (
    <div className="showcase-carousel" aria-label="Example deliverables">
      <div className="showcase-track">
        {track.map((item, i) => (
          <ShowcaseCard key={`${item.id}-${i}`} item={item} />
        ))}
      </div>
    </div>
  );
}
