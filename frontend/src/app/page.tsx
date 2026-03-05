import Card from "@/components/Card";
import MetricBox from "@/components/MetricBox";
import StatusBadge from "@/components/StatusBadge";
import { getSignals, getRiskState, getCalibration, getHealth, getQuota } from "@/lib/api";
import type { SignalResponse, RiskStateResponse, CalibrationResponse } from "@/lib/types";

async function DashboardData() {
  let signals: SignalResponse[] = [];
  let risk: RiskStateResponse | null = null;
  let calibration: CalibrationResponse | null = null;
  let healthStatus = "unknown";
  let quotaRemaining: number | null = null;

  try {
    [signals, risk, calibration] = await Promise.all([
      getSignals({ limit: 10 }),
      getRiskState(),
      getCalibration(),
    ]);
  } catch {
    // API not reachable — show empty state
  }

  try {
    const health = await getHealth();
    healthStatus = health.status;
  } catch {
    // ignore
  }

  try {
    const quota = await getQuota();
    quotaRemaining = quota.requests_remaining;
  } catch {
    // ignore
  }

  return { signals, risk, calibration, healthStatus, quotaRemaining };
}

export default async function Dashboard() {
  const { signals, risk, calibration, healthStatus, quotaRemaining } = await DashboardData();

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Dashboard</h1>
          <p className="text-sm text-[#888]">Positive EV Signal Engine</p>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge status={healthStatus} size="md" />
          {quotaRemaining !== null && (
            <span className="text-xs text-[#888]">{quotaRemaining} API calls left</span>
          )}
        </div>
      </div>

      {/* Risk State Metrics */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
        <MetricBox
          label="Risk Level"
          value={risk?.risk_level ?? "—"}
          color={
            risk?.risk_level === "aggressive" ? "green" :
            risk?.risk_level === "cautious" ? "yellow" :
            risk?.risk_level === "defensive" ? "red" : "blue"
          }
        />
        <MetricBox
          label="Bankroll"
          value={risk ? `$${risk.current_bankroll.toFixed(0)}` : "—"}
          subtext={risk ? `Peak: $${risk.peak_bankroll.toFixed(0)}` : undefined}
        />
        <MetricBox
          label="Drawdown"
          value={risk ? `${risk.drawdown_pct}%` : "—"}
          color={
            (risk?.drawdown_pct ?? 0) > 20 ? "red" :
            (risk?.drawdown_pct ?? 0) > 10 ? "yellow" : "green"
          }
        />
        <MetricBox
          label="Kelly Mult"
          value={risk ? `${risk.kelly_multiplier}x` : "—"}
        />
        <MetricBox
          label="Active Exposure"
          value={risk ? `${risk.active_exposure_pct}%` : "—"}
          subtext={risk ? `$${risk.active_exposure.toFixed(0)}` : undefined}
        />
        <MetricBox
          label="Total P&L"
          value={risk ? `$${risk.total_pnl.toFixed(0)}` : "—"}
          color={(risk?.total_pnl ?? 0) >= 0 ? "green" : "red"}
        />
      </div>

      {/* Signals Table */}
      <Card title="Golden Plays" subtitle="Current +EV signals sorted by edge">
        {signals.length === 0 ? (
          <p className="text-sm text-[#666]">No active signals. Waiting for edges to appear...</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#2a2a2a] text-left text-xs uppercase tracking-wider text-[#888]">
                  <th className="pb-2 pr-4">Event</th>
                  <th className="pb-2 pr-4">Outcome</th>
                  <th className="pb-2 pr-4">Book</th>
                  <th className="pb-2 pr-4 text-right">Odds</th>
                  <th className="pb-2 pr-4 text-right">Model %</th>
                  <th className="pb-2 pr-4 text-right">Edge %</th>
                  <th className="pb-2 pr-4 text-right">Kelly %</th>
                  <th className="pb-2 text-right">Stake</th>
                </tr>
              </thead>
              <tbody>
                {signals.map((s, i) => (
                  <tr key={`${s.event_id}-${s.outcome}-${s.bookmaker}`} className={`border-b border-[#1a1a1a] ${i % 2 === 0 ? "" : "bg-[#111]"}`}>
                    <td className="py-2 pr-4">
                      <span className="font-medium">{s.home_team}</span>
                      <span className="text-[#666]"> vs </span>
                      <span className="font-medium">{s.away_team}</span>
                    </td>
                    <td className="py-2 pr-4 font-medium text-blue-400">{s.outcome}</td>
                    <td className="py-2 pr-4 text-[#888]">{s.bookmaker}</td>
                    <td className="py-2 pr-4 text-right font-mono">{s.decimal_odds.toFixed(2)}</td>
                    <td className="py-2 pr-4 text-right font-mono">{(s.model_prob * 100).toFixed(1)}%</td>
                    <td className="py-2 pr-4 text-right font-mono text-green-400">+{s.edge_pct.toFixed(1)}%</td>
                    <td className="py-2 pr-4 text-right font-mono">{s.kelly_fraction_pct.toFixed(1)}%</td>
                    <td className="py-2 text-right font-mono font-bold">${s.recommended_stake.toFixed(0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Calibration */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Model Calibration" subtitle="Brier score tracking">
          {calibration && calibration.n_resolved > 0 ? (
            <div className="space-y-3">
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <p className="text-xs text-[#888]">Ensemble Brier</p>
                  <p className="text-lg font-bold">{calibration.brier_ensemble?.toFixed(4) ?? "—"}</p>
                </div>
                <div>
                  <p className="text-xs text-[#888]">Sharp Brier</p>
                  <p className="text-lg font-bold">{calibration.brier_sharp?.toFixed(4) ?? "—"}</p>
                </div>
                <div>
                  <p className="text-xs text-[#888]">Edge Over Sharp</p>
                  <p className={`text-lg font-bold ${(calibration.edge_over_sharp ?? 0) > 0 ? "text-green-400" : "text-red-400"}`}>
                    {calibration.edge_over_sharp !== null ? `${calibration.edge_over_sharp > 0 ? "+" : ""}${calibration.edge_over_sharp.toFixed(4)}` : "—"}
                  </p>
                </div>
              </div>
              <p className="text-xs text-[#666]">
                {calibration.n_resolved} / {calibration.n_predictions} predictions resolved
              </p>
            </div>
          ) : (
            <p className="text-sm text-[#666]">
              No resolved predictions yet. Calibration data will appear after events complete.
            </p>
          )}
        </Card>

        <Card title="Betting Stats" subtitle="Performance summary">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <p className="text-xs text-[#888]">Total Bets</p>
              <p className="text-lg font-bold">{risk?.total_bets ?? 0}</p>
            </div>
            <div>
              <p className="text-xs text-[#888]">Win Rate</p>
              <p className="text-lg font-bold">
                {risk?.recent_win_rate !== null && risk?.recent_win_rate !== undefined
                  ? `${(risk.recent_win_rate * 100).toFixed(1)}%`
                  : "—"}
              </p>
            </div>
            <div>
              <p className="text-xs text-[#888]">Max Stake</p>
              <p className="text-lg font-bold">{risk ? `${(risk.max_stake_fraction * 100).toFixed(0)}%` : "—"}</p>
            </div>
            <div>
              <p className="text-xs text-[#888]">Portfolio Cap</p>
              <p className="text-lg font-bold">{risk ? `${(risk.max_portfolio_exposure * 100).toFixed(0)}%` : "—"}</p>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
