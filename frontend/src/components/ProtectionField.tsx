export type ProtectionMode = "price" | "pct";

export default function ProtectionField({
  label,
  mode,
  value,
  onModeChange,
  onValueChange,
  secondaryText,
  hint,
  optional,
}: {
  label: string;
  mode: ProtectionMode;
  value: string;
  onModeChange: (m: ProtectionMode) => void;
  onValueChange: (v: string) => void;
  secondaryText?: string;
  hint?: string;
  optional?: boolean;
}) {
  return (
    <div className="modal-field">
      <div className="protection-field-header">
        <label>
          {label}
          {optional ? " (optional)" : ""}
        </label>
        <div className="mode-toggle">
          <button type="button" className={mode === "price" ? "active" : ""} onClick={() => onModeChange("price")}>
            Price
          </button>
          <button type="button" className={mode === "pct" ? "active" : ""} onClick={() => onModeChange("pct")}>
            %
          </button>
        </div>
      </div>
      <input
        type="number"
        step={mode === "price" ? "0.05" : "0.1"}
        value={value}
        onChange={(e) => onValueChange(e.target.value)}
        placeholder={mode === "price" ? "e.g. 1450.00" : "e.g. 3"}
      />
      {secondaryText && <span className="field-hint">{secondaryText}</span>}
      {hint && <span className="field-hint">{hint}</span>}
    </div>
  );
}
