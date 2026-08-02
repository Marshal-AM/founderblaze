"use client";

import { PanelRightClose } from "lucide-react";

const SERVICES = [
  { name: "Promo Video", need: "product URL" },
  { name: "Product Demo", need: "website + script" },
  { name: "Brand Kit", need: "name + description" },
  { name: "App Kit", need: "name + idea" },
  { name: "Outreach", need: "website + sheet URL" },
  { name: "Social Listening", need: "product URL" },
  { name: "Competitor Research", need: "product name" },
];

type Props = {
  onCollapse: () => void;
};

export function CapabilitiesPanel({ onCollapse }: Props) {
  return (
    <aside className="panel-card sidebar-panel">
      <div className="panel-header">
        <div>
          <p className="panel-kicker">Catalog</p>
          <p className="panel-title">Services</p>
        </div>
        <button
          type="button"
          className="icon-btn"
          onClick={onCollapse}
          title="Collapse sidebar"
          aria-label="Collapse sidebar"
        >
          <PanelRightClose className="h-4 w-4" />
        </button>
      </div>
      <div className="caps-list">
        {SERVICES.map((s) => (
          <div key={s.name} className="caps-row">
            <p className="caps-name">{s.name}</p>
            <p className="caps-need mono">{s.need}</p>
          </div>
        ))}
      </div>
    </aside>
  );
}
