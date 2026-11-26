import { Alert, Anchor, Button, Center, Loader, PasswordInput, Stack, Text, Title } from "@mantine/core";
import { useForm } from "@mantine/form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router";
import { api, errorMessage, unwrap } from "../../api";
import { applySession } from "../../auth";
import { ConsentFields } from "../../components/ConsentFields";
import { PASSWORD_MIN_LENGTH, showRequestError, validatePassword } from "../../lib/forms";

/** Choose a new password from an e-mailed link. Invitation links also ask for the consents. */
function SetPasswordPage({ invitation }: { invitation: boolean }) {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const link = useQuery({
    queryKey: ["token-info", token],
    queryFn: () => unwrap(api.POST("/api/v1/auth/token-info", { body: { token } })),
    enabled: token.length > 0,
    retry: false,
    staleTime: Number.POSITIVE_INFINITY,
  });
  const isInvitation = link.data?.kind === "invitation" || invitation;

  const form = useForm({
    initialValues: {
      password: "",
      confirm: "",
      accept_privacy_policy: false,
      accept_cross_border_transfer: false,
    },
    validate: {
      password: validatePassword,
      confirm: (value, values) => (value === values.password ? null : "The passwords do not match"),
      accept_privacy_policy: (value) => (!isInvitation || value ? null : "Required to activate your account"),
      accept_cross_border_transfer: (value) =>
        !isInvitation || value ? null : "Required to activate your account",
    },
  });

  const save = useMutation({
    mutationFn: ({ confirm: _confirm, ...values }: typeof form.values) =>
      unwrap(api.POST("/api/v1/auth/password-reset/confirm", { body: { token, ...values } })),
    onSuccess: (session) => {
      applySession(queryClient, session);
      navigate("/", { replace: true });
    },
    onError: (error) => showRequestError(error, form),
  });

  const title = isInvitation ? "Accept your invitation" : "Choose a new password";
  if (!token || link.isError) {
    return (
      <Stack>
        <Title order={2}>{title}</Title>
        <Alert color="red" title="This link does not work">
          {token ? errorMessage(link.error) : "The link is incomplete. Open it again from the e-mail."}
        </Alert>
        <Anchor component={Link} to={isInvitation ? "/login" : "/forgot-password"} size="sm">
          {isInvitation ? "Go to sign in" : "Request a new reset link"}
        </Anchor>
      </Stack>
    );
  }
  if (link.isPending) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }

  return (
    <form onSubmit={form.onSubmit((values) => save.mutate(values))} noValidate>
      <Stack>
        <Stack gap={4}>
          <Title order={2}>{title}</Title>
          <Text c="dimmed" size="sm">
            {isInvitation ? "Welcome, " : "Account: "}
            <b>{isInvitation ? link.data.full_name : link.data.email}</b>
            {isInvitation ? ". Choose a password to activate your account." : null}
          </Text>
        </Stack>
        <PasswordInput
          label="New password"
          description={`At least ${PASSWORD_MIN_LENGTH} characters`}
          autoComplete="new-password"
          required
          {...form.getInputProps("password")}
        />
        <PasswordInput
          label="Repeat the password"
          autoComplete="new-password"
          required
          {...form.getInputProps("confirm")}
        />
        {isInvitation ? (
          <ConsentFields
            privacy={form.getInputProps("accept_privacy_policy", { type: "checkbox" })}
            crossBorder={form.getInputProps("accept_cross_border_transfer", { type: "checkbox" })}
          />
        ) : null}
        <Button type="submit" loading={save.isPending}>
          {isInvitation ? "Activate account" : "Save password and sign in"}
        </Button>
      </Stack>
    </form>
  );
}

export function ResetPasswordPage() {
  return <SetPasswordPage invitation={false} />;
}

export function AcceptInvitationPage() {
  return <SetPasswordPage invitation />;
}
