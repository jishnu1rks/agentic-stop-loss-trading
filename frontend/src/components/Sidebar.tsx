import type { SVGProps } from "react";

export type View = "dashboard" | "open-trades" | "history" | "agent-settings";

const ICON_PROPS = {
  viewBox: "0 0 24 24",
  width: 18,
  height: 18,
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.75,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

function DashboardIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...ICON_PROPS} {...props}>
      <rect x="3" y="3" width="7" height="9" rx="1.5" />
      <rect x="14" y="3" width="7" height="5" rx="1.5" />
      <rect x="14" y="12" width="7" height="9" rx="1.5" />
      <rect x="3" y="16" width="7" height="5" rx="1.5" />
    </svg>
  );
}

function OpenTradesIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...ICON_PROPS} {...props}>
      <path d="M4 7h13M17 7l-3.5-3.5M17 7l-3.5 3.5" />
      <path d="M20 17H7M7 17l3.5-3.5M7 17l3.5 3.5" />
    </svg>
  );
}

function HistoryIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...ICON_PROPS} {...props}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 2" />
    </svg>
  );
}

function AgentSettingsIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg {...ICON_PROPS} {...props}>
      <path d="M4 6h9M17 6h3M4 12h3M9 12h11M4 18h13M19 18h1" />
      <circle cx="13" cy="6" r="2" />
      <circle cx="7" cy="12" r="2" />
      <circle cx="17" cy="18" r="2" />
    </svg>
  );
}

const ITEMS: { key: View; label: string; icon: (props: SVGProps<SVGSVGElement>) => JSX.Element }[] = [
  { key: "dashboard", label: "Dashboard", icon: DashboardIcon },
  { key: "open-trades", label: "Open trades", icon: OpenTradesIcon },
  { key: "history", label: "History", icon: HistoryIcon },
  { key: "agent-settings", label: "Agent settings", icon: AgentSettingsIcon },
];

export default function Sidebar({
  active,
  onChange,
  mobileOpen,
  onClose,
}: {
  active: View;
  onChange: (v: View) => void;
  mobileOpen: boolean;
  onClose: () => void;
}) {
  return (
    <>
      {mobileOpen && <div className="sidebar-overlay" onClick={onClose} />}
      <nav className={`sidebar${mobileOpen ? " open" : ""}`}>
        <div className="sidebar-title">Stop-Loss Trading</div>
        <ul className="sidebar-nav">
          {ITEMS.map((item) => (
            <li key={item.key}>
              <button
                className={active === item.key ? "active" : ""}
                onClick={() => {
                  onChange(item.key);
                  onClose();
                }}
              >
                <item.icon />
                {item.label}
              </button>
            </li>
          ))}
        </ul>
      </nav>
    </>
  );
}
