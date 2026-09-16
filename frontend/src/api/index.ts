import { createDemoSource } from "./demo";
import { createHttpSource } from "./http";
import type { DataSource, HealthInfo } from "./types";

export interface Connection {
  source: DataSource;
  health: HealthInfo;
  notice: string | null; // why demo data is used, if it is
}

/** Use the backend when it answers with loaded businesses, otherwise the demo data (VITE_DATA_MODE=auto). */
export async function connect(): Promise<Connection> {
  const mode = import.meta.env.VITE_DATA_MODE ?? "auto";
  const apiUrl = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
  let notice: string | null = null;
  if (mode !== "demo") {
    const http = createHttpSource(apiUrl);
    try {
      const health = await http.health();
      if (health.businessCount > 0 || mode === "api") return { source: http, health, notice: null };
      notice = `De backend op ${apiUrl} heeft nog geen ondernemingen geladen.`;
    } catch (error) {
      if (mode === "api") throw error;
      notice = `Backend niet bereikbaar op ${apiUrl}.`;
    }
  }
  const demo = await createDemoSource();
  return { source: demo, health: await demo.health(), notice };
}

export * from "./types";
