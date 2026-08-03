import react from "@vitejs/plugin-react"
import { loadEnv } from "vite"
import { defineConfig } from "vitest/config"

export const DEFAULT_BACKEND_PORT = 8000

export function resolveBackendPort(
  environment: Record<string, string | undefined>,
): number {
  const rawPort =
    environment.VITE_RACS_BACKEND_PORT ?? String(DEFAULT_BACKEND_PORT)
  const port = Number(rawPort)

  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error("VITE_RACS_BACKEND_PORT must be a valid TCP port")
  }
  return port
}

export default defineConfig(({ mode }) => {
  const environment = loadEnv(mode, process.cwd(), "")
  const backendPort = resolveBackendPort(environment)

  return {
    plugins: [react()],
    server: {
      proxy: {
        "/api": `http://127.0.0.1:${backendPort}`,
      },
    },
    test: {
      environment: "jsdom",
    },
  }
})
