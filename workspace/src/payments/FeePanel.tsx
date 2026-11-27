import type { BillingOut, InvoiceOut } from "@jps/api-client";
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Modal,
  NumberInput,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import {
  IconBrandPaypal,
  IconBuildingBank,
  IconCreditCard,
  IconDownload,
  IconPencil,
} from "@tabler/icons-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrap } from "../api";
import { QueryState } from "../components/common";
import { formatDate, formatDateTime } from "../lib/format";
import { notifySaved, showRequestError } from "../lib/forms";
import { INVOICE_STATUS, look, METHOD_LABELS, money, PAYMENT_STATUS, WAIVER_STATUS } from "./labels";
import { billingKey, useBilling } from "./queries";

function Amounts({ invoice }: { invoice: InvoiceOut }) {
  const rows: [string, string][] = [["Publication fee", money(invoice.amount, invoice.currency)]];
  if (Number(invoice.discount) > 0) {
    rows.push([`Fee waiver (${invoice.discount_percent}%)`, `−${money(invoice.discount, invoice.currency)}`]);
  }
  if (Number(invoice.vat_percent) > 0) {
    rows.push([`VAT ${Number(invoice.vat_percent)}%`, money(invoice.tax, invoice.currency)]);
  }
  return (
    <Table verticalSpacing={6} withRowBorders={false}>
      <Table.Tbody>
        {rows.map(([label, value]) => (
          <Table.Tr key={label}>
            <Table.Td>
              <Text size="sm">{label}</Text>
            </Table.Td>
            <Table.Td ta="right">
              <Text size="sm">{value}</Text>
            </Table.Td>
          </Table.Tr>
        ))}
        <Table.Tr style={{ borderTop: "1px solid var(--mantine-color-default-border)" }}>
          <Table.Td>
            <Text fw={700}>Total</Text>
          </Table.Td>
          <Table.Td ta="right">
            <Text fw={700}>{money(invoice.total, invoice.currency)}</Text>
          </Table.Td>
        </Table.Tr>
      </Table.Tbody>
    </Table>
  );
}

