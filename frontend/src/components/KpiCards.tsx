import type { Kpis } from "../api/types";

function fmt(n: number) {
  return n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}
function fmtMoney(n: number) {
  return `${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

export default function KpiCards({ kpis }: { kpis: Kpis }) {
  return (
    <div className="kpi-grid">
      <div className="kpi-card">
        <div className="label">Free capital</div>
        <div className={`value ${kpis.free_capital >= 0 ? "positive" : "negative"}`}>
          {fmtMoney(kpis.free_capital)}
        </div>
        <div className="subvalue">
          {fmtMoney(kpis.starting_capital)} total · {fmtMoney(kpis.capital_deployed)} deployed
        </div>
      </div>

      <div className="kpi-card">
        <div className="label">Net profit</div>
        <div className={`value ${kpis.total_net_profit_all_time >= 0 ? "positive" : "negative"}`}>
          {fmtMoney(kpis.total_net_profit_all_time)}
        </div>
        <div className="subvalue">
          {fmtMoney(kpis.total_net_profit_this_month)} this month
        </div>
      </div>

      <div className="kpi-card">
        <div className="label">Open positions</div>
        <div className="value">{fmt(kpis.open_positions_count)}</div>
      </div>

      <div className="kpi-card">
        <div className="label">Trades</div>
        <div className="value">{fmt(kpis.total_trades_all_time)}</div>
        <div className="subvalue">{fmt(kpis.total_trades_this_month)} this month</div>
      </div>

      <div className="kpi-card">
        <div className="label">Capital currently invested</div>
        <div className="value">{fmtMoney(kpis.capital_deployed)}</div>
      </div>

      <div className="kpi-card">
        <div className="label">Charges &amp; tax</div>
        <div className="value">{fmtMoney(kpis.total_charges_paid)}</div>
        <div className="subvalue">{fmtMoney(kpis.total_tax_accrued)} tax accrued</div>
      </div>
    </div>
  );
}
