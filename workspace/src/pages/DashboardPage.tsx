import type { Capability } from "@jps/api-client";
import { Anchor, Badge, Card, Group, SimpleGrid, Stack, Text, ThemeIcon, Title } from "@mantine/core";
import {
  IconChecklist,
  IconClipboardList,
  IconFileText,
  IconLayoutList,
  IconMessageCircle,
  IconSettings,
  IconStack2,
  IconUsers,
} from "@tabler/icons-react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { can, hasRole, useSignedInUser } from "../auth";
import { RoleBadges } from "../components/common";
import { usePublicJournal } from "../journal";

function Tile({
  icon,
  title,
  children,
  to,
  soon,
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
  to?: string;
  soon?: boolean;
}) {
  return (
    <Card withBorder padding="lg">
      <Stack gap="sm">
        <Group justify="space-between">
          <ThemeIcon variant="light" size={38}>
            {icon}
          </ThemeIcon>
          {soon ? (
            <Badge variant="light" color="gray">
              Coming soon
            </Badge>
          ) : null}
        </Group>
        <Text fw={600}>
          {to ? (
            <Anchor component={Link} to={to} inherit>
              {title}
            </Anchor>
          ) : (
            title
          )}
        </Text>
        <Text size="sm" c="dimmed">
          {children}
        </Text>
      </Stack>
    </Card>
  );
}

const ADMIN_TILES: { capability: Capability; to: string; title: string; text: string; icon: ReactNode }[] = [
  {
    capability: "journal.settings.edit",
    to: "/admin/journal",
    title: "Journal settings",
    text: "Name, ISSN, publisher, contacts and the description shown on the website.",
    icon: <IconSettings />,
  },
  {
    capability: "journal.settings.edit",
    to: "/admin/submission-settings",
    title: "Submission settings",
    text: "Checklist for authors, guidelines, limits and similarity checking.",
    icon: <IconChecklist />,
  },
  {
    capability: "sections.manage",
    to: "/admin/sections",
    title: "Sections",
    text: "Article types the journal accepts and the editors responsible for them.",
    icon: <IconLayoutList />,
  },
  {
    capability: "users.view",
    to: "/admin/users",
    title: "Users and roles",
    text: "Find people, invite editors and change who can do what.",
    icon: <IconUsers />,
  },
  {
    capability: "audit.view",
    to: "/admin/audit",
    title: "Audit log",
    text: "Every important action: who did it and when.",
    icon: <IconClipboardList />,
  },
];

export function DashboardPage() {
  const me = useSignedInUser();
  const { data: journal } = usePublicJournal();
  const adminTiles = ADMIN_TILES.filter((tile) => can(me, tile.capability));

  return (
    <Stack gap="xl">
      <Stack gap="xs">
        <Title order={2}>Welcome, {me.user.given_name}</Title>
        <Group gap="xs">
          <Text c="dimmed" size="sm">
            Your roles{journal ? ` in ${journal.name}` : ""}:
          </Text>
          <RoleBadges roles={me.roles} />
        </Group>
      </Stack>

      <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
        <Tile icon={<IconFileText />} title="My submissions" to="/submissions">
          Submit a manuscript and follow it through review to publication.
        </Tile>
        {hasRole(me, "reviewer") ? (
          <Tile icon={<IconMessageCircle />} title="Review requests" soon>
            Invitations to review, deadlines and your submitted reviews.
          </Tile>
        ) : null}
        {can(me, "submissions.view_all") || hasRole(me, "section_editor") ? (
          <Tile icon={<IconStack2 />} title="Editorial queue" to="/editorial">
            New submissions, reviews in progress and manuscripts waiting for a decision.
          </Tile>
        ) : null}
      </SimpleGrid>

      {adminTiles.length > 0 ? (
        <Stack gap="sm">
          <Title order={4}>Administration</Title>
          <SimpleGrid cols={{ base: 1, sm: 2, lg: 4 }}>
            {adminTiles.map((tile) => (
              <Tile key={tile.to} icon={tile.icon} title={tile.title} to={tile.to}>
                {tile.text}
              </Tile>
            ))}
          </SimpleGrid>
        </Stack>
      ) : null}
    </Stack>
  );
}
