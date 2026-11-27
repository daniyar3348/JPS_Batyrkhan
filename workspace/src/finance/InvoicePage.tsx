import type { InvoiceOut, PaymentOut } from "@jps/api-client";
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Modal,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { IconBan, IconBuildingBank, IconDownload, IconReceiptRefund } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api, unwrap } from "../api";
import { PageHeader, QueryState } from "../components/common";
import { formatDate, formatDateTime } from "../lib/format";
import { notifySaved, showRequestError } from "../lib/forms";
import { INVOICE_STATUS, look, METHOD_LABELS, money, PAYMENT_STATUS } from "../payments/labels";

const invoiceKey = (id: number) => ["payments", "invoice", id] as const;

/** Money as the API expects it: a string with two decimals. */
function amountText(value: number): string {
  return value.toFixed(2);
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

/** What has come in for the invoice so far. */
function received(invoice: InvoiceOut): number {
  return invoice.payments
    .filter((payment) => payment.status === "succeeded")
    .reduce((sum, payment) => sum + Number(payment.amount), 0);
}

/** What can still be refunded from a payment: not yet refunded, and not already asked for. */
function refundable(payment: PaymentOut): number {
  const reserved = payment.refunds
    .filter((refund) => refund.status !== "failed")
    .reduce((sum, refund) => sum + Number(refund.amount), 0);
  return Math.max(Number(payment.amount) - reserved, 0);
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Group justify="space-between" wrap="nowrap" gap="md">
      <Text size="sm" c="dimmed">
        {label}
      </Text>
      <Text size="sm" ta="right">
        {children}
      </Text>
    </Group>
  );
}

