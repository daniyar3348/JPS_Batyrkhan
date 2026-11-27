import { Badge, createTheme } from "@mantine/core";

export const theme = createTheme({
  primaryColor: "indigo",
  defaultRadius: "md",
  fontFamily:
    "Inter, system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans', sans-serif",
  headings: { fontWeight: "650" },
  components: {
    // Status badges are short; in narrow table columns they must keep their width, not end in "…".
    Badge: Badge.extend({ styles: { root: { minWidth: "max-content" } } }),
  },
});
