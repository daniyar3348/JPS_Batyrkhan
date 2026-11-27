import type { Payee, PaymentSettingsOut } from "@jps/api-client";
import {
  Button,
  Card,
  Group,
  NumberInput,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  TagsInput,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { notifications } from "@mantine/notifications";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, unwrap } from "../api";
import { PageHeader, QueryState } from "../components/common";
import { notifySaved, showRequestError } from "../lib/forms";
import { METHOD_LABELS } from "../payments/labels";
import { paymentSettingsKey, usePaymentSettings } from "../payments/queries";
import { useActiveSections } from "../submissions/queries";

type Method = "card" | "paypal" | "bank_transfer";
const METHODS: Method[] = ["card", "paypal", "bank_transfer"];

interface FormValues {
  enabled: boolean;
  currency: string;
  fee: number | string;
  /** By section id; empty means the section pays the default fee. */
  section_fees: Record<string, number | string>;
  vat_percent: number | string;
  due_days: number | string;
  /** Edited as text tags ("-7", "0", "7") and sent as numbers. */
  reminder_days: string[];
  methods: Record<Method, boolean>;
  payee: Payee;
  invoice_note: string;
  waiver_policy: string;
}

function toForm(settings: PaymentSettingsOut): FormValues {
  return {
    enabled: settings.enabled,
    currency: settings.currency,
    fee: Number(settings.fee),
    section_fees: Object.fromEntries(
      Object.entries(settings.section_fees).map(([id, fee]) => [id, Number(fee)]),
    ),
    vat_percent: Number(settings.vat_percent),
    due_days: settings.due_days,
    reminder_days: settings.reminder_days.map(String),
    methods: { ...settings.methods },
    payee: { ...settings.payee },
    invoice_note: settings.invoice_note,
    waiver_policy: settings.waiver_policy,
  };
}

/** Amounts go to the server as strings with two decimals. */
function decimal(value: number | string): string {
  return Number(value).toFixed(2);
}

const INTEGER = /^-?\d+$/;

function validateDays(values: string[]): string | null {
  if (values.length > 6) return "At most 6 reminders";
  for (const value of values) {
    if (!INTEGER.test(value.trim())) return `“${value}” is not a whole number of days`;
    const days = Number(value);
    if (days < -60 || days > 90) return "Use days from -60 to 90";
  }
  return null;
}

