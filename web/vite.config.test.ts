import { describe, expect, it } from "vitest"

import { DEFAULT_BACKEND_PORT, resolveBackendPort } from "./vite.config"

describe("Vite backend proxy port", () => {
  it("uses 8000 by default", () => {
    expect(resolveBackendPort({})).toBe(DEFAULT_BACKEND_PORT)
  })

  it("uses the same explicitly configured local backend port", () => {
    expect(resolveBackendPort({ VITE_RACS_BACKEND_PORT: "18000" })).toBe(18000)
  })

  it.each(["0", "65536", "not-a-port"])("rejects invalid port %s", (port) => {
    expect(() => resolveBackendPort({ VITE_RACS_BACKEND_PORT: port })).toThrow(
      "VITE_RACS_BACKEND_PORT must be a valid TCP port",
    )
  })
})
