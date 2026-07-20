import "@testing-library/jest-dom/vitest"

import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { App } from "./App"

describe("App", () => {
  it("renders the engineering baseline shell", () => {
    render(<App />)

    expect(
      screen.getByRole("heading", { name: "Recoverable AI Customer Service" }),
    ).toBeVisible()
  })
})
