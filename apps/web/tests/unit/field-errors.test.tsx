import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FaqEditor } from "@/features/admin/faq/faq-editor";
import { matchApiFields } from "@/lib/api/field-errors";
import { ApiError } from "@/lib/api/errors";

import { errorEnvelope, jsonResponse, sessionBody, stubFetch, type StubbedCall } from "./helpers";
import { renderWithProviders } from "./render";

/* L5: a 422's details.fields (FastAPI locations such as "body.patient.full_name") mark the matching form fields. */

const validation = (fields: string[]) =>
  new ApiError({ status: 422, code: "VALIDATION_ERROR", message: "Please check these fields", details: { fields } });

describe("matchApiFields", () => {
  it("maps API field paths, with or without the body. prefix, to form fields", () => {
    const map = { "patient.full_name": "full_name", "patient.phone": "phone", answer: "answer" } as const;
    expect(matchApiFields(validation(["body.patient.full_name", "body.answer"]), map)).toEqual(["full_name", "answer"]);
    expect(matchApiFields(validation(["patient.phone"]), map)).toEqual(["phone"]);
  });

  it("matches nested paths under a mapped prefix", () => {
    expect(matchApiFields(validation(["body.aliases.2"]), { aliases: "aliasesText" })).toEqual(["aliasesText"]);
  });

  it("ignores unknown paths and non-validation errors", () => {
    expect(matchApiFields(validation(["query.date"]), { answer: "answer" })).toEqual([]);
    expect(matchApiFields(new ApiError({ status: 409, code: "CONFLICT", details: { fields: ["body.answer"] } }), { answer: "answer" })).toEqual([]);
  });
});

describe("FAQ form with a 422 from the API", () => {
  it("marks the rejected field instead of promising highlights it never shows", async () => {
    stubFetch((call: StubbedCall) => {
      if (call.url.startsWith("/api/v1/faq") && call.method === "GET") return jsonResponse(200, { items: [], page: 1, page_size: 100, total: 0 });
      if (call.url === "/api/v1/auth/me") return jsonResponse(200, sessionBody("admin"));
      if (call.url === "/api/v1/faq" && call.method === "POST") {
        return jsonResponse(422, errorEnvelope("VALIDATION_ERROR", "Please check these fields: body.answer", { details: { fields: ["body.answer"] } }));
      }
      throw new Error(`unexpected ${call.method} ${call.url}`);
    });
    renderWithProviders(<FaqEditor />);
    fireEvent.click(await screen.findByRole("button", { name: "Add the first answer" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Topic name"), { target: { value: "parking_info" } });
    fireEvent.change(within(dialog).getByLabelText("Answer"), { target: { value: "Behind the clinic." } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add answer" }));

    expect(await within(dialog).findByText("The clinic server didn't accept this. Check it and try again.")).toBeTruthy();
    expect(within(dialog).getByLabelText("Answer").getAttribute("aria-invalid")).toBe("true");
    expect(within(dialog).getByLabelText("Topic name").getAttribute("aria-invalid")).toBe("false");
    expect(within(dialog).getByText("Some details weren't accepted. Check the marked fields.")).toBeTruthy();
  });
});
