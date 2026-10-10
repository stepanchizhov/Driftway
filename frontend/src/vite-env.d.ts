/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}

/** The commit the app was built from - see vite.config.ts. */
declare const __BUILD_COMMIT__: string;
