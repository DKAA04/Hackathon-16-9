import { createClient } from "@supabase/supabase-js";

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;

export const supabase =
  supabaseUrl && supabaseKey
    ? createClient(supabaseUrl, supabaseKey, {
        auth: {
          persistSession: true,
          autoRefreshToken: true,
          detectSessionInUrl: true,
        },
      })
    : null;

export type SupabaseConnectionState =
  | "checking"
  | "connected"
  | "configured"
  | "missing"
  | "error";

export async function checkSupabaseConnection(): Promise<{
  state: SupabaseConnectionState;
  detail: string;
}> {
  if (!supabase) {
    return { state: "missing", detail: "Supabase environment variables are missing." };
  }

  // The project sample used a `todos` table, so use it only as a lightweight
  // connectivity probe. CivicLens itself does not depend on this table.
  const { error } = await supabase
    .from("todos")
    .select("id", { head: true, count: "exact" })
    .limit(1);

  if (!error) {
    return { state: "connected", detail: "Supabase REST access is live." };
  }

  const message = error.message.toLowerCase();
  const code = (error as { code?: string }).code;
  if (
    code === "PGRST205" ||
    code === "42P01" ||
    message.includes("relation") ||
    message.includes("could not find the table")
  ) {
    return {
      state: "configured",
      detail: "Supabase client works; sample `todos` table is unavailable.",
    };
  }

  return { state: "error", detail: error.message };
}
