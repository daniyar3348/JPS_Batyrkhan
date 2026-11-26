import {
  Anchor,
  Button,
  Checkbox,
  Divider,
  PasswordInput,
  Select,
  SimpleGrid,
  Stack,
  TagsInput,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, Navigate, useNavigate } from "react-router";
import { api, unwrap } from "../../api";
import { applySession, useMe } from "../../auth";
import { ConsentFields } from "../../components/ConsentFields";
import { COUNTRIES } from "../../lib/countries";
import { PASSWORD_MIN_LENGTH, showRequestError, validateEmail, validatePassword } from "../../lib/forms";

export function RegisterPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: me } = useMe();

  const form = useForm({
    initialValues: {
      given_name: "",
      family_name: "",
      email: "",
      password: "",
      affiliation: "",
      country: null as string | null,
      interests: [] as string[],
      wants_to_review: false,
      accept_privacy_policy: false,
      accept_cross_border_transfer: false,
    },
    validate: {
      given_name: (value) => (value.trim() ? null : "Enter your given name"),
      email: validateEmail,
      password: validatePassword,
      accept_privacy_policy: (value) => (value ? null : "Required to create an account"),
      accept_cross_border_transfer: (value) => (value ? null : "Required to create an account"),
    },
  });

  const register = useMutation({
    mutationFn: (values: typeof form.values) => unwrap(api.POST("/api/v1/auth/register", { body: values })),
    onSuccess: (session) => {
      applySession(queryClient, session);
      navigate("/", { replace: true });
    },
    onError: (error) => showRequestError(error, form),
  });

  if (me) return <Navigate to="/" replace />;

  return (
    <form onSubmit={form.onSubmit((values) => register.mutate(values))} noValidate>
      <Stack>
        <Stack gap={4}>
          <Title order={2}>Create an account</Title>
          <Text c="dimmed" size="sm">
            You need an account to submit a manuscript or to review for the journal.
          </Text>
        </Stack>
        <SimpleGrid cols={{ base: 1, xs: 2 }}>
          <TextInput
            label="Given name"
            autoComplete="given-name"
            required
            {...form.getInputProps("given_name")}
          />
          <TextInput label="Family name" autoComplete="family-name" {...form.getInputProps("family_name")} />
        </SimpleGrid>
        <TextInput
          label="E-mail address"
          type="email"
          autoComplete="email"
          required
          {...form.getInputProps("email")}
        />
        <PasswordInput
          label="Password"
          description={`At least ${PASSWORD_MIN_LENGTH} characters. A short phrase is easy to remember and hard to guess.`}
          autoComplete="new-password"
          required
          {...form.getInputProps("password")}
        />
        <TextInput
          label="Affiliation"
          placeholder="University, institute or company"
          autoComplete="organization"
          {...form.getInputProps("affiliation")}
        />
        <Select
          label="Country"
          placeholder="Choose a country"
          data={COUNTRIES}
          searchable
          clearable
          {...form.getInputProps("country")}
        />
        <TagsInput
          label="Research interests"
          description="Press Enter after each. Editors use these to find suitable reviewers."
          maxTags={30}
          {...form.getInputProps("interests")}
        />
        <Checkbox
          label="I am willing to review manuscripts for this journal"
          {...form.getInputProps("wants_to_review", { type: "checkbox" })}
        />
        <Divider />
        <ConsentFields
          privacy={form.getInputProps("accept_privacy_policy", { type: "checkbox" })}
          crossBorder={form.getInputProps("accept_cross_border_transfer", { type: "checkbox" })}
        />
        <Button type="submit" loading={register.isPending} fullWidth>
          Create account
        </Button>
        <Text size="sm" ta="center">
          Already registered?{" "}
          <Anchor component={Link} to="/login">
            Sign in
          </Anchor>
        </Text>
      </Stack>
    </form>
  );
}
