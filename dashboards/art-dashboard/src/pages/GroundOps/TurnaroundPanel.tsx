import { useQuery } from "@tanstack/react-query";
import { flightsApi } from "../../hooks/useApi";

interface TurnaroundTask {
  name: string;
  status: string;
  duration_min: number;
  started_at: string | null;
  completed_at: string | null;
}

interface TurnaroundPlan {
  aircraft_registration: string;
  arrival_flight_id: string;
  paired_departure_id: string | null;
  aircraft_type: string;
  is_complete: boolean;
  ready_for_boarding: boolean;
  critical_path_minutes: number;
  tasks: TurnaroundTask[];
}

export function TurnaroundPanel() {
  const turnaroundsQuery = useQuery({
    queryKey: ["turnarounds"],
    queryFn: () => flightsApi.turnarounds(),
    refetchInterval: 5_000,
  });

  const plans = (turnaroundsQuery.data?.turnarounds ?? []) as TurnaroundPlan[];
  const active = plans.filter((p) => !p.is_complete);

  if (active.length === 0) {
    return (
      <div className="bg-gray-800 rounded p-3">
        <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
          Active Turnarounds
        </h3>
        <div className="text-xs text-gray-400">No active turnarounds</div>
      </div>
    );
  }

  return (
    <div className="bg-gray-800 rounded p-3">
      <h3 className="text-xs text-gray-400 uppercase tracking-wide mb-2">
        Active Turnarounds ({active.length})
      </h3>
      <div className="space-y-2 max-h-48 overflow-y-auto">
        {active.map((plan) => (
          <div
            key={plan.aircraft_registration}
            className="bg-gray-900 rounded p-2 text-xs"
          >
            <div className="flex justify-between items-center mb-1">
              <span className="font-bold text-white">
                {plan.aircraft_registration}
              </span>
              <span className="text-gray-400">
                CP: {plan.critical_path_minutes}m
              </span>
            </div>
            <div className="flex gap-0.5">
              {plan.tasks.map((t) => (
                <div
                  key={t.name}
                  className={`h-2 flex-1 rounded-sm ${
                    t.status === "completed"
                      ? "bg-green-600"
                      : t.status === "in_progress"
                        ? "bg-blue-500 animate-pulse"
                        : "bg-gray-600"
                  }`}
                  title={`${t.name} (${t.duration_min}m) — ${t.status}`}
                />
              ))}
            </div>
            {plan.ready_for_boarding && (
              <div className="text-green-400 text-[10px] mt-1">
                Ready for boarding
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
