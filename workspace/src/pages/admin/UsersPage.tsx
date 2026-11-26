import type { InviteIn, MemberOut, Role } from "@jps/api-client";
import {
  Avatar,
  Badge,
  Button,
  Card,
  Checkbox,
  Drawer,
  Group,
  Modal,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { useDebouncedValue, useDisclosure } from "@mantine/hooks";
import { modals } from "@mantine/modals";
import { IconMailForward, IconSearch, IconUserPlus } from "@tabler/icons-react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, unwrap } from "../../api";
import { can, useSignedInUser } from "../../auth";
import { PageHeader, QueryState, RoleBadges } from "../../components/common";
import { countryName } from "../../lib/countries";
import { formatDateTime, initials } from "../../lib/format";
import { notifySaved, showRequestError, validateEmail } from "../../lib/forms";
import { ROLE_DESCRIPTIONS, ROLE_LABELS, ROLES } from "../../lib/roles";

const usersKey = ["users"] as const;

function RoleCheckboxes({
  value,
  onChange,
  disabled,
  error,
}: {
  value: Role[];
  onChange: (roles: Role[]) => void;
  disabled?: boolean;
  error?: React.ReactNode;
}) {
  return (
    <Checkbox.Group value={value} onChange={(roles) => onChange(roles as Role[])} error={error}>
      <Stack gap="xs" mt={4}>
        {ROLES.map((role) => (
          <Checkbox
            key={role}
            value={role}
            label={ROLE_LABELS[role]}
            description={ROLE_DESCRIPTIONS[role]}
            disabled={disabled}
          />
        ))}
      </Stack>
    </Checkbox.Group>
  );
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Stack gap={2}>
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
        {label}
      </Text>
      <Text size="sm">{children || "—"}</Text>
    </Stack>
  );
}

