/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  readonly VITE_ENRICH_URL?: string;
  readonly VITE_DATA_MODE?: "auto" | "api" | "demo";
  readonly VITE_MUNICIPALITY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
