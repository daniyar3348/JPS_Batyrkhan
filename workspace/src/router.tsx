import type { Capability } from "@jps/api-client";
import { createBrowserRouter } from "react-router";
import { AppLayout } from "./components/AppLayout";
import { AuthLayout } from "./components/AuthLayout";
import { CapabilityOutlet, RequireAuth } from "./components/guards";
import { ForgotPasswordPage } from "./pages/auth/ForgotPasswordPage";
import { LoginPage } from "./pages/auth/LoginPage";
import { RegisterPage } from "./pages/auth/RegisterPage";
import { AcceptInvitationPage, ResetPasswordPage } from "./pages/auth/ResetPasswordPage";
import { VerifyEmailPage } from "./pages/auth/VerifyEmailPage";
import { DashboardPage } from "./pages/DashboardPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { ProfilePage } from "./pages/ProfilePage";

const requires = (capability: Capability) => ({ capability });

export const router = createBrowserRouter([
  {
    element: <AuthLayout />,
    children: [
      { path: "/login", element: <LoginPage /> },
      { path: "/register", element: <RegisterPage /> },
      { path: "/forgot-password", element: <ForgotPasswordPage /> },
      { path: "/reset-password", element: <ResetPasswordPage /> },
      { path: "/accept-invitation", element: <AcceptInvitationPage /> },
      { path: "/verify-email", element: <VerifyEmailPage /> },
    ],
  },
  {
    path: "/",
    element: (
      <RequireAuth>
        <AppLayout />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <DashboardPage /> },
      { path: "profile", element: <ProfilePage /> },
      // Submission pages are loaded on demand (the wizard brings its own components).
      {
        path: "submissions",
        lazy: async () => ({
          Component: (await import("./submissions/MySubmissionsPage")).MySubmissionsPage,
        }),
      },
      {
        path: "submissions/new",
        lazy: async () => ({
          Component: (await import("./submissions/NewSubmissionPage")).NewSubmissionPage,
        }),
      },
      {
        path: "submissions/:id",
        lazy: async () => ({
          Component: (await import("./submissions/SubmissionDetailPage")).SubmissionDetailPage,
        }),
      },
      {
        path: "submissions/:id/edit",
        lazy: async () => ({
          Component: (await import("./submissions/SubmissionWizardPage")).SubmissionWizardPage,
        }),
      },
      {
        path: "reviews",
        lazy: async () => ({ Component: (await import("./reviews/MyReviewsPage")).MyReviewsPage }),
      },
      {
        path: "reviews/:id",
        lazy: async () => ({ Component: (await import("./reviews/ReviewPage")).ReviewPage }),
      },
      {
        path: "payments/return",
        lazy: async () => ({ Component: (await import("./payments/PaymentReturnPage")).PaymentReturnPage }),
      },
      {
        // Finance managers only: invoices, payments, refunds, waiver requests.
        path: "finance",
        element: <CapabilityOutlet />,
        children: [
          {
            index: true,
            handle: requires("payments.manage"),
            lazy: async () => ({ Component: (await import("./finance/InvoicesPage")).InvoicesPage }),
          },
          {
            path: "invoices/:id",
            handle: requires("payments.manage"),
            lazy: async () => ({ Component: (await import("./finance/InvoicePage")).InvoicePage }),
          },
          {
            path: "waivers",
            handle: requires("payments.manage"),
            lazy: async () => ({ Component: (await import("./finance/WaiversPage")).WaiversPage }),
          },
          {
            path: "settings",
            handle: requires("payments.manage"),
            lazy: async () => ({
              Component: (await import("./finance/PaymentSettingsPage")).PaymentSettingsPage,
            }),
          },
        ],
      },
      {
        path: "production",
        lazy: async () => ({
          Component: (await import("./production/ProductionWorkPage")).ProductionWorkPage,
        }),
      },
      {
        // Issues: listed to the editors; created, published and set up by those with publishing.manage.
        path: "publishing",
        children: [
          {
            path: "issues",
            lazy: async () => ({ Component: (await import("./publishing/IssuesPage")).IssuesPage }),
          },
          {
            path: "issues/:id",
            lazy: async () => ({ Component: (await import("./publishing/IssuePage")).IssuePage }),
          },
          {
            element: <CapabilityOutlet />,
            children: [
              {
                path: "settings",
                handle: requires("publishing.manage"),
                lazy: async () => ({
                  Component: (await import("./publishing/PublishingSettingsPage")).PublishingSettingsPage,
                }),
              },
              {
                path: "doi",
                handle: requires("publishing.manage"),
                lazy: async () => ({
                  Component: (await import("./publishing/DoiDepositsPage")).DoiDepositsPage,
                }),
              },
            ],
          },
        ],
      },
      {
        path: "editorial",
        lazy: async () => ({
          Component: (await import("./submissions/EditorialQueuePage")).EditorialQueuePage,
        }),
      },
      {
        // Administration pages are loaded on demand, so most users never download them.
        path: "admin",
        element: <CapabilityOutlet />,
        children: [
          {
            path: "journal",
            handle: requires("journal.settings.edit"),
            lazy: async () => ({
              Component: (await import("./pages/admin/JournalSettingsPage")).JournalSettingsPage,
            }),
          },
          {
            path: "submission-settings",
            handle: requires("journal.settings.edit"),
            lazy: async () => ({
              Component: (await import("./pages/admin/SubmissionSettingsPage")).SubmissionSettingsPage,
            }),
          },
          {
            path: "review-settings",
            handle: requires("journal.settings.edit"),
            lazy: async () => ({
              Component: (await import("./pages/admin/ReviewSettingsPage")).ReviewSettingsPage,
            }),
          },
          {
            path: "review-forms",
            handle: requires("journal.settings.edit"),
            lazy: async () => ({
              Component: (await import("./pages/admin/ReviewFormsPage")).ReviewFormsPage,
            }),
          },
          {
            path: "email-templates",
            handle: requires("journal.settings.edit"),
            lazy: async () => ({
              Component: (await import("./pages/admin/EmailTemplatesPage")).EmailTemplatesPage,
            }),
          },
          {
            path: "sections",
            handle: requires("sections.manage"),
            lazy: async () => ({ Component: (await import("./pages/admin/SectionsPage")).SectionsPage }),
          },
          {
            path: "users",
            handle: requires("users.view"),
            lazy: async () => ({ Component: (await import("./pages/admin/UsersPage")).UsersPage }),
          },
          {
            path: "audit",
            handle: requires("audit.view"),
            lazy: async () => ({ Component: (await import("./pages/admin/AuditLogPage")).AuditLogPage }),
          },
        ],
      },
    ],
  },
  { path: "*", element: <NotFoundPage /> },
]);
