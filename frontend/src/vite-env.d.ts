/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  /** The app's final address; set once the move is verified (docs/ANDROID.md). */
  readonly VITE_CANONICAL_ORIGIN?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}

/** The commit the app was built from - see vite.config.ts. */
declare const __BUILD_COMMIT__: string;