/** Who the invoice is made out to: the author, or their institution. */
function PayerModal({
  invoice,
  submissionId,
  onClose,
}: {
  invoice: InvoiceOut;
  submissionId: number;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const form = useForm({
    initialValues: {
      payer_name: invoice.payer_name,
      payer_email: invoice.payer_email,
      payer_organization: invoice.payer_organization,
      payer_address: invoice.payer_address,
      payer_tax_id: invoice.payer_tax_id,
    },
  });
  const save = useMutation({
    mutationFn: (values: typeof form.values) =>
      unwrap(
        api.PATCH("/api/v1/payments/invoices/{invoice_id}/payer", {
          params: { path: { invoice_id: invoice.id } },
          body: values,
        }),
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: billingKey(submissionId) });
      notifySaved("Payer details saved");
      onClose();
    },
    onError: (error) => showRequestError(error, form),
  });
  return (
    <Modal opened onClose={onClose} title="Payer details" size="lg">
      <form onSubmit={form.onSubmit((values) => save.mutate(values))}>
        <Stack>
          <Text size="sm" c="dimmed">
            For example, to have your university pay: enter its name, address and tax number. The invoice is
            updated straight away.
          </Text>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput label="Name" required {...form.getInputProps("payer_name")} />
            <TextInput label="E-mail" type="email" required {...form.getInputProps("payer_email")} />
          </SimpleGrid>
          <TextInput label="Organization" {...form.getInputProps("payer_organization")} />
          <Textarea label="Address" autosize minRows={2} {...form.getInputProps("payer_address")} />
          <TextInput label="Tax number (BIN/IIN or VAT number)" {...form.getInputProps("payer_tax_id")} />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" loading={save.isPending}>
              Save
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

function WaiverModal({
  billing,
  submissionId,
  onClose,
}: {
  billing: BillingOut;
  submissionId: number;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [percent, setPercent] = useState<number | string>(100);
  const [reason, setReason] = useState("");
  const request = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/submissions/{submission_id}/waiver-requests", {
          params: { path: { submission_id: submissionId } },
          body: { percent: Number(percent), reason },
        }),
      ),
    onSuccess: (data) => {
      queryClient.setQueryData(billingKey(submissionId), data);
      notifySaved("Your request has been sent to the journal's finance manager");
      onClose();
    },
    onError: (error) => showRequestError(error),
  });
  return (
    <Modal opened onClose={onClose} title="Ask for a fee waiver" size="lg">
      <Stack>
        {billing.waiver_policy ? (
          <Alert color="gray" variant="light" title="The journal's policy">
            <Text size="sm" className="pre-wrap">
              {billing.waiver_policy}
            </Text>
          </Alert>
        ) : null}
        <Text size="sm" c="dimmed">
          The finance manager decides. The editors do not see your request: it has no effect on the editorial
          decision.
        </Text>
        <NumberInput
          label="Share of the fee to waive, %"
          min={1}
          max={100}
          value={percent}
          onChange={setPercent}
          maw={220}
        />
        <Textarea
          label="Reason"
          description="For example: no research funding, or the journal's policy for your country."
          required
          autosize
          minRows={3}
          value={reason}
          onChange={(event) => setReason(event.currentTarget.value)}
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={!reason.trim() || !percent}
            loading={request.isPending}
            onClick={() => request.mutate()}
          >
            Send request
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function PayButtons({ billing, invoice }: { billing: BillingOut; invoice: InvoiceOut }) {
  const checkout = useMutation({
    mutationFn: (method: "card" | "paypal") =>
      unwrap(
        api.POST("/api/v1/payments/invoices/{invoice_id}/checkout", {
          params: { path: { invoice_id: invoice.id } },
          body: { method },
        }),
      ),
    // The provider's own page takes the payment; card details never reach the journal.
    onSuccess: (data) => window.location.assign(data.redirect_url),
    onError: (error) => showRequestError(error),
  });
  const online = billing.methods.filter((m) => m.method !== "bank_transfer");
  const icons: Record<string, React.ReactNode> = {
    card: <IconCreditCard size={18} />,
    paypal: <IconBrandPaypal size={18} />,
  };
  return (
    <Stack gap="sm">
      <Group gap="sm">
        {online.map((method) => (
          <Button
            key={method.method}
            leftSection={icons[method.method]}
            disabled={!method.available}
            loading={checkout.isPending && checkout.variables === method.method}
            onClick={() => checkout.mutate(method.method as "card" | "paypal")}
            title={method.available ? undefined : method.reason}
          >
            {method.method === "card"
              ? "Pay by card"
              : `Pay with ${METHOD_LABELS[method.method] ?? method.method}`}
          </Button>
        ))}
      </Group>
      {online
        .filter((m) => !m.available)
        .map((m) => (
          <Text key={m.method} size="xs" c="dimmed">
            {METHOD_LABELS[m.method]}: {m.reason}.
          </Text>
        ))}
      {billing.bank_details ? (
        <Card withBorder padding="md" bg="var(--mantine-color-gray-0)">
          <Group gap="xs" mb={6}>
            <IconBuildingBank size={18} />
            <Text fw={600} size="sm">
              Or pay by bank transfer
            </Text>
          </Group>
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing={4}>
            {(
              [
                ["Beneficiary", billing.bank_details.name],
                ["BIN", billing.bank_details.tax_id],
                ["Bank", billing.bank_details.bank_name],
                ["IBAN", billing.bank_details.iban],
                ["BIC/SWIFT", billing.bank_details.bic],
                ["KBe", billing.bank_details.kbe],
                ["KNP", billing.bank_details.knp],
                ["Payment reference", invoice.number],
              ] as [string, string][]
            )
              .filter(([, value]) => value)
              .map(([label, value]) => (
                <Text key={label} size="sm">
                  <Text span c="dimmed" size="sm">
                    {label}:{" "}
                  </Text>
                  {value}
                </Text>
              ))}
          </SimpleGrid>
          <Text size="xs" c="dimmed" mt={6}>
            Transfers are confirmed by the journal's finance manager when the money arrives, usually within a
            few working days.
          </Text>
        </Card>
      ) : null}
    </Stack>
  );
}

function InvoiceCard({
  billing,
  invoice,
  submissionId,
}: {
  billing: BillingOut;
  invoice: InvoiceOut;
  submissionId: number;
}) {
  const [editing, setEditing] = useState(false);
  const status = look(INVOICE_STATUS, invoice.status);
  const paid = invoice.status === "paid" || invoice.status === "refunded";
  return (
    <Card withBorder padding="lg">
      <Stack gap="md">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Group gap="xs">
              <Title order={4}>Invoice {invoice.number}</Title>
              <Badge color={status.color} variant="light">
                {status.label}
              </Badge>
              {invoice.overdue ? (
                <Badge color="red" variant="filled">
                  Overdue
                </Badge>
              ) : null}
            </Group>
            <Text size="sm" c="dimmed">
              Issued {formatDate(invoice.issued_at)}
              {invoice.status === "issued" ? ` · due ${formatDate(invoice.due_date)}` : ""}
              {invoice.paid_at ? ` · paid ${formatDate(invoice.paid_at)}` : ""}
            </Text>
          </Stack>
          <Anchor href={invoice.pdf_url} size="sm">
            <Group gap={6}>
              <IconDownload size={16} />
              {paid ? "Receipt (PDF)" : "Invoice (PDF)"}
            </Group>
          </Anchor>
        </Group>
        <Amounts invoice={invoice} />
        <Group justify="space-between" align="flex-start">
          <Stack gap={0}>
            <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
              Payer
            </Text>
            <Text size="sm">
              {[invoice.payer_organization, invoice.payer_name].filter(Boolean).join(", ")}
            </Text>
            <Text size="xs" c="dimmed">
              {invoice.payer_email}
            </Text>
          </Stack>
          {invoice.status === "issued" ? (
            <Button
              size="xs"
              variant="subtle"
              leftSection={<IconPencil size={14} />}
              onClick={() => setEditing(true)}
            >
              Change payer
            </Button>
          ) : null}
        </Group>
        {invoice.status === "issued" ? <PayButtons billing={billing} invoice={invoice} /> : null}
        {invoice.status === "waived" ? (
          <Alert color="grape" variant="light">
            The fee has been waived. Nothing is due.
          </Alert>
        ) : null}
        {invoice.payments.filter((p) => p.status !== "created").length ? (
          <Stack gap={4}>
            <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
              Payments
            </Text>
            {invoice.payments
              .filter((p) => p.status !== "created")
              .map((payment) => {
                const s = look(PAYMENT_STATUS, payment.status);
                return (
                  <Group key={payment.id} gap="xs">
                    <Badge size="sm" variant="light" color={s.color}>
                      {s.label}
                    </Badge>
                    <Text size="sm">
                      {money(payment.amount, payment.currency)} by{" "}
                      {METHOD_LABELS[payment.method]?.toLowerCase()}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {formatDateTime(payment.completed_at ?? payment.created_at)}
                    </Text>
                    {Number(payment.refunded) > 0 ? (
                      <Text size="xs" c="dimmed">
                        · {money(payment.refunded, payment.currency)} refunded
                      </Text>
                    ) : null}
                  </Group>
                );
              })}
          </Stack>
        ) : null}
      </Stack>
      {editing ? (
        <PayerModal invoice={invoice} submissionId={submissionId} onClose={() => setEditing(false)} />
      ) : null}
    </Card>
  );
}

/** The publication fee, for the manuscript's authors: what is due, how to pay, waivers. */
export function FeePanel({ submissionId }: { submissionId: number }) {
  const billing = useBilling(submissionId);
  const [asking, setAsking] = useState(false);
  if (!billing.data) {
    return (
      <QueryState isPending={billing.isPending} error={billing.error} onRetry={() => billing.refetch()} />
    );
  }
  const data = billing.data;
  const current = data.invoices.filter((i) => i.status !== "void");
  return (
    <Stack gap="lg">
      {current.length === 0 ? (
        <Alert color="gray" variant="light" title="Publication fee">
          {data.fee_required
            ? `The publication fee is ${money(data.expected_fee, data.currency)}. It is charged only if the manuscript is accepted, and has no part in the editors' decision.`
            : data.accepted
              ? "There is no publication fee for this article."
              : "If the manuscript is accepted, you will be told here whether a publication fee applies."}
        </Alert>
      ) : (
        current.map((invoice) => (
          <InvoiceCard key={invoice.id} billing={data} invoice={invoice} submissionId={submissionId} />
        ))
      )}
      {data.waivers.length || data.can_request_waiver ? (
        <Card withBorder padding="lg">
          <Stack gap="sm">
            <Group justify="space-between">
              <Title order={5}>Fee waiver</Title>
              {data.can_request_waiver ? (
                <Button size="xs" variant="light" onClick={() => setAsking(true)}>
                  Ask for a waiver
                </Button>
              ) : null}
            </Group>
            {data.waivers.length === 0 ? (
              <Text size="sm" c="dimmed">
                If you cannot pay the fee, you can ask for it to be reduced or waived.
              </Text>
            ) : null}
            {data.waivers.map((waiver) => {
              const s = look(WAIVER_STATUS, waiver.status);
              return (
                <Stack key={waiver.id} gap={2}>
                  <Group gap="xs">
                    <Badge size="sm" variant="light" color={s.color}>
                      {s.label}
                    </Badge>
                    <Text size="sm">
                      {waiver.status === "approved"
                        ? `${waiver.approved_percent}% waived`
                        : `${waiver.percent}% requested`}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {formatDate(waiver.decided_at ?? waiver.created_at)}
                    </Text>
                  </Group>
                  {waiver.decision_note ? (
                    <Text size="sm" c="dimmed" className="pre-wrap">
                      {waiver.decision_note}
                    </Text>
                  ) : null}
                </Stack>
              );
            })}
          </Stack>
        </Card>
      ) : null}
      {asking ? (
        <WaiverModal billing={data} submissionId={submissionId} onClose={() => setAsking(false)} />
      ) : null}
    </Stack>
  );
}
