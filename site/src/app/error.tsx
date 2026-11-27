"use client";

/** Shown only when a page has never been built and the platform cannot be reached. */
export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <div className="reading">
      <h1>Temporarily unavailable</h1>
      <p>This page cannot be shown at the moment. Please try again in a few minutes.</p>
      <button type="button" className="button" onClick={reset}>
        Try again
      </button>
    </div>
  );
}
