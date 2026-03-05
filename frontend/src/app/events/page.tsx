import Card from "@/components/Card";
import StatusBadge from "@/components/StatusBadge";
import { getEvents } from "@/lib/api";
import type { EventResponse } from "@/lib/types";

export default async function EventsPage() {
  let events: EventResponse[] = [];

  try {
    events = await getEvents({ limit: 50 });
  } catch {
    // API not reachable
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Events</h1>
        <p className="text-sm text-[#888]">Upcoming games across all supported sports</p>
      </div>

      <Card title={`${events.length} Events`} subtitle="Ordered by commence time">
        {events.length === 0 ? (
          <p className="text-sm text-[#666]">No events found. The ingestion pipeline may not be running.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#2a2a2a] text-left text-xs uppercase tracking-wider text-[#888]">
                  <th className="pb-2 pr-4">Sport</th>
                  <th className="pb-2 pr-4">Matchup</th>
                  <th className="pb-2 pr-4">Time</th>
                  <th className="pb-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {events.map((ev, i) => (
                  <tr key={ev.id} className={`border-b border-[#1a1a1a] ${i % 2 === 0 ? "" : "bg-[#111]"}`}>
                    <td className="py-2.5 pr-4">
                      <span className="rounded bg-[#222] px-2 py-0.5 text-xs font-medium text-[#aaa]">
                        {ev.sport === "baseball_mlb" ? "MLB" : ev.sport === "mma_mixed_martial_arts" ? "UFC" : ev.sport}
                      </span>
                    </td>
                    <td className="py-2.5 pr-4">
                      <span className="font-medium">{ev.home_team}</span>
                      <span className="text-[#666]"> vs </span>
                      <span className="font-medium">{ev.away_team}</span>
                    </td>
                    <td className="py-2.5 pr-4 text-[#888]">
                      {ev.commence_time
                        ? new Date(ev.commence_time).toLocaleString("en-US", {
                            month: "short",
                            day: "numeric",
                            hour: "numeric",
                            minute: "2-digit",
                          })
                        : "TBD"}
                    </td>
                    <td className="py-2.5">
                      <StatusBadge status={ev.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
