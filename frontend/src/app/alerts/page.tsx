import Card from "@/components/Card";
import StatusBadge from "@/components/StatusBadge";
import { getAlerts, getCLVReport } from "@/lib/api";
import type { LineAlertResponse, CLVReportResponse } from "@/lib/types";

export default async function AlertsPage() {
  let alerts: LineAlertResponse[] = [];
  let clv: CLVReportResponse | null = null;

  try {
    [alerts, clv] = await Promise.all([
      getAlerts({ hours: 24 }),
      getCLVReport(),
    ]);
  } catch {
    // API not reachable
  }

  const highAlerts = alerts.filter((a) => a.priority === "high");
  const mediumAlerts = alerts.filter((a) => a.priority === "medium");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Alerts & Intelligence</h1>
        <p className="text-sm text-[#888]">Line movements, CLV tracking, and market intelligence</p>
      </div>

      {/* CLV Summary */}
      <div className="grid gap-3 sm:grid-cols-4">
        <div className="rounded-lg border border-[#2a2a2a] bg-[#111] p-4">
          <p className="text-xs font-medium uppercase tracking-wider text-[#888]">Total Signals</p>
          <p className="mt-1 text-2xl font-bold">{clv?.total_signals ?? 0}</p>
        </div>
        <div className="rounded-lg border border-[#2a2a2a] bg-[#111] p-4">
          <p className="text-xs font-medium uppercase tracking-wider text-[#888]">CLV Tracked</p>
          <p className="mt-1 text-2xl font-bold">{clv?.signals_with_closing ?? 0}</p>
        </div>
        <div className="rounded-lg border border-[#2a2a2a] bg-[#111] p-4">
          <p className="text-xs font-medium uppercase tracking-wider text-[#888]">Positive CLV %</p>
          <p className={`mt-1 text-2xl font-bold ${(clv?.positive_clv_pct ?? 0) > 50 ? "text-green-400" : "text-[#888]"}`}>
            {clv?.positive_clv_pct !== null ? `${clv?.positive_clv_pct}%` : "—"}
          </p>
        </div>
        <div className="rounded-lg border border-[#2a2a2a] bg-[#111] p-4">
          <p className="text-xs font-medium uppercase tracking-wider text-[#888]">Market Efficiency</p>
          <p className="mt-1 text-2xl font-bold">
            {clv?.market_efficiency_score !== null ? clv?.market_efficiency_score?.toFixed(2) : "—"}
          </p>
        </div>
      </div>

      {/* High Priority Alerts */}
      <Card
        title={`Steam Moves (${highAlerts.length})`}
        subtitle="High priority — large, sudden line movements"
      >
        {highAlerts.length === 0 ? (
          <p className="text-sm text-[#666]">No steam moves detected in the last 24 hours.</p>
        ) : (
          <div className="space-y-2">
            {highAlerts.map((alert, i) => (
              <div
                key={`${alert.event_id}-${alert.bookmaker}-${alert.outcome}-${i}`}
                className="flex items-start justify-between rounded-md border border-red-500/20 bg-red-500/5 p-3"
              >
                <div>
                  <p className="text-sm font-medium">{alert.description}</p>
                  <p className="mt-0.5 text-xs text-[#888]">
                    {alert.bookmaker} &middot; {alert.outcome}
                  </p>
                </div>
                <div className="text-right">
                  <p className="font-mono text-sm">
                    {alert.old_odds.toFixed(2)} &rarr; {alert.new_odds.toFixed(2)}
                  </p>
                  <p className={`font-mono text-xs ${alert.odds_change_pct > 0 ? "text-green-400" : "text-red-400"}`}>
                    {alert.odds_change_pct > 0 ? "+" : ""}{alert.odds_change_pct}%
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Medium Priority Alerts */}
      <Card
        title={`Convergence & Stale Lines (${mediumAlerts.length})`}
        subtitle="Medium priority — soft books drifting toward sharp prices"
      >
        {mediumAlerts.length === 0 ? (
          <p className="text-sm text-[#666]">No convergence events in the last 24 hours.</p>
        ) : (
          <div className="space-y-2">
            {mediumAlerts.map((alert, i) => (
              <div
                key={`${alert.event_id}-${alert.bookmaker}-${alert.outcome}-${i}`}
                className="flex items-start justify-between rounded-md border border-yellow-500/20 bg-yellow-500/5 p-3"
              >
                <div>
                  <p className="text-sm font-medium">{alert.description}</p>
                  <p className="mt-0.5 text-xs text-[#888]">
                    {alert.bookmaker} &middot; {alert.outcome}
                  </p>
                </div>
                <div className="text-right">
                  <p className="font-mono text-sm">
                    {alert.old_odds.toFixed(2)} &rarr; {alert.new_odds.toFixed(2)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Bookmaker Softness */}
      {clv && clv.bookmaker_softness.length > 0 && (
        <Card title="Bookmaker Softness" subtitle="Which books are most exploitable">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#2a2a2a] text-left text-xs uppercase tracking-wider text-[#888]">
                  <th className="pb-2 pr-4">Bookmaker</th>
                  <th className="pb-2 pr-4 text-right">Signals</th>
                  <th className="pb-2 pr-4 text-right">Softness</th>
                  <th className="pb-2 pr-4 text-right">Mean CLV</th>
                  <th className="pb-2 text-right">Mean Edge</th>
                </tr>
              </thead>
              <tbody>
                {clv.bookmaker_softness
                  .sort((a, b) => b.softness_score - a.softness_score)
                  .map((book, i) => (
                    <tr key={book.bookmaker} className={`border-b border-[#1a1a1a] ${i % 2 === 0 ? "" : "bg-[#111]"}`}>
                      <td className="py-2 pr-4 font-medium">{book.bookmaker}</td>
                      <td className="py-2 pr-4 text-right font-mono">{book.total_signals}</td>
                      <td className="py-2 pr-4 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <div className="h-1.5 w-16 overflow-hidden rounded-full bg-[#333]">
                            <div
                              className="h-full rounded-full bg-green-500"
                              style={{ width: `${book.softness_score * 100}%` }}
                            />
                          </div>
                          <span className="font-mono text-xs">{(book.softness_score * 100).toFixed(0)}%</span>
                        </div>
                      </td>
                      <td className="py-2 pr-4 text-right font-mono">
                        {book.mean_clv !== null ? `${(book.mean_clv * 100).toFixed(2)}%` : "—"}
                      </td>
                      <td className="py-2 text-right font-mono text-green-400">
                        +{(book.mean_edge * 100).toFixed(1)}%
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
