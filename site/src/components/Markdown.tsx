import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** Texts written in the workspace (pages, announcements). Raw HTML in them is not rendered. */
export function Markdown({ children }: { children: string }) {
  return (
    <div className="prose">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{
          a: ({ href, children: text }) =>
            href?.startsWith("http") ? (
              <a href={href} rel="noopener noreferrer">
                {text}
              </a>
            ) : (
              <a href={href}>{text}</a>
            ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}

/** Plain text with blank lines between paragraphs (abstracts). */
export function Paragraphs({ text, className }: { text: string; className?: string }) {
  return (
    <div className={className}>
      {text
        .split(/\n\s*\n/)
        .map((paragraph) => paragraph.trim())
        .filter(Boolean)
        .map((paragraph) => (
          <p key={paragraph.slice(0, 40)}>{paragraph}</p>
        ))}
    </div>
  );
}
