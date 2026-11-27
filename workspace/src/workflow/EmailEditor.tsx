import { Alert, Group, Stack, Switch, Text, Textarea, TextInput } from "@mantine/core";
import { IconMail } from "@tabler/icons-react";

export interface EmailDraft {
  subject: string;
  body: string;
}

/**
 * An e-mail the editor can read and change before it is sent.
 * With `send`/`onSendChange` the editor can also choose not to send it.
 */
export function EmailEditor({
  value,
  onChange,
  to,
  send,
  onSendChange,
  sendLabel = "Send this e-mail",
  hint,
}: {
  value: EmailDraft;
  onChange: (value: EmailDraft) => void;
  to?: string[];
  send?: boolean;
  onSendChange?: (send: boolean) => void;
  sendLabel?: string;
  hint?: string;
}) {
  const enabled = send ?? true;
  return (
    <Stack gap="xs">
      {onSendChange ? (
        <Switch
          label={sendLabel}
          checked={enabled}
          onChange={(event) => onSendChange(event.currentTarget.checked)}
        />
      ) : null}
      {enabled ? (
        <>
          {to?.length ? (
            <Group gap={6}>
              <IconMail size={16} color="var(--mantine-color-dimmed)" />
              <Text size="sm" c="dimmed">
                To: {to.join(", ")}
              </Text>
            </Group>
          ) : null}
          <TextInput
            label="Subject"
            value={value.subject}
            onChange={(event) => onChange({ ...value, subject: event.currentTarget.value })}
          />
          <Textarea
            label="Message"
            autosize
            minRows={8}
            maxRows={22}
            value={value.body}
            onChange={(event) => onChange({ ...value, body: event.currentTarget.value })}
          />
          {hint ? (
            <Text size="xs" c="dimmed">
              {hint}
            </Text>
          ) : null}
        </>
      ) : (
        <Alert color="gray" variant="light">
          No e-mail will be sent.
        </Alert>
      )}
    </Stack>
  );
}
