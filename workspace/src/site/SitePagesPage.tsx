import { Anchor, Badge, Button, Card, Stack, Table, Text } from "@mantine/core";
import { IconPlus } from "@tabler/icons-react";
import { Link } from "react-router";
import { PageHeader, QueryState } from "../components/common";
import { formatDateTime } from "../lib/format";
import { useSitePages } from "./queries";

/** The site's pages: aims and scope, policies, guidelines. */
export function SitePagesPage() {
  const pages = useSitePages();
  return (
    <Stack>
      <PageHeader
        title="Site pages"
        description="Texts on the journal's site: aims and scope, policies, guidelines for authors."
        actions={
          <Button component={Link} to="/site/pages/new" leftSection={<IconPlus size={16} />}>
            New page
          </Button>
        }
      />
      {pages.data ? (
        pages.data.length === 0 ? (
          <Text c="dimmed">No pages yet. Create the first one, for example “Aims and scope”.</Text>
        ) : (
          <Card withBorder padding={0}>
            <Table.ScrollContainer minWidth={640}>
              <Table verticalSpacing="sm" horizontalSpacing="md" highlightOnHover>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Title</Table.Th>
                    <Table.Th>Address</Table.Th>
                    <Table.Th>Menu</Table.Th>
                    <Table.Th>Status</Table.Th>
                    <Table.Th>Order</Table.Th>
                    <Table.Th>Changed</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {pages.data.map((page) => (
                    <Table.Tr key={page.id}>
                      <Table.Td>
                        <Anchor component={Link} to={`/site/pages/${page.id}`} fw={500}>
                          {page.title}
                        </Anchor>
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm" ff="monospace">
                          /{page.slug}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm">{page.in_menu ? "In menu" : "—"}</Text>
                      </Table.Td>
                      <Table.Td>
                        <Badge variant="light" color={page.is_published ? "green" : "gray"}>
                          {page.is_published ? "Published" : "Draft"}
                        </Badge>
                      </Table.Td>
                      <Table.Td>{page.position}</Table.Td>
                      <Table.Td>
                        <Text size="sm" c="dimmed">
                          {formatDateTime(page.updated_at)}
                        </Text>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          </Card>
        )
      ) : (
        <QueryState isPending={pages.isPending} error={pages.error} onRetry={() => pages.refetch()} />
      )}
    </Stack>
  );
}
