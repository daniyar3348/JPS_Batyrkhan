import { NextResponse } from "next/server";
import { config } from "@/lib/config";

/** "Submit a manuscript": the workspace, which asks the author to sign in or register first. */
export function GET() {
  return NextResponse.redirect(`${config.workspaceUrl}/submissions/new`, 307);
}
