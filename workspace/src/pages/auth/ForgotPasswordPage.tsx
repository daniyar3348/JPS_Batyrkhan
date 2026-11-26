import { Alert, Anchor, Button, Stack, Text, TextInput, Title } from "@mantine/core";
import { useForm } from "@mantine/form";
import { IconMailCheck } from "@tabler/icons-react";
import { useMutation } from "@tanstack/react-query";
import { Link } from "react-router";
import { api, unwrap } from "../../api";
import { showRequestError, validateEmail } from "../../lib/forms";

export function ForgotPasswordPage() {
  const form = useForm({ initialValues: { email: "" }, validate: { email: validateEmail } });
  const request = useMutation({
    mutationFn: (email: string) => unwrap(api.POST("/api/v1/auth/password-reset", { body: { email } })),
    onError: (error) => showRequestError(error, form),
  });

  return (
    <Stack>
      <Stack gap={4}>
        <Title order={2}>Reset your password</Title>
        <Text c="dimmed" size="sm">
          Enter the e-mail address of your account and we will send you a link to choose a new password.
        </Text>
      </Stack>
      {request.isSuccess ? (
        <Alert color="teal" icon={<IconMailCheck />} title="Check your inbox">
          If an account exists for {form.values.email}, a reset link is on its way. The link works for one
          hour.
        </Alert>
      ) : (
        <form onSubmit={form.onSubmit(({ email }) => request.mutate(email))} noValidate>
          <Stack>
            <TextInput
              label="E-mail address"
              type="email"
              autoComplete="email"
              required
              {...form.getInputProps("email")}
            />
            <Button type="submit" loading={request.isPending}>
              Send reset link
            </Button>
          </Stack>
        </form>
      )}
      <Anchor component={Link} to="/login" size="sm" ta="center">
        Back to sign in
      </Anchor>
    </Stack>
  );
}
