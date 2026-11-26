import type { Capability } from "@jps/api-client";
import {
  AppShell,
  Avatar,
  Burger,
  Group,
  Menu,
  NavLink,
  ScrollArea,
  Stack,
  Text,
  ThemeIcon,
  UnstyledButton,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import {
  IconBook2,
  IconChevronDown,
  IconClipboardList,
  IconHome,
  IconLayoutList,
  IconLogout,
  IconSettings,
  IconUser,
  IconUsers,
} from "@tabler/icons-react";
import { useMutation } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link, Outlet, useLocation } from "react-router";
import { api, unwrap } from "../api";
import { can, useSignedInUser } from "../auth";
import { usePublicJournal } from "../journal";
import { initials } from "../lib/format";
import { showRequestError } from "../lib/forms";
import { EmailVerificationBanner } from "./EmailVerificationBanner";

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
  capability?: Capability;
}

const MAIN_NAV: NavItem[] = [
  { to: "/", label: "Dashboard", icon: <IconHome size={18} /> },
  { to: "/profile", label: "My profile", icon: <IconUser size={18} /> },
];

const ADMIN_NAV: NavItem[] = [
  {
    to: "/admin/journal",
    label: "Journal settings",
    icon: <IconSettings size={18} />,
    capability: "journal.settings.edit",
  },
  {
    to: "/admin/sections",
    label: "Sections",
    icon: <IconLayoutList size={18} />,
    capability: "sections.manage",
  },
  { to: "/admin/users", label: "Users and roles", icon: <IconUsers size={18} />, capability: "users.view" },
  { to: "/admin/audit", label: "Audit log", icon: <IconClipboardList size={18} />, capability: "audit.view" },
];

export function AppLayout() {
  const me = useSignedInUser();
  const { data: journal } = usePublicJournal();
  const [opened, { toggle, close }] = useDisclosure();
  const location = useLocation();

  const logout = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/auth/logout")),
    // A full reload drops everything the previous user loaded, and the next person to sign in
    // starts from the dashboard rather than the page the previous user was on.
    onSuccess: () => window.location.replace("/login"),
    onError: (error) => showRequestError(error),
  });

  const adminItems = ADMIN_NAV.filter((item) => !item.capability || can(me, item.capability));
  const isActive = (to: string) =>
    to === "/" ? location.pathname === "/" : location.pathname.startsWith(to);
  const renderItem = (item: NavItem) => (
    <NavLink
      key={item.to}
      component={Link}
      to={item.to}
      label={item.label}
      leftSection={item.icon}
      active={isActive(item.to)}
      onClick={close}
    />
  );

  return (
    <AppShell
      header={{ height: 60 }}
      navbar={{ width: 250, breakpoint: "sm", collapsed: { mobile: !opened } }}
      padding="lg"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Burger
              opened={opened}
              onClick={toggle}
              hiddenFrom="sm"
              size="sm"
              aria-label="Toggle navigation"
            />
            <ThemeIcon size={32} variant="filled">
              <IconBook2 size={20} />
            </ThemeIcon>
            <Text fw={650} truncate maw={{ base: 180, sm: 420 }}>
              {journal?.name ?? "Editorial workspace"}
            </Text>
          </Group>
          <Menu position="bottom-end" width={220}>
            <Menu.Target>
              <UnstyledButton aria-label="Account menu">
                <Group gap="xs" wrap="nowrap">
                  <Avatar color="indigo" radius="xl" size={34}>
                    {initials(me.user.full_name)}
                  </Avatar>
                  <Text size="sm" fw={500} visibleFrom="sm">
                    {me.user.full_name}
                  </Text>
                  <IconChevronDown size={14} />
                </Group>
              </UnstyledButton>
            </Menu.Target>
            <Menu.Dropdown>
              <Menu.Label>{me.user.email}</Menu.Label>
              <Menu.Item component={Link} to="/profile" leftSection={<IconUser size={16} />}>
                My profile
              </Menu.Item>
              <Menu.Item
                color="red"
                leftSection={<IconLogout size={16} />}
                onClick={() => logout.mutate()}
                disabled={logout.isPending}
              >
                Sign out
              </Menu.Item>
            </Menu.Dropdown>
          </Menu>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="sm">
        <AppShell.Section grow component={ScrollArea}>
          <Stack gap={2}>{MAIN_NAV.map(renderItem)}</Stack>
          {adminItems.length > 0 ? (
            <>
              <Text size="xs" fw={700} c="dimmed" tt="uppercase" mt="lg" mb={6} px="sm">
                Administration
              </Text>
              <Stack gap={2}>{adminItems.map(renderItem)}</Stack>
            </>
          ) : null}
        </AppShell.Section>
      </AppShell.Navbar>

      <AppShell.Main>
        <Stack maw={1200} gap="lg">
          <EmailVerificationBanner />
          <Outlet />
        </Stack>
      </AppShell.Main>
    </AppShell>
  );
}
