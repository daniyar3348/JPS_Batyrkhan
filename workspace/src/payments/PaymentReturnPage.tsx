import { Alert, Button, Card, Center, Group, Loader, Stack, Text, Title } from "@mantine/core";
import { IconAlertTriangle, IconCircleCheck, IconClock, IconX } from "@tabler/icons-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api, unwrap } from "../api";
import { QueryState } from "../components/common";
import { money } from "./labels";
import { billingKey } from "./queries";

const WAIT_MS = 60_000;

/**
 * Where the payment provider sends the payer back. Arriving here proves nothing: the page asks the
 * server, which asks the provider, and shows the result once the provider has confirmed it.
 */
export function PaymentReturnPage() {
  const [params] = useSearchParams();
  const paymentId = Number(params.get("payment"));
  const cancelled = params.has("cancelled");
  const queryClient = useQueryClient();
  const [startedAt] = useState(() => Date.now());

  // Once, on arrival: ask the server to check (and finish, e.g. PayPal's capture) with the provider.
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => {
    if (!paymentId || cancelled) return;
    unwrap(api.POST("/api/v1/payments/{payment_id}/confirm", { params: { path: { payment_id: paymentId } } }))
      .catch(() => undefined)
      .finally(() => setConfirmed(true));
  }, [paymentId, cancelled]);

  // Then watch the payment until the provider's notification has been recorded.
  const status = useQuery({
    queryKey: ["payment", paymentId],
    queryFn: () =>
      unwrap(api.GET("/api/v1/payments/{payment_id}", { params: { path: { payment_id: paymentId } } })),
    enabled: paymentId > 0 && !cancelled && confirmed,
    refetchInterval: (query) =>
      query.state.data?.status === "pending" && Date.now() - startedAt < WAIT_MS ? 2000 : false,
  });

  const data = status.data;
  useEffect(() => {
    if (data && data.status !== "pending") {
      queryClient.invalidateQueries({ queryKey: billingKey(data.submission_id) });
    }
  }, [data, queryClient]);

  const back = data ? `/submissions/${data.submission_id}?tab=fee` : "/submissions";
  let content: React.ReactNode;
  if (cancelled) {
    content = (
      <Alert color="gray" icon={<IconX />} title="Payment cancelled">
        Nothing was charged. You can pay later from the manuscript's page.
      </Alert>
    );
  } else if (!data) {
    content = (
      <QueryState isPending={status.isPending} error={status.error} onRetry={() => status.refetch()} />
    );
  } else if (data.status === "succeeded" || data.invoice_status === "paid") {
    content = (
      <Alert color="teal" icon={<IconCircleCheck />} title="Thank you, the payment was received">
        {money(data.amount, data.currency)} for invoice {data.invoice_number}. A receipt has been sent to you
        by e-mail and can be downloaded from the manuscript's page.
      </Alert>
    );
  } else if (data.status === "failed" || data.status === "cancelled") {
    content = (
      <Alert color="red" icon={<IconAlertTriangle />} title="The payment did not go through">
        Nothing was charged. You can try again, or choose another payment method.
      </Alert>
    );
  } else if (Date.now() - startedAt < WAIT_MS) {
    content = (
      <Center py="md">
        <Group gap="sm">
          <Loader size="sm" />
          <Text>Waiting for the payment provider to confirm…</Text>
        </Group>
      </Center>
    );
  } else {
    content = (
      <Alert color="blue" icon={<IconClock />} title="Not confirmed yet">
        The provider has not confirmed the payment yet. If you were charged, it will be recorded
        automatically; you will receive a receipt by e-mail.
      </Alert>
    );
  }

  return (
    <Center py="xl">
      <Card withBorder padding="xl" maw={560} w="100%">
        <Stack>
          <Title order={3}>Payment</Title>
          {content}
          <Group justify="flex-end">
            <Button component={Link} to={back} variant="light">
              Back to the manuscript
            </Button>
          </Group>
        </Stack>
      </Card>
    </Center>
  );
}
