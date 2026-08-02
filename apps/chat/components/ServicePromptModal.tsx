"use client";

import { FormEvent, useEffect, useState } from "react";
import { X } from "lucide-react";

export type ServiceFormDef = {
  id: string;
  label: string;
  blurb: string;
  fields: Array<{
    key: string;
    label: string;
    placeholder: string;
    type?: "text" | "url" | "textarea";
    required?: boolean;
  }>;
  buildPrompt: (values: Record<string, string>) => string;
};

export const SERVICE_FORMS: ServiceFormDef[] = [
  {
    id: "promo-video",
    label: "Promo Video",
    blurb: "Cinematic ad from your product URL.",
    fields: [
      {
        key: "product_url",
        label: "Product URL",
        placeholder: "https://yourproduct.com",
        type: "url",
        required: true,
      },
    ],
    buildPrompt: (v) =>
      `Please create a promo video for this product URL: ${v.product_url}`,
  },
  {
    id: "automated-product-demo",
    label: "Product Demo",
    blurb: "Narrated walkthrough of your live site.",
    fields: [
      {
        key: "website_url",
        label: "Website URL",
        placeholder: "https://yourproduct.com",
        type: "url",
        required: true,
      },
      {
        key: "script",
        label: "Demo script",
        placeholder: "Click Sign up, fill the form, then show the dashboard…",
        type: "textarea",
        required: true,
      },
    ],
    buildPrompt: (v) =>
      `Please record an automated product demo for ${v.website_url} with this script:\n${v.script}`,
  },
  {
    id: "brand-kit",
    label: "Brand Kit",
    blurb: "Logo, palette, fonts, and social assets.",
    fields: [
      {
        key: "brand_name",
        label: "Brand name",
        placeholder: "Acme",
        required: true,
      },
      {
        key: "description",
        label: "Description",
        placeholder: "What you build and who it’s for…",
        type: "textarea",
        required: true,
      },
    ],
    buildPrompt: (v) =>
      `Please generate a brand kit for "${v.brand_name}". Description: ${v.description}`,
  },
  {
    id: "app-kit",
    label: "App Kit",
    blurb: "Desktop and mobile UI mock screens.",
    fields: [
      {
        key: "product_name",
        label: "Product name",
        placeholder: "Acme",
        required: true,
      },
      {
        key: "product_idea",
        label: "Product idea",
        placeholder: "What the product does and key screens…",
        type: "textarea",
        required: true,
      },
    ],
    buildPrompt: (v) =>
      `Please generate an app kit for "${v.product_name}". Product idea: ${v.product_idea}`,
  },
  {
    id: "pitch-deck",
    label: "Pitch Deck",
    blurb: "6–8 page investor deck PDF from your product URL.",
    fields: [
      {
        key: "product_url",
        label: "Product URL",
        placeholder: "https://yourproduct.com",
        type: "url",
        required: true,
      },
      {
        key: "funding_ask",
        label: "Funding ask",
        placeholder: "$2M seed",
        required: true,
      },
    ],
    buildPrompt: (v) =>
      `Please generate a pitch deck for this product URL: ${v.product_url} with funding ask: ${v.funding_ask}`,
  },
  {
    id: "outreach",
    label: "Outreach",
    blurb: "Investor intelligence report from site + revenue sheet.",
    fields: [
      {
        key: "website_url",
        label: "Company website",
        placeholder: "https://yourcompany.com",
        type: "url",
        required: true,
      },
      {
        key: "sheet_url",
        label: "Revenue spreadsheet URL",
        placeholder: "https://…xlsx or public CSV link",
        type: "url",
        required: true,
      },
    ],
    buildPrompt: (v) =>
      `Please run investor outreach using website ${v.website_url} and this revenue spreadsheet: ${v.sheet_url}`,
  },
  {
    id: "social-listening",
    label: "Social Listening",
    blurb: "Reddit threads and draft replies.",
    fields: [
      {
        key: "product_url",
        label: "Product URL",
        placeholder: "https://yourproduct.com",
        type: "url",
        required: true,
      },
      {
        key: "product_name",
        label: "Product name (optional)",
        placeholder: "Acme",
      },
    ],
    buildPrompt: (v) => {
      const name = v.product_name?.trim();
      return name
        ? `Please run social listening for ${name} at ${v.product_url}`
        : `Please run social listening for this product URL: ${v.product_url}`;
    },
  },
  {
    id: "competitor-research",
    label: "Competitor Research",
    blurb: "Features, pricing, and positioning brief.",
    fields: [
      {
        key: "product_name",
        label: "Product name",
        placeholder: "Notion",
        required: true,
      },
      {
        key: "product_url",
        label: "Product URL (optional)",
        placeholder: "https://notion.so",
        type: "url",
      },
    ],
    buildPrompt: (v) => {
      const url = v.product_url?.trim();
      return url
        ? `Please run competitor research for ${v.product_name} (${url})`
        : `Please run competitor research for product name: ${v.product_name}`;
    },
  },
];

type Props = {
  service: ServiceFormDef | null;
  onClose: () => void;
  onConfirm: (prompt: string) => void;
};

export function ServicePromptModal({ service, onClose, onConfirm }: Props) {
  const [values, setValues] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!service) return;
    setValues({});
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [service, onClose]);

  if (!service) return null;

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    for (const f of service!.fields) {
      if (f.required && !String(values[f.key] || "").trim()) return;
    }
    onConfirm(service!.buildPrompt(values));
    onClose();
  }

  return (
    <div
      className="modal-backdrop"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div className="modal-card service-modal" onClick={(e) => e.stopPropagation()}>
        <button type="button" className="modal-close" onClick={onClose} aria-label="Close">
          <X className="h-4 w-4" />
        </button>
        <p className="modal-label">{service.label}</p>
        <h2 className="modal-title">What we need</h2>
        <p className="modal-sub">{service.blurb}</p>
        <form className="auth-form" onSubmit={onSubmit}>
          {service.fields.map((f) =>
            f.type === "textarea" ? (
              <label key={f.key} className="field-label">
                <span>{f.label}</span>
                <textarea
                  value={values[f.key] || ""}
                  onChange={(e) =>
                    setValues((v) => ({ ...v, [f.key]: e.target.value }))
                  }
                  placeholder={f.placeholder}
                  required={f.required}
                  rows={4}
                />
              </label>
            ) : (
              <label key={f.key} className="field-label">
                <span>{f.label}</span>
                <input
                  type={f.type || "text"}
                  value={values[f.key] || ""}
                  onChange={(e) =>
                    setValues((v) => ({ ...v, [f.key]: e.target.value }))
                  }
                  placeholder={f.placeholder}
                  required={f.required}
                />
              </label>
            )
          )}
          <button type="submit" className="btn-ember-pill w-full">
            Insert prompt
          </button>
        </form>
      </div>
    </div>
  );
}
