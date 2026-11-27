import type { WorkflowOut } from "@jps/api-client";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { json, mockApi, renderPage } from "../test/render";
import { ParticipantsCard } from "./ParticipantsCard";

const EDITOR = {
  user: { id: 2, full_name: "Daniyar Chief", email: "chief@example.org" },
  role: "editor",
  recommend_only: false,
  assigned_at: "2026-11-27T10:00:00Z",
};

function workflowWith(changes: Partial<WorkflowOut>): WorkflowOut {
  return {
    stage: "copyediting",
    status: "queued",
    editors: [EDITOR],
    viewer: {
      is_author: false,
      is_editor: true,
      can_edit: false,
      can_manage: true,
      can_decide: true,
      recommend_only: false,
      production_roles: [],
    },
    ...changes,
  } as WorkflowOut;
}

describe("ParticipantsCard", () => {
  it("after acceptance, assigns a copyeditor", async () => {
    const calls = mockApi({
      "GET /api/v1/submissions/5/participant-candidates": () =>
        json(200, [{ id: 7, full_name: "Kamila Copy", email: "copy@example.org" }]),
      "POST /api/v1/submissions/5/participants": () => json(201, workflowWith({})),
    });
    renderPage(<ParticipantsCard submissionId={5} workflow={workflowWith({})} />);

    expect(screen.getByText("Daniyar Chief")).toBeInTheDocument();
    for (const role of ["Copyeditors", "Layout editors", "Proofreaders"]) {
      expect(screen.getByText(role)).toBeInTheDocument();
    }
    const copyeditors = screen.getByText("Copyeditors").closest("div")?.parentElement as HTMLElement;
    await userEvent.click(within(copyeditors).getByRole("button", { name: "Assign" }));
    await userEvent.click(await screen.findByPlaceholderText("Choose a person"));
    await userEvent.click(await screen.findByText("Kamila Copy (copy@example.org)"));
    const form = screen.getByRole("button", { name: "Cancel" }).parentElement as HTMLElement;
    await userEvent.click(within(form).getByRole("button", { name: "Assign" }));

    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const lookup = calls.find((c) => c.method === "GET");
    expect(lookup?.path).toBe("/api/v1/submissions/5/participant-candidates");
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      user_id: 7,
      role: "copyeditor",
      recommend_only: false,
      notify: true,
    });
  });

  it("before acceptance shows only editors, and nothing to change for others", () => {
    mockApi({});
    const viewer = { ...workflowWith({}).viewer, can_manage: false, can_decide: false, is_editor: false };
    renderPage(<ParticipantsCard submissionId={5} workflow={workflowWith({ stage: "review", viewer })} />);
    expect(screen.getByText("Editors")).toBeInTheDocument();
    expect(screen.queryByText("Copyeditors")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Assign" })).not.toBeInTheDocument();
  });
});
