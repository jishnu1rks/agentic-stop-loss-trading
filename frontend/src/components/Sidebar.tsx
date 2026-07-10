export type View = "dashboard" | "open-trades" | "history" | "agent-settings";

const ITEMS: { key: View; label: string }[] = [
  { key: "dashboard", label: "Dashboard" },
  { key: "open-trades", label: "Open trades" },
  { key: "history", label: "History" },
  { key: "agent-settings", label: "Agent settings" },
];

export default function Sidebar({ active, onChange }: { active: View; onChange: (v: View) => void }) {
  return (
    <nav className="sidebar">
      <div className="sidebar-title">Stop-Loss Trading</div>
      <ul className="sidebar-nav">
        {ITEMS.map((item) => (
          <li key={item.key}>
            <button className={active === item.key ? "active" : ""} onClick={() => onChange(item.key)}>
              {item.label}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}