function MemberPanel({ userId, onClose }: { userId: number; onClose: () => void }) {
  const me = useSignedInUser();
  const queryClient = useQueryClient();
  const canManage = can(me, "users.manage");
  const member = useQuery({
    queryKey: [...usersKey, userId],
    queryFn: () => unwrap(api.GET("/api/v1/users/{user_id}", { params: { path: { user_id: userId } } })),
  });
  const [roles, setRoles] = useState<Role[] | null>(null);
  const selectedRoles = roles ?? member.data?.roles ?? [];

  const refresh = (updated: MemberOut) => {
    queryClient.setQueryData([...usersKey, userId], updated);
    queryClient.invalidateQueries({ queryKey: usersKey, exact: false, refetchType: "active" });
    if (updated.id === me.user.id) queryClient.invalidateQueries({ queryKey: ["me"] });
  };

  const saveRoles = useMutation({
    mutationFn: () =>
      unwrap(
        api.PUT("/api/v1/users/{user_id}/roles", {
          params: { path: { user_id: userId } },
          body: { roles: selectedRoles },
        }),
      ),
    onSuccess: (updated) => {
      setRoles(null);
      refresh(updated);
      notifySaved("Roles updated");
    },
    onError: (error) => showRequestError(error),
  });

  const setActive = useMutation({
    mutationFn: (is_active: boolean) =>
      unwrap(
        api.PATCH("/api/v1/users/{user_id}", { params: { path: { user_id: userId } }, body: { is_active } }),
      ),
    onSuccess: (updated) => {
      refresh(updated);
      notifySaved(updated.is_active ? "Account activated" : "Account deactivated");
    },
    onError: (error) => showRequestError(error),
  });

  const resendInvitation = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/v1/users/{user_id}/invitation", { params: { path: { user_id: userId } } })),
    onSuccess: () => notifySaved("Invitation sent again"),
    onError: (error) => showRequestError(error),
  });

  if (!member.data) {
    return <QueryState isPending={member.isPending} error={member.error} onRetry={() => member.refetch()} />;
  }
  const user = member.data;
  const confirmDeactivate = () =>
    modals.openConfirmModal({
      title: `Deactivate ${user.full_name}?`,
      children: (
        <Text size="sm">
          They will be signed out everywhere and will not be able to sign in. Their manuscripts and reviews
          stay in the system. You can activate the account again at any time.
        </Text>
      ),
      labels: { confirm: "Deactivate", cancel: "Cancel" },
      confirmProps: { color: "red" },
      onConfirm: () => setActive.mutate(false),
    });

  return (
    <Stack gap="lg">
      <Group>
        <Avatar color="indigo" radius="xl" size={48}>
          {initials(user.full_name)}
        </Avatar>
        <Stack gap={2}>
          <Title order={4}>{user.full_name}</Title>
          <Text size="sm" c="dimmed">
            {user.email}
          </Text>
        </Stack>
      </Group>
      <Group gap="xs">
        {user.is_active ? <Badge color="teal">Active</Badge> : <Badge color="gray">Deactivated</Badge>}
        {!user.has_password ? <Badge color="orange">Invitation not accepted</Badge> : null}
        {user.has_password && !user.email_verified ? (
          <Badge color="yellow">E-mail not confirmed</Badge>
        ) : null}
      </Group>
      <SimpleGrid cols={2}>
        <Detail label="Affiliation">{user.affiliation}</Detail>
        <Detail label="Country">{countryName(user.country)}</Detail>
        <Detail label="ORCID iD">{user.orcid}</Detail>
        <Detail label="Last sign-in">{formatDateTime(user.last_login_at)}</Detail>
        <Detail label="Registered">{formatDateTime(user.created_at)}</Detail>
      </SimpleGrid>

      <Stack gap="xs">
        <Title order={5}>Roles</Title>
        {canManage ? (
          <>
            <RoleCheckboxes value={selectedRoles} onChange={setRoles} />
            <Group justify="flex-end">
              <Button variant="default" disabled={roles === null} onClick={() => setRoles(null)}>
                Undo
              </Button>
              <Button
                disabled={roles === null}
                loading={saveRoles.isPending}
                onClick={() => saveRoles.mutate()}
              >
                Save roles
              </Button>
            </Group>
          </>
        ) : (
          <RoleBadges roles={user.roles} />
        )}
      </Stack>

      {canManage ? (
        <Stack gap="xs">
          <Title order={5}>Account</Title>
          <Group>
            {!user.has_password && user.is_active ? (
              <Button
                variant="light"
                leftSection={<IconMailForward size={16} />}
                loading={resendInvitation.isPending}
                onClick={() => resendInvitation.mutate()}
              >
                Send invitation again
              </Button>
            ) : null}
            {user.id === me.user.id ? null : user.is_active ? (
              <Button color="red" variant="light" loading={setActive.isPending} onClick={confirmDeactivate}>
                Deactivate account
              </Button>
            ) : (
              <Button
                color="teal"
                variant="light"
                loading={setActive.isPending}
                onClick={() => setActive.mutate(true)}
              >
                Activate account
              </Button>
            )}
          </Group>
        </Stack>
      ) : null}
      <Button variant="subtle" onClick={onClose}>
        Close
      </Button>
    </Stack>
  );
}

