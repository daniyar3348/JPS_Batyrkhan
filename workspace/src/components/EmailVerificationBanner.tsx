import { Alert, Button, Group, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconMailExclamation } from "@tabler/icons-react";
import { useMutation } from "@tanstack/react-query";
import { api, unwrap } from "../api";
import { useSignedInUser } from "../auth";
import { showRequestError } from "../lib/forms";

export function EmailVerificationBanner() {
  const me = useSignedInUser();
  const resend = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/me/email-verification")),
    onSuccess: () =>
      notifications.show({ color: "teal", message: `We sent a new confirmation link to ${me.user.email}.` }),
    onError: (error) => showRequestError(error),
  });

  if (me.user.email_verified) return null;
  return (
    <Alert color="yellow" icon={<IconMailExclamation />} title="Confirm your e-mail address">
      <Group justify="space-between" gap="sm">
        <Text size="sm">
          We sent a confirmation link to <b>{me.user.email}</b>. Open it to receive notifications about your
          manuscripts.
        </Text>
        <Button
          size="xs"
          variant="light"
          color="yellow"
          loading={resend.isPending}
          onClick={() => resend.mutate()}
        >
          Send the link again
        </Button>
      </Group>
    </Alert>
  );
}