function TransferModal({
  invoice,
  opened,
  onClose,
  onSaved,
}: {
  invoice: InvoiceOut;
  opened: boolean;
  onClose: () => void;
  onSaved: (invoice: InvoiceOut) => void;
}) {
  const outstanding = Math.max(Number(invoice.total) - received(invoice), 0);
  const [amount, setAmount] = useState(amountText(outstanding));
  const [reference, setReference] = useState("");
  const [paidOn, setPaidOn] = useState(today());
  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/payments/invoices/{invoice_id}/transfers", {
          params: { path: { invoice_id: invoice.id } },
          body: { amount, reference, paid_on: paidOn },
        }),
      ),
    onSuccess: (saved) => {
      onSaved(saved);
      notifySaved("Bank transfer recorded");
      onClose();
    },
    onError: (error) => showRequestError(error),
  });
  return (
    <Modal opened={opened} onClose={onClose} title="Record a bank transfer">
      <Stack>
        <Text size="sm" c="dimmed">
          Record money that reached the journal's bank account. The invoice is marked paid once the payments
          cover its total.
        </Text>
        <TextInput
          label={`Amount received, ${invoice.currency}`}
          inputMode="decimal"
          value={amount}
          onChange={(event) => setAmount(event.currentTarget.value)}
        />
        <TextInput
          label="Bank reference"
          description="From the bank statement, so the payment can be traced."
          value={reference}
          onChange={(event) => setReference(event.currentTarget.value)}
        />
        <TextInput
          type="date"
          label="Date received"
          value={paidOn}
          onChange={(event) => setPaidOn(event.currentTarget.value)}
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button
            loading={save.isPending}
            disabled={!(Number(amount) > 0) || !paidOn}
            onClick={() => save.mutate()}
          >
            Record transfer
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function RefundModal({
  payment,
  onClose,
  onSaved,
}: {
  payment: PaymentOut;
  onClose: () => void;
  onSaved: (invoice: InvoiceOut) => void;
}) {
  const [amount, setAmount] = useState(amountText(refundable(payment)));
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/payments/{payment_id}/refunds", {
          params: { path: { payment_id: payment.id } },
          body: { amount, reason },
        }),
      ),
    onSuccess: (saved) => {
      onSaved(saved);
      notifySaved("Refund recorded");
      onClose();
    },
    onError: (error) => showRequestError(error),
  });
  const viaProvider = payment.method !== "bank_transfer";
  return (
    <Modal opened onClose={onClose} title="Refund">
      <Stack>
        <Text size="sm" c="dimmed">
          {viaProvider
            ? `The refund goes back through ${METHOD_LABELS[payment.method] ?? payment.provider}. It may take a moment to be confirmed, and a few days to reach the payer.`
            : "Bank transfers are refunded outside the system: send the money back from the journal's bank account, then record it here."}
        </Text>
        <Text size="sm">
          Paid {money(payment.amount, payment.currency)}; up to {money(refundable(payment), payment.currency)}{" "}
          can be refunded.
        </Text>
        <TextInput
          label={`Amount, ${payment.currency}`}
          inputMode="decimal"
          value={amount}
          onChange={(event) => setAmount(event.currentTarget.value)}
        />
        <Textarea
          label="Reason"
          description="Sent to the payer."
          required
          autosize
          minRows={2}
          value={reason}
          onChange={(event) => setReason(event.currentTarget.value)}
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button
            color="red"
            loading={save.isPending}
            disabled={!(Number(amount) > 0) || !reason.trim()}
            onClick={() => save.mutate()}
          >
            Refund
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function VoidModal({
  invoice,
  opened,
  onClose,
  onSaved,
}: {
  invoice: InvoiceOut;
  opened: boolean;
  onClose: () => void;
  onSaved: (invoice: InvoiceOut) => void;
}) {
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/payments/invoices/{invoice_id}/void", {
          params: { path: { invoice_id: invoice.id } },
          body: { reason },
        }),
      ),
    onSuccess: (saved) => {
      onSaved(saved);
      notifySaved("Invoice voided");
      onClose();
    },
    onError: (error) => showRequestError(error),
  });
  return (
    <Modal opened={opened} onClose={onClose} title={`Void ${invoice.number}?`}>
      <Stack>
        <Text size="sm">
          A void invoice can no longer be paid. It stays on record. You can then issue a new invoice for the
          manuscript, for example with a corrected amount.
        </Text>
        <Textarea
          label="Reason"
          required
          autosize
          minRows={2}
          value={reason}
          onChange={(event) => setReason(event.currentTarget.value)}
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Keep it
          </Button>
          <Button
            color="red"
            loading={save.isPending}
            disabled={!reason.trim()}
            onClick={() => save.mutate()}
          >
            Void invoice
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function PaymentsTable({
  invoice,
  onRefund,
}: {
  invoice: InvoiceOut;
  onRefund: (payment: PaymentOut) => void;
}) {
  if (invoice.payments.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        No payments yet.
      </Text>
    );
  }
  return (
    <Table.ScrollContainer minWidth={720}>
      <Table verticalSpacing="sm">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Method</Table.Th>
            <Table.Th>Status</Table.Th>
            <Table.Th ta="right">Amount</Table.Th>
            <Table.Th>Reference</Table.Th>
            <Table.Th>Date</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {invoice.payments.map((payment) => {
            const state = look(PAYMENT_STATUS, payment.status);
            const canRefund = payment.status === "succeeded" && refundable(payment) > 0;
            return (
              <Table.Tr key={payment.id}>
                <Table.Td>
                  <Text size="sm">{METHOD_LABELS[payment.method] ?? payment.method}</Text>
                </Table.Td>
                <Table.Td miw={120}>
                  <Badge variant="light" color={state.color} style={{ overflow: "visible" }}>
                    {state.label}
                  </Badge>
                  {payment.failure_reason ? (
                    <Text size="xs" c="red" mt={4}>
                      {payment.failure_reason}
                    </Text>
                  ) : null}
                </Table.Td>
                <Table.Td ta="right">
                  <Text size="sm" style={{ whiteSpace: "nowrap" }}>
                    {money(payment.amount, payment.currency)}
                  </Text>
                  {Number(payment.refunded) > 0 ? (
                    <Text size="xs" c="dimmed" style={{ whiteSpace: "nowrap" }}>
                      refunded {money(payment.refunded, payment.currency)}
                    </Text>
                  ) : null}
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{payment.reference || "—"}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm">{formatDateTime(payment.completed_at ?? payment.created_at)}</Text>
                  {payment.refunds.map((refund) => (
                    <Text key={refund.id} size="xs" c={refund.status === "failed" ? "red" : "dimmed"}>
                      Refund {money(refund.amount, payment.currency)} ·{" "}
                      {refund.status === "succeeded"
                        ? `done ${formatDate(refund.completed_at)}`
                        : refund.status === "pending"
                          ? "being processed"
                          : "failed"}{" "}
                      · {refund.reason}
                      {refund.failure_reason ? ` (${refund.failure_reason})` : ""}
                    </Text>
                  ))}
                </Table.Td>
                <Table.Td>
                  {canRefund ? (
                    <Button
                      size="compact-sm"
                      variant="subtle"
                      color="red"
                      leftSection={<IconReceiptRefund size={14} />}
                      onClick={() => onRefund(payment)}
                    >
                      Refund
                    </Button>
                  ) : null}
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

export function InvoicePage() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [recording, setRecording] = useState(false);
  const [voiding, setVoiding] = useState(false);
  const [refunding, setRefunding] = useState<PaymentOut | null>(null);

  const invoice = useQuery({
    queryKey: invoiceKey(id),
    queryFn: () =>
      unwrap(api.GET("/api/v1/payments/invoices/{invoice_id}", { params: { path: { invoice_id: id } } })),
  });

  const store = (saved: InvoiceOut) => {
    queryClient.setQueryData(invoiceKey(saved.id), saved);
    queryClient.invalidateQueries({ queryKey: ["payments", "invoices"] });
    queryClient.invalidateQueries({ queryKey: ["payments", "summary"] });
  };

  const reissue = useMutation({
    mutationFn: (submissionId: number) =>
      unwrap(
        api.POST("/api/v1/submissions/{submission_id}/invoices", {
          params: { path: { submission_id: submissionId } },
        }),
      ),
    onSuccess: (created) => {
      store(created);
      notifySaved(`Invoice ${created.number} issued`);
      navigate(`/finance/invoices/${created.id}`);
    },
    onError: (error) => showRequestError(error),
  });

  if (!invoice.data) {
    return (
      <QueryState isPending={invoice.isPending} error={invoice.error} onRetry={() => invoice.refetch()} />
    );
  }
  const data = invoice.data;
  const state = look(INVOICE_STATUS, data.status);
  const issued = data.status === "issued";
  const hasReceived = data.payments.some((payment) => payment.status === "succeeded");
  const isReceipt = data.status === "paid" || data.status === "refunded";

  return (
    <Stack gap="lg">
      <PageHeader
        title={data.number}
        description={
          <Group gap="xs">
            <Badge variant="light" color={state.color}>
              {state.label}
            </Badge>
            {data.overdue ? (
              <Badge variant="filled" color="red">
                Overdue
              </Badge>
            ) : null}
            <Text size="sm" c="dimmed">
              Issued {formatDate(data.issued_at)} · due {formatDate(data.due_date)}
              {data.paid_at ? ` · paid ${formatDate(data.paid_at)}` : ""}
            </Text>
          </Group>
        }
        actions={
          <Group gap="xs">
            <Button
              component="a"
              href={data.pdf_url}
              variant="default"
              leftSection={<IconDownload size={16} />}
            >
              {isReceipt ? "Download receipt" : "Download invoice"}
            </Button>
            {issued ? (
              <Button leftSection={<IconBuildingBank size={16} />} onClick={() => setRecording(true)}>
                Record a bank transfer
              </Button>
            ) : null}
            {issued && !hasReceived ? (
              <Button
                variant="light"
                color="red"
                leftSection={<IconBan size={16} />}
                onClick={() => setVoiding(true)}
              >
                Void
              </Button>
            ) : null}
          </Group>
        }
      />

      {data.status === "void" ? (
        <Alert color="gray" title="This invoice is void">
          <Stack gap="xs" align="flex-start">
            <Text size="sm">
              Voided {formatDateTime(data.voided_at)}
              {data.void_reason ? `: ${data.void_reason}` : "."}
            </Text>
            <Button size="xs" loading={reissue.isPending} onClick={() => reissue.mutate(data.submission_id)}>
              Issue a new invoice
            </Button>
          </Stack>
        </Alert>
      ) : null}

      <SimpleGrid cols={{ base: 1, md: 2 }}>
        <Card withBorder padding="lg">
          <Stack gap="xs">
            <Title order={4}>Amounts</Title>
            <Text size="sm">{data.description}</Text>
            <Row label="Publication fee">{money(data.amount, data.currency)}</Row>
            {Number(data.discount) > 0 ? (
              <Row label={`Waiver (${data.discount_percent}%)`}>−{money(data.discount, data.currency)}</Row>
            ) : null}
            {Number(data.vat_percent) > 0 ? (
              <Row label={`VAT ${Number(data.vat_percent)}%`}>{money(data.tax, data.currency)}</Row>
            ) : null}
            <Group justify="space-between">
              <Text fw={700}>Total</Text>
              <Text fw={700}>{money(data.total, data.currency)}</Text>
            </Group>
            {Number(data.refunded) > 0 ? (
              <Row label="Refunded">{money(data.refunded, data.currency)}</Row>
            ) : null}
            {data.waived_at ? <Row label="Waived">{formatDate(data.waived_at)}</Row> : null}
          </Stack>
        </Card>
        <Card withBorder padding="lg">
          <Stack gap="xs">
            <Title order={4}>Payer</Title>
            {data.payer_organization ? <Text size="sm">{data.payer_organization}</Text> : null}
            <Text size="sm">{data.payer_name}</Text>
            <Text size="sm" c="dimmed">
              {data.payer_email}
            </Text>
            {data.payer_address ? (
              <Text size="sm" className="pre-wrap">
                {data.payer_address}
              </Text>
            ) : null}
            {data.payer_tax_id ? (
              <Text size="sm" c="dimmed">
                Tax ID: {data.payer_tax_id}
              </Text>
            ) : null}
            <Anchor component={Link} to={`/submissions/${data.submission_id}`} size="sm" mt="xs">
              Open the manuscript
            </Anchor>
          </Stack>
        </Card>
      </SimpleGrid>

      <Card withBorder padding="lg">
        <Stack gap="sm">
          <Title order={4}>Payments</Title>
          <PaymentsTable invoice={data} onRefund={setRefunding} />
        </Stack>
      </Card>

      {issued ? (
        <TransferModal
          key={`transfer-${data.payments.length}`}
          invoice={data}
          opened={recording}
          onClose={() => setRecording(false)}
          onSaved={store}
        />
      ) : null}
      <VoidModal invoice={data} opened={voiding} onClose={() => setVoiding(false)} onSaved={store} />
      {refunding ? (
        <RefundModal payment={refunding} onClose={() => setRefunding(null)} onSaved={store} />
      ) : null}
    </Stack>
  );
}
