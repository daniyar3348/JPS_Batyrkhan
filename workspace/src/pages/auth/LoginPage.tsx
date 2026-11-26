import { Alert, Anchor, Button, Group, PasswordInput, Stack, Text, TextInput, Title } from "@mantine/core";
import { useForm } from "@mantine/form";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router";
import { ApiError, api, unwrap } from "../../api";
import { applySession, useMe } from "../../auth";
import { validateEmail } from "../../lib/forms";

/** Only allow redirects to pages of this app, never to another site. */
export function safeNext(value: string | null): string {
  return value?.startsWith("/") && !value.startsWith("//") ? value : "/";
}

export function LoginPage() {
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: me } = useMe();

  const form = useForm({
    initialValues: { email: "", password: "" },
    validate: {
      email: validateEmail,
      password: (value) => (value ? null : "Enter your password"),
    },
  });

  const login = useMutation({
    mutationFn: (values: typeof form.values) => unwrap(api.POST("/api/v1/auth/login", { body: values })),
    onSuccess: (session) => {
      applySession(queryClient, session);
      navigate(next, { replace: true });
    },
  });

  if (me) return <Navigate to={next} replace />;

  const error = login.error instanceof ApiError ? login.error : null;
  return (
    <form onSubmit={form.onSubmit((values) => login.mutate(values))} noValidate>
      <Stack>
        <Stack gap={4}>
          <Title order={2}>Sign in</Title>
          <Text c="dimmed" size="sm">
            Authors, reviewers and editors use the same account.
          </Text>
        </Stack>
        {error ? (
          <Alert color={error.code === "account_locked" ? "orange" : "red"}>{error.detail}</Alert>
        ) : null}
        <TextInput
          label="E-mail address"
          type="email"
          autoComplete="email"
          required
          {...form.getInputProps("email")}
        />
        <PasswordInput
          label="Password"
          autoComplete="current-password"
          required
          {...form.getInputProps("password")}
        />
        <Group justify="space-between">
          <Anchor component={Link} to="/forgot-password" size="sm">
            Forgot your password?
          </Anchor>
          <Button type="submit" loading={login.isPending}>
            Sign in
          </Button>
        </Group>
        <Text size="sm" ta="center" mt="xs">
          New to the journal?{" "}
          <Anchor component={Link} to="/register">
            Create an account
          </Anchor>
        </Text>
      </Stack>
    </form>
  );
}
