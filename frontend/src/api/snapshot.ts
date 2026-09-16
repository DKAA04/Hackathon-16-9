// The supplied KBO snapshot (read-only, straight from backend/data/reference).
import rawUrl from "../../../backend/data/reference/schoten-kbo-1000-2026-09-07.geojson?url";
import metadata from "../../../backend/data/reference/source-metadata.json";
import { cleanKbo } from "./cleaning";

export const snapshotMeta = {
  name: metadata.dataset,
  publisher: metadata.publisher,
  retrievedOn: metadata.retrieved_on.slice(0, 10),
  note: "De exacte KBO-datum staat niet in de bron; de uitgever meldt 1 tot 3 dagen vertraging.",
  attribution: metadata.attribution,
  licenceUrl: metadata.licence_url,
  completeMunicipality: metadata.complete_municipality,
};

let rawPromise: Promise<unknown> | null = null;

export function loadRawSnapshot(): Promise<unknown> {
  rawPromise ??= fetch(rawUrl).then((res) => {
    if (!res.ok) throw new Error(`KBO-bestand niet gevonden (${res.status})`);
    return res.json();
  });
  return rawPromise;
}

export async function cleanSnapshot() {
  return cleanKbo(await loadRawSnapshot());
}
