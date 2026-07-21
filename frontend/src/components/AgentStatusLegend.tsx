export default function AgentStatusLegend() {
  return (
    <div className="panel">
      <div className="status-legend">
        <div className="status-legend-item">
          <span className="pill open">WATCHING</span>
          <span className="legend-text">A stock being tracked that hasn't yet met the entry criteria.</span>
        </div>
        <div className="status-legend-item">
          <span className="pill buy">BREAKOUT</span>
          <span className="legend-text">Entry criteria are confirmed right now - this is a live, actionable signal.</span>
        </div>
        <div className="status-legend-item">
          <span className="pill buy">BUY IDEA</span>
          <span className="legend-text">
            A Recommending agent's LLM flagged this as a buy right now. Idea only - it doesn't place trades; use a
            manual trade or an Execution agent to act on it.
          </span>
        </div>
        <div className="status-legend-item">
          <span className="pill sell">SELL IDEA</span>
          <span className="legend-text">
            Same as BUY IDEA, but the LLM's read is a sell. Idea only - it doesn't place trades.
          </span>
        </div>
        <div className="status-legend-item">
          <span className="pill buy">BUY SIGNAL</span>
          <span className="legend-text">
            An Execution agent mirrored this buy from the Recommending agent's LLM and will enter it automatically on
            its next scan - priced with this agent's own target/stop-loss/qty. You can also act on it now via the Buy
            button.
          </span>
        </div>
        <div className="status-legend-item">
          <span className="pill sell">SELL SIGNAL</span>
          <span className="legend-text">Same as BUY SIGNAL, but the mirrored signal is a sell.</span>
        </div>
      </div>
    </div>
  );
}
