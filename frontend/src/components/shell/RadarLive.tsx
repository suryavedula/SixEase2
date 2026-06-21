import { createContext, useContext } from "react";

// Live-radar pulse (EPIC-08). AppShell holds an EventSource on /radar/stream and
// bumps this counter on every pushed change; the ChangeRadar widget — rendered
// deep via the registry — consumes it as a useEffect dependency to refetch /radar
// without a manual reload. A counter (not the event payload) keeps the contract
// trivial: any change in value means "something was pushed, go refresh".

export const RadarLiveContext = createContext<number>(0);

export function useRadarLive(): number {
  return useContext(RadarLiveContext);
}
