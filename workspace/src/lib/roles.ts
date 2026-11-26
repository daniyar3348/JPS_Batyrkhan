import { type Role, roleValues } from "@jps/api-client";

export const ROLE_LABELS: Record<Role, string> = {
  admin: "Administrator",
  editor_in_chief: "Editor-in-chief",
  section_editor: "Section editor",
  reviewer: "Reviewer",
  author: "Author",
  copyeditor: "Copyeditor",
  layout_editor: "Layout editor",
  proofreader: "Proofreader",
  finance_manager: "Finance manager",
};

export const ROLE_DESCRIPTIONS: Record<Role, string> = {
  admin: "Journal settings, sections, users and roles",
  editor_in_chief: "All submissions; assigns editors and makes decisions",
  section_editor: "Submissions assigned to them",
  reviewer: "Can be invited to review",
  author: "Submits manuscripts",
  copyeditor: "Edits accepted manuscripts",
  layout_editor: "Prepares PDF and HTML galleys",
  proofreader: "Checks galleys before publication",
  finance_manager: "Invoices, payments and waivers",
};

export const ROLE_COLORS: Record<Role, string> = {
  admin: "red",
  editor_in_chief: "grape",
  section_editor: "violet",
  reviewer: "teal",
  author: "blue",
  copyeditor: "orange",
  layout_editor: "orange",
  proofreader: "orange",
  finance_manager: "yellow",
};

/** Roles in a stable, meaningful order (most privileged first). */
export const ROLES: readonly Role[] = roleValues;

export const EDITOR_ROLES: readonly Role[] = ["editor_in_chief", "section_editor"];
