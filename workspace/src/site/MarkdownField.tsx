import { Group, Paper, SegmentedControl, Stack, Text, Textarea, Typography } from "@mantine/core";
import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

export const MARKDOWN_HELP =
  "Markdown: ## for a heading, **bold**, *italic*, - for a list item, [text](https://…) for a link.";

/** Markdown with a preview of how the site shows it. Raw HTML is not rendered, here or on the site. */
export function MarkdownField({
  label,
  value,
  onChange,
  error,
  minRows = 10,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  error?: string | null;
  minRows?: number;
}) {
  const [mode, setMode] = useState<"write" | "preview">("write");
  return (
    <Stack gap={6}>
      <Group justify="space-between" align="flex-end">
        <Text size="sm" fw={500}>
          {label}
        </Text>
        <SegmentedControl
          size="xs"
          value={mode}
          onChange={(next) => setMode(next as "write" | "preview")}
          data={[
            { value: "write", label: "Write" },
            { value: "preview", label: "Preview" },
          ]}
        />
      </Group>
      {mode === "write" ? (
        <Textarea
          aria-label={label}
          autosize
          minRows={minRows}
          maxRows={40}
          value={value}
          error={error}
          onChange={(event) => onChange(event.currentTarget.value)}
          styles={{ input: { fontFamily: "var(--mantine-font-family-monospace)", fontSize: 13 } }}
        />
      ) : (
        <Paper withBorder p="md" mih={120} data-testid="markdown-preview">
          {value.trim() ? (
            <Typography>
              <Markdown remarkPlugins={[remarkGfm]}>{value}</Markdown>
            </Typography>
          ) : (
            <Text size="sm" c="dimmed">
              Nothing to preview yet.
            </Text>
          )}
        </Paper>
      )}
      <Text size="xs" c="dimmed">
        {MARKDOWN_HELP}
      </Text>
    </Stack>
  );
}
