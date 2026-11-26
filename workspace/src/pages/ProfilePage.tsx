import type { ProfileUpdate } from "@jps/api-client";
import {
  Button,
  Card,
  Group,
  PasswordInput,
  Select,
  SimpleGrid,
  Stack,
  TagsInput,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "../api";
import { meQueryKey, useSignedInUser } from "../auth";
import { PageHeader, RoleBadges } from "../components/common";
import { COUNTRIES } from "../lib/countries";
import { notifySaved, PASSWORD_MIN_LENGTH, showRequestError, validatePassword } from "../lib/forms";

function ProfileForm() {
  const me = useSignedInUser();
  const queryClient = useQueryClient();
  const user = me.user;

  const form = useForm({
    initialValues: {
      given_name: user.given_name,
      family_name: user.family_name,
      affiliation: user.affiliation,
      country: user.country,
      orcid: user.orcid ?? "",
      biography: user.biography,
      interests: user.interests,
    },
    validate: { given_name: (value) => (value.trim() ? null : "Enter your given name") },
  });

  const save = useMutation({
    mutationFn: (body: ProfileUpdate) => unwrap(api.PATCH("/api/v1/me", { body })),
    onSuccess: (updated) => {
      queryClient.setQueryData(meQueryKey, { ...me, user: updated });
      form.setInitialValues({ ...form.values, orcid: updated.orcid ?? "" });
      form.setFieldValue("orcid", updated.orcid ?? "");
      form.resetDirty();
      notifySaved("Profile saved");
    },
    onError: (error) => showRequestError(error, form),
  });

  return (
    <Card withBorder padding="lg">
      <form onSubmit={form.onSubmit((values) => save.mutate(values))} noValidate>
        <Stack>
          <Title order={4}>Personal information</Title>
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput label="Given name" required {...form.getInputProps("given_name")} />
            <TextInput label="Family name" {...form.getInputProps("family_name")} />
          </SimpleGrid>
          <TextInput
            label="E-mail address"
            value={user.email}
            disabled
            description="Contact the journal to change it."
          />
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput label="Affiliation" {...form.getInputProps("affiliation")} />
            <Select
              label="Country"
              data={COUNTRIES}
              searchable
              clearable
              {...form.getInputProps("country")}
            />
          </SimpleGrid>
          <TextInput
            label="ORCID iD"
            placeholder="0000-0002-1825-0097"
            description="Shown with your name on published articles and sent to Crossref."
            {...form.getInputProps("orcid")}
          />
          <TagsInput
            label="Research interests"
            description="Editors use these to find suitable reviewers."
            maxTags={30}
            {...form.getInputProps("interests")}
          />
          <Textarea
            label="Short biography"
            autosize
            minRows={3}
            maxRows={10}
            {...form.getInputProps("biography")}
          />
          <Group justify="flex-end">
            <Button type="submit" loading={save.isPending} disabled={!form.isDirty()}>
              Save profile
            </Button>
          </Group>
        </Stack>
      </form>
    </Card>
  );
}

function PasswordForm() {
  const form = useForm({
    initialValues: { current_password: "", new_password: "", confirm: "" },
    validate: {
      current_password: (value) => (value ? null : "Enter your current password"),
      new_password: validatePassword,
      confirm: (value, values) => (value === values.new_password ? null : "The passwords do not match"),
    },
  });
  const change = useMutation({
    mutationFn: ({ confirm: _confirm, ...body }: typeof form.values) =>
      unwrap(api.POST("/api/v1/me/password", { body })),
    onSuccess: () => {
      form.reset();
      notifySaved("Password changed. You were signed out on your other devices.");
    },
    onError: (error) => showRequestError(error, form),
  });

  return (
    <Card withBorder padding="lg">
      <form onSubmit={form.onSubmit((values) => change.mutate(values))} noValidate>
        <Stack>
          <Title order={4}>Password</Title>
          <PasswordInput
            label="Current password"
            autoComplete="current-password"
            {...form.getInputProps("current_password")}
          />
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <PasswordInput
              label="New password"
              description={`At least ${PASSWORD_MIN_LENGTH} characters`}
              autoComplete="new-password"
              {...form.getInputProps("new_password")}
            />
            <PasswordInput
              label="Repeat the new password"
              autoComplete="new-password"
              {...form.getInputProps("confirm")}
            />
          </SimpleGrid>
          <Group justify="flex-end">
            <Button type="submit" variant="light" loading={change.isPending}>
              Change password
            </Button>
          </Group>
        </Stack>
      </form>
    </Card>
  );
}

export function ProfilePage() {
  const me = useSignedInUser();
  return (
    <Stack>
      <PageHeader
        title="My profile"
        description={
          <Group gap="xs" component="span">
            <Text span size="sm" c="dimmed">
              Roles:
            </Text>
            <RoleBadges roles={me.roles} />
          </Group>
        }
      />
      <ProfileForm />
      <PasswordForm />
    </Stack>
  );
}
