import Link from "next/link";

export default function NotFound() {
  return (
    <div className="reading">
      <h1>Page not found</h1>
      <p>
        The page may have moved. Try the <Link href="/issues">archive</Link> or{" "}
        <Link href="/search">search</Link>.
      </p>
    </div>
  );
}