function InviteForm({ onDone }: { onDone: (user: MemberOut) => void }) {
  const queryClient = useQueryClient();
  const form = useForm({
    initialValues: { email: "", given_name: "", family_name: "", affiliation: "", roles: [] as Role[] },
    validate: {
      email: validateEmail,
      given_name: (value) => (value.trim() ? null : "Enter the given name"),
      roles: (value) => (value.length ? null : "Choose at least one role"),
    },
  });
  const invite = useMutation({
    mutationFn: (body: InviteIn) => unwrap(api.POST("/api/v1/users", { body })),
    onSuccess: (user) => {
      queryClient.invalidateQueries({ queryKey: usersKey });
      notifySaved(`Invitation sent to ${user.email}`);
      onDone(user);
    },
    onError: (error) => showRequestError(error, form),
  });

  return (
    <form onSubmit={form.onSubmit((values) => invite.mutate(values))} noValidate>
      <Stack>
        <Text size="sm" c="dimmed">
          The person receives an e-mail with a link to choose a password. The link works for 7 days.
        </Text>
        <TextInput label="E-mail address" type="email" required {...form.getInputProps("email")} />
        <SimpleGrid cols={2}>
          <TextInput label="Given name" required {...form.getInputProps("given_name")} />
          <TextInput label="Family name" {...form.getInputProps("family_name")} />
        </SimpleGrid>
        <TextInput label="Affiliation" {...form.getInputProps("affiliation")} />
        <Stack gap={0}>
          <Text size="sm" fw={500}>
            Roles
          </Text>
          <RoleCheckboxes
            value={form.values.roles}
            onChange={(roles) => form.setFieldValue("roles", roles)}
            error={form.errors.roles}
          />
        </Stack>
        <Group justify="flex-end">
          <Button type="submit" loading={invite.isPending} leftSection={<IconMailForward size={16} />}>
            Send invitation
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

export function UsersPage() {
  const me = useSignedInUser();
  const [search, setSearch] = useState("");
  const [q] = useDebouncedValue(search.trim(), 300);
  const [role, setRole] = useState<Role | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [inviteOpened, invite] = useDisclosure(false);

  const users = useInfiniteQuery({
    queryKey: [...usersKey, "list", q, role],
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/users", {
          params: {
            query: { q: q || undefined, role: role ?? undefined, cursor: pageParam ?? undefined, limit: 50 },
          },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor ?? null,
  });
  const rows = users.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <Stack>
      <PageHeader
        title="Users and roles"
        description="Everyone with an account. Open a person to see their details and change their roles."
        actions={
          can(me, "users.manage") ? (
            <Button leftSection={<IconUserPlus size={16} />} onClick={invite.open}>
              Invite user
            </Button>
          ) : null
        }
      />
      <Group>
        <TextInput
          placeholder="Search by name, e-mail or affiliation"
          leftSection={<IconSearch size={16} />}
          value={search}
          onChange={(event) => setSearch(event.currentTarget.value)}
          w={{ base: "100%", sm: 360 }}
        />
        <Select
          placeholder="All roles"
          data={ROLES.map((value) => ({ value, label: ROLE_LABELS[value] }))}
          value={role}
          onChange={(value) => setRole(value as Role | null)}
          clearable
          w={{ base: "100%", sm: 220 }}
        />
      </Group>

      {users.data ? (
        <Card withBorder padding={0}>
          {rows.length === 0 ? (
            <Text c="dimmed" p="lg">
              Nobody matches this search.
            </Text>
          ) : (
            <Table.ScrollContainer minWidth={720}>
              <Table verticalSpacing="sm" horizontalSpacing="md" highlightOnHover>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Name</Table.Th>
                    <Table.Th>Affiliation</Table.Th>
                    <Table.Th>Roles</Table.Th>
                    <Table.Th>Status</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {rows.map((user) => (
                    <Table.Tr key={user.id} className="clickable-row" onClick={() => setSelected(user.id)}>
                      <Table.Td>
                        <Text size="sm" fw={500}>
                          {user.full_name}
                        </Text>
                        <Text size="xs" c="dimmed">
                          {user.email}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm">{user.affiliation || "—"}</Text>
                      </Table.Td>
                      <Table.Td>
                        <RoleBadges roles={user.roles} size="xs" />
                      </Table.Td>
                      <Table.Td>
                        {!user.is_active ? (
                          <Badge color="gray" variant="light">
                            Deactivated
                          </Badge>
                        ) : !user.has_password ? (
                          <Badge color="orange" variant="light">
                            Invited
                          </Badge>
                        ) : (
                          <Badge color="teal" variant="light">
                            Active
                          </Badge>
                        )}
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )}
          {users.hasNextPage ? (
            <Group justify="center" p="md">
              <Button
                variant="light"
                loading={users.isFetchingNextPage}
                onClick={() => users.fetchNextPage()}
              >
                Show more
              </Button>
            </Group>
          ) : null}
        </Card>
      ) : (
        <QueryState isPending={users.isPending} error={users.error} onRetry={() => users.refetch()} />
      )}

      <Drawer
        opened={selected !== null}
        onClose={() => setSelected(null)}
        position="right"
        size="md"
        title="User"
      >
        {selected !== null ? (
          <MemberPanel key={selected} userId={selected} onClose={() => setSelected(null)} />
        ) : null}
      </Drawer>
      <Modal opened={inviteOpened} onClose={invite.close} title="Invite a user" size="lg">
        <InviteForm
          onDone={(user) => {
            invite.close();
            setSelected(user.id);
          }}
        />
      </Modal>
    </Stack>
  );
}
