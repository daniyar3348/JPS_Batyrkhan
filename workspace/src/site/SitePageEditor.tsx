import type { PageIn, PageOut } from "@jps/api-client";
import {
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  NumberInput,
  SimpleGrid,
  Stack,
  Switch,
  TextInput,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import { IconTrash } from "@tabler/icons-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ApiError, api, unwrap } from "../api";
import { PageHeader, QueryState } from "../components/common";
import { notifySaved, showRequestError } from "../lib/forms";
import { MarkdownField } from "./MarkdownField";
import { sitePageKey, sitePagesKey, useSitePage } from "./queries";

interface FormValues {
  title: string;
  slug: string;
  position: number | string;
  in_menu: boolean;
  is_published: boolean;
  body: string;
}

/** "Aims & Scope" → "aims-scope": the page's address on the site. */
export function slugify(text: string): string {
  return text
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80)
    .replace(/-+$/g, "");
}

function toForm(page?: PageOut): FormValues {
  return {
    title: page?.title ?? "",
    slug: page?.slug ?? "",
    position: page?.position ?? 0,
    in_menu: page?.in_menu ?? true,
    is_published: page?.is_published ?? false,
    body: page?.body ?? "",
  };
}

function toBody(values: FormValues): PageIn {
  return {
    title: values.title.trim(),
    slug: values.slug.trim(),
    position: values.position === "" ? 0 : Number(values.position),
    in_menu: values.in_menu,
    is_published: values.is_published,
    body: values.body,
  };
}

function PageForm({ page }: { page?: PageOut }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const creating = page === undefined;
  // While creating, the address follows the title until someone edits it.
  const [slugTouched, setSlugTouched] = useState(!creating);
  const form = useForm<FormValues>({
    initialValues: toForm(page),
    validate: {
      title: (value) => (value.trim() ? null : "Give the page a title"),
      slug: (value) =>
        /^[a-z0-9][a-z0-9-]{0,79}$/.test(value.trim())
          ? null
          : "Use lower-case letters, digits and hyphens, e.g. author-guidelines",
    },
  });

  const save = useMutation({
    mutationFn: (values: FormValues) =>
      page
        ? unwrap(
            api.PUT("/api/v1/site/pages/{page_id}", {
              params: { path: { page_id: page.id }, header: { "if-match": `"${page.row_version}"` } },
              body: toBody(values),
            }),
          )
        : unwrap(api.POST("/api/v1/site/pages", { body: toBody(values) })),
    onSuccess: (saved) => {
      queryClient.setQueryData(sitePageKey(saved.id), saved);
      queryClient.invalidateQueries({ queryKey: sitePagesKey, exact: true });
      if (creating) {
        notifySaved("Page created");
        navigate(`/site/pages/${saved.id}`, { replace: true });
      } else {
        form.resetDirty(toForm(saved));
        notifySaved("Page saved");
      }
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 412 && page) {
        notifications.show({
          color: "orange",
          title: "Someone else changed this page",
          message: "The latest version is loaded. Make your changes again.",
        });
        queryClient.invalidateQueries({ queryKey: sitePageKey(page.id) });
        return;
      }
      if (error instanceof ApiError && error.code === "slug_taken") {
        form.setFieldError("slug", "Another page already has this address");
        return;
      }
      showRequestError(error, form);
    },
  });

  const remove = useMutation({
    mutationFn: (id: number) =>
      unwrap(api.DELETE("/api/v1/site/pages/{page_id}", { params: { path: { page_id: id } } })),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: sitePagesKey });
      notifySaved("Page deleted");
      navigate("/site/pages");
    },
    onError: (error) => showRequestError(error),
  });

  const titleProps = form.getInputProps("title");
  return (
    <form onSubmit={form.onSubmit((values) => save.mutate(values))} noValidate>
      <Stack gap="lg">
        <Card withBorder padding="lg">
          <Stack>
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <TextInput
                label="Title"
                required
                {...titleProps}
                onChange={(event) => {
                  titleProps.onChange(event);
                  if (!slugTouched) form.setFieldValue("slug", slugify(event.currentTarget.value));
                }}
              />
              <TextInput
                label="Address"
                description={`The page's address on the site: /${form.values.slug || "slug"}`}
                required
                {...form.getInputProps("slug")}
                onChange={(event) => {
                  setSlugTouched(true);
                  form.setFieldValue("slug", event.currentTarget.value.toLowerCase());
                }}
              />
            </SimpleGrid>
            <Group gap="xl" align="flex-end">
              <NumberInput
                label="Order"
                description="Lower numbers come first in the menu."
                min={0}
                max={10000}
                allowDecimal={false}
                w={200}
                {...form.getInputProps("position")}
              />
              <Switch label="In the menu" {...form.getInputProps("in_menu", { type: "checkbox" })} />
              <Switch
                label="Published"
                description="Drafts are not shown on the site."
                {...form.getInputProps("is_published", { type: "checkbox" })}
              />
            </Group>
          </Stack>
        </Card>
        <Card withBorder padding="lg">
          <MarkdownField
            label="Text"
            value={form.values.body}
            onChange={(value) => form.setFieldValue("body", value)}
            error={form.errors.body as string | undefined}
            minRows={14}
          />
        </Card>
        <Group justify="space-between">
          {page ? (
            <Button
              variant="subtle"
              color="red"
              leftSection={<IconTrash size={16} />}
              loading={remove.isPending}
              onClick={() =>
                modals.openConfirmModal({
                  title: `Delete “${page.title}”?`,
                  children: "The page is removed from the site for good.",
                  labels: { confirm: "Delete", cancel: "Cancel" },
                  confirmProps: { color: "red" },
                  onConfirm: () => remove.mutate(page.id),
                })
              }
            >
              Delete
            </Button>
          ) : (
            <span />
          )}
          <Button type="submit" loading={save.isPending} disabled={!creating && !form.isDirty()}>
            {creating ? "Create page" : "Save"}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

/** Create a page (/site/pages/new) or edit one (/site/pages/:id). */
export function SitePageEditor() {
  const params = useParams();
  const creating = params.id === undefined || params.id === "new";
  const id = creating ? 0 : Number(params.id);
  const page = useSitePage(id, !creating);
  const back = (
    <Anchor component={Link} to="/site/pages" size="sm">
      ← All pages
    </Anchor>
  );
  if (creating) {
    return (
      <Stack>
        <PageHeader title="New page" description="A text for the journal's site." />
        {back}
        <PageForm />
      </Stack>
    );
  }
  if (!page.data) {
    return <QueryState isPending={page.isPending} error={page.error} onRetry={() => page.refetch()} />;
  }
  return (
    <Stack>
      <PageHeader
        title={page.data.title}
        description={
          <Group gap="xs">
            <Badge variant="light" color={page.data.is_published ? "green" : "gray"}>
              {page.data.is_published ? "Published" : "Draft"}
            </Badge>
          </Group>
        }
      />
      {back}
      <PageForm key={`${page.data.id}-${page.data.row_version}`} page={page.data} />
    </Stack>
  );
}
