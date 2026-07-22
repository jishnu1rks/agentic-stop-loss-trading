---
name: ui-update
description: Make a UI/dashboard change to the Agentic Stop-Loss Trading System frontend - add/remove/reorder table columns, add a modal/popup, change styling, add a button or confirmation. Use for any request to change what the dashboard shows or how it looks/behaves, without re-deriving the project's conventions from scratch.
---

# UI updates - conventions and where things live

Frontend: `frontend/src/` — Vite + React + TypeScript, no UI framework
(hand-rolled components + one CSS file). Talks to the backend via
`api/client.ts` (`http://127.0.0.1:8000` locally).

## File map

- `pages/DashboardPage.tsx`, `OpenTradesPage.tsx`, `HistoryPage.tsx`,
  `AgentSettingsPage.tsx` — one per sidebar tab, thin wrappers that mostly
  compose components below.
- `components/TradeLogTable.tsx` — the shared table behind **both** Open
  Trades and History (`lockedStatus="open"` vs `"closed"` prop switches
  which columns/filters show). **If asked to change "the open trades
  table", check whether the change should also apply to History** - they
  share this one file. Columns are defined once in a `cols` object (a
  `Record<string, Column>`), then two arrays (`isOpenView ? [...] : [...]`)
  pick which columns render for each view, in order. To add/remove/reorder
  a column: edit the `cols` object once, then edit the relevant array(s) -
  don't duplicate cell-rendering logic inline in JSX.
- `components/Modal.tsx` — generic dialog (title, body, footer, click-away
  + Escape to close). Reuse this for any new popup rather than hand-rolling
  a new overlay; see `EditProtectionModal.tsx` for a real example (edit
  form) and the inline `confirmClose` modal in `TradeLogTable.tsx` for a
  confirmation-dialog example.
- `components/KpiCards.tsx`, `RecommendationsPanel.tsx`, `Sidebar.tsx`,
  `AgentTable.tsx`, `AgentSettingsCard.tsx`, `LoginGate.tsx` — one concern
  each, names are literal.
- `api/client.ts` — every backend call goes through the `api` object here
  (`api.listTrades()`, `api.closeTrade()`, etc.), typed against
  `api/types.ts`. Add a new method here rather than calling `axios`/`fetch`
  directly from a component.
- `index.css` — one global stylesheet, plain classes (`.btn`, `.pill`,
  `.panel`, `.modal`, `.filters`, `.editable-cell`, etc.), no CSS modules,
  no Tailwind.

## Theming - both light and dark, every time

All colors are CSS variables defined twice in `index.css`: once under
`:root` (dark, default) and once under `:root[data-theme="light"]`
(`--bg`, `--panel`, `--panel-border`, `--text`, `--text-dim`, `--accent`,
`--green`, `--red`, `--amber`). **Never hardcode a hex color in a
component or inline `style`** - use `var(--...)` or an existing class
(`.text-green`, `.text-red`, `.text-dim`) so the change works in both
themes automatically. The theme toggle lives in `App.tsx` and flips
`data-theme` on `<html>`.

## Patterns already in place - reuse, don't reinvent

- **Confirmation before a destructive action**: see `confirmClose` state +
  inline `<Modal>` in `TradeLogTable.tsx` (close position). Copy this
  pattern for any new "are you sure?" prompt.
- **Click a cell to edit**: the `.editable-cell` button class (dashed
  underline, transparent background) + opening a modal on click - see the
  `stopLoss`/`target` cell definitions in `TradeLogTable.tsx`.
- **Per-open-position live data**: `api.openPositionsPnl()` returns a
  `Record<trade_id, OpenPositionPnl>` (current price, unrealized P&L,
  heading %) merged onto trade rows client-side - don't invent a second
  live-data fetch pattern, extend this endpoint/type if a new live field
  is needed (see `add-feature` skill for the backend side).
- **Column show/hide by view**: booleans like `isOpenView`,
  `showSellColumns` computed once near the top of the component, then used
  both in the `cols` array selection and to conditionally render table
  cells - keep header and cell logic driven by the same boolean, don't let
  them drift out of sync.

## After making a change

Type-check before calling it done: `cd frontend && npx tsc -b`. If a
preview/browser tool is available and the user hasn't said to skip
verification, start the dev server and check the actual rendered page
(`run-dev` skill has the exact commands) - a clean type-check does not
guarantee the JSX renders what was asked for.
