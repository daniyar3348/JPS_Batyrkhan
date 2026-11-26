import { Button, Center, Stack, Text, Title } from "@mantine/core";
import { Link } from "react-router";

export function NotFoundPage() {
  return (
    <Center h="100vh" p="md">
      <Stack align="center" gap="sm">
        <Title order={1} c="dimmed">
          404
        </Title>
        <Text>This page does not exist.</Text>
        <Button component={Link} to="/" variant="light">
          Go to the dashboard
        </Button>
      </Stack>
    </Center>
  );
}