function SettingsForm({ settings }: { settings: PaymentSettingsOut }) {
  const queryClient = useQueryClient();
  const sections = useActiveSections();
  const form = useForm<FormValues>({
    initialValues: toForm(settings),
    validate: {
      fee: (value) => (value === "" || Number(value) < 0 ? "Enter the fee (0 or more)" : null),
      vat_percent: (value) =>
        value === "" || Number(value) < 0 || Number(value) > 50 ? "From 0 to 50" : null,
      due_days: (value) =>
        value === "" || Number(value) < 1 || Number(value) > 180 ? "From 1 to 180 days" : null,
      reminder_days: validateDays,
    },
  });

  const save = useMutation({
    mutationFn: (values: FormValues) =>
      unwrap(
        api.PUT("/api/v1/journal/payment-settings", {
          params: { header: { "if-match": `"${settings.version}"` } },
          body: {
            ...values,
            fee: decimal(values.fee),
            vat_percent: decimal(values.vat_percent),
            due_days: Number(values.due_days),
            section_fees: Object.fromEntries(
              Object.entries(values.section_fees)
                .filter(([, fee]) => fee !== "" && fee !== null && fee !== undefined)
                .map(([id, fee]) => [id, decimal(fee)]),
            ),
            reminder_days: [...new Set(values.reminder_days.map((day) => Number(day.trim())))].sort(
              (a, b) => a - b,
            ),
          },
        }),
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(paymentSettingsKey, saved);
      notifySaved("Payment settings saved");
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 412) {
        notifications.show({
          color: "orange",
          title: "Someone else changed the journal settings",
          message: "The latest version is loaded. Make your changes again.",
        });
        queryClient.invalidateQueries({ queryKey: paymentSettingsKey });
        return;
      }
      showRequestError(error, form);
    },
  });

  const availability = Object.fromEntries(settings.method_availability.map((item) => [item.method, item]));
  const currency = form.values.currency;

  return (
    <form onSubmit={form.onSubmit((values) => save.mutate(values))} noValidate>
      <Stack gap="lg">
        <Card withBorder padding="lg">
          <Stack>
            <Title order={4}>Publication fee</Title>
            <Switch
              label="Charge a publication fee"
              description="Invoices are issued automatically when a manuscript is accepted, never before."
              {...form.getInputProps("enabled", { type: "checkbox" })}
            />
            <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }}>
              <Select
                label="Currency"
                data={settings.currencies}
                allowDeselect={false}
                {...form.getInputProps("currency")}
              />
              <NumberInput
                label={`Fee, ${currency}`}
                min={0}
                decimalScale={2}
                thousandSeparator=" "
                {...form.getInputProps("fee")}
              />
              <NumberInput
                label="VAT, %"
                min={0}
                max={50}
                decimalScale={2}
                {...form.getInputProps("vat_percent")}
              />
              <NumberInput label="Days to pay" min={1} max={180} {...form.getInputProps("due_days")} />
            </SimpleGrid>
            {sections.data?.length ? (
              <Stack gap="xs">
                <Text size="sm" fw={500}>
                  Fees by section
                </Text>
                <Text size="sm" c="dimmed">
                  Leave a section empty to charge the fee above.
                </Text>
                <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }}>
                  {sections.data.map((section) => (
                    <NumberInput
                      key={section.id}
                      label={section.title}
                      placeholder={`Default fee, ${currency}`}
                      min={0}
                      decimalScale={2}
                      thousandSeparator=" "
                      {...form.getInputProps(`section_fees.${section.id}`)}
                      value={form.values.section_fees[String(section.id)] ?? ""}
                    />
                  ))}
                </SimpleGrid>
              </Stack>
            ) : null}
            <TagsInput
              label="Reminders for unpaid invoices"
              description="Days relative to the due date: negative before it, 0 on the day, positive after. Press Enter after each number."
              placeholder="Add a day"
              {...form.getInputProps("reminder_days")}
            />
          </Stack>
        </Card>

        <Card withBorder padding="lg">
          <Stack>
            <Title order={4}>Payment methods</Title>
            <Text size="sm" c="dimmed">
              Authors see the methods that are switched on and available.
            </Text>
            {METHODS.map((method) => {
              const status = availability[method];
              return (
                <Switch
                  key={method}
                  label={METHOD_LABELS[method]}
                  description={
                    status && !status.available ? (
                      <Text span size="xs" c="orange.8">
                        Not available: {status.reason}
                      </Text>
                    ) : (
                      "Available"
                    )
                  }
                  {...form.getInputProps(`methods.${method}`, { type: "checkbox" })}
                />
              );
            })}
          </Stack>
        </Card>

        <Card withBorder padding="lg">
          <Stack>
            <Title order={4}>Payee and bank details</Title>
            <Text size="sm" c="dimmed">
              Printed on invoices and shown to authors who pay by bank transfer.
            </Text>
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <TextInput label="Legal name" {...form.getInputProps("payee.name")} />
              <TextInput label="Tax ID (BIN)" {...form.getInputProps("payee.tax_id")} />
            </SimpleGrid>
            <Textarea label="Address" autosize minRows={2} {...form.getInputProps("payee.address")} />
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <TextInput label="Bank" {...form.getInputProps("payee.bank_name")} />
              <TextInput label="IBAN" {...form.getInputProps("payee.iban")} />
              <TextInput label="BIC / SWIFT" {...form.getInputProps("payee.bic")} />
              <SimpleGrid cols={2}>
                <TextInput label="KBe" description="Beneficiary code" {...form.getInputProps("payee.kbe")} />
                <TextInput
                  label="KNP"
                  description="Payment purpose code"
                  {...form.getInputProps("payee.knp")}
                />
              </SimpleGrid>
            </SimpleGrid>
          </Stack>
        </Card>

        <Card withBorder padding="lg">
          <Stack>
            <Title order={4}>Texts</Title>
            <Textarea
              label="Note on invoices"
              description="Printed at the bottom of every invoice and receipt."
              autosize
              minRows={2}
              {...form.getInputProps("invoice_note")}
            />
            <Textarea
              label="Waiver policy"
              description="Shown to authors next to the request for a waiver."
              autosize
              minRows={3}
              {...form.getInputProps("waiver_policy")}
            />
          </Stack>
        </Card>

        <Group justify="flex-end">
          <Button type="submit" loading={save.isPending} disabled={!form.isDirty()}>
            Save settings
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

export function PaymentSettingsPage() {
  const settings = usePaymentSettings();
  return (
    <Stack>
      <PageHeader title="Payment settings" description="The publication fee and how authors can pay it." />
      {settings.data ? (
        <SettingsForm key={settings.data.version} settings={settings.data} />
      ) : (
        <QueryState
          isPending={settings.isPending}
          error={settings.error}
          onRetry={() => settings.refetch()}
        />
      )}
    </Stack>
  );
}
