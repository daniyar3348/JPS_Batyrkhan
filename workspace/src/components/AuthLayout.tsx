import { Anchor, Box, Container, Group, Paper, Stack, Text, ThemeIcon, Title } from "@mantine/core";
import { IconBook2 } from "@tabler/icons-react";
import { Outlet } from "react-router";
import { usePublicJournal } from "../journal";

export function AuthLayout() {
  const { data: journal } = usePublicJournal();
  return (
    <Box className="auth-background" py={48}>
      <Container size={460}>
        <Stack gap="lg">
          <Group gap="sm" justify="center">
            <ThemeIcon size={40} radius="md" variant="filled">
              <IconBook2 size={24} />
            </ThemeIcon>
            <Stack gap={0}>
              <Title order={3} lh={1.2}>
                {journal?.name ?? "Editorial workspace"}
              </Title>
              <Text size="sm" c="dimmed">
                Editorial workspace
              </Text>
            </Stack>
          </Group>
          <Paper withBorder shadow="sm" p="xl" radius="lg">
            <Outlet />
          </Paper>
          {journal?.contact_email ? (
            <Text size="sm" c="dimmed" ta="center">
              Questions? Write to{" "}
              <Anchor href={`mailto:${journal.contact_email}`} size="sm">
                {journal.contact_email}
              </Anchor>
            </Text>
          ) : null}
        </Stack>
      </Container>
    </Box>
  );
}
