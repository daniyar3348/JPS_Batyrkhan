import type { MeOut } from "@jps/api-client";
import { Alert, Button, Center, Loader, Stack, Title } from "@mantine/core";
import { IconCircleCheck } from "@tabler/icons-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { Link, useSearchParams } from "react-router";
import { api, errorMessage, unwrap } from "../../api";
import { meQueryKey, useMe } from "../../auth";

export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const queryClient = useQueryClient();
  const { data: me } = useMe();
  const started = useRef(false);

  const verify = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/auth/verify-email", { body: { token } })),
    onSuccess: (user) => {
      // Show the confirmed state at once (no flash of the "confirm" banner), then refetch: this also
      // cancels a request for the current user that started before the confirmation and would be stale.
      queryClient.setQueryData<MeOut | null>(meQueryKey, (me) =>
        me && me.user.id === user.id ? { ...me, user } : me,
      );
      return queryClient.invalidateQueries({ queryKey: meQueryKey });
    },
  });

  useEffect(() => {
    // The link is single-use, so make sure it is sent once even when React renders twice in development.
    if (token && !started.current) {
      started.current = true;
      verify.mutate();
    }
  }, [token, verify]);

  return (
    <Stack>
      <Title order={2}>Confirm your e-mail address</Title>
      {!token ? (
        <Alert color="red">The link is incomplete. Open it again from the e-mail.</Alert>
      ) : verify.isError ? (
        <Alert color="red" title="This link does not work">
          {errorMessage(verify.error)} You can request a new link from your dashboard.
        </Alert>
      ) : verify.isSuccess ? (
        <Alert color="teal" icon={<IconCircleCheck />} title="Thank you">
          Your e-mail address {verify.data.email} is confirmed.
        </Alert>
      ) : (
        <Center py="md">
          <Loader />
        </Center>
      )}
      <Button component={Link} to={me ? "/" : "/login"} variant="light">
        {me ? "Go to the dashboard" : "Sign in"}
      </Button>
    </Stack>
  );
}
