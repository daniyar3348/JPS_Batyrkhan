import { notifications } from "@mantine/notifications";
import { ApiError, errorMessage } from "../api";

interface FormWithErrors {
  setErrors: (errors: Record<string, string>) => void;
}

/**
 * Show a failed request to the user: field errors next to the fields, anything else as a notification.
 * Field names from the server ("interests.0") are mapped to their top-level form field ("interests").
 */
export function showRequestError(error: unknown, form?: FormWithErrors): void {
  if (form && error instanceof ApiError && Object.keys(error.fieldErrors).length > 0) {
    const fieldErrors: Record<string, string> = {};
    for (const [field, message] of Object.entries(error.fieldErrors)) {
      const key = field.split(".")[0] ?? field;
      fieldErrors[key] ??= message.replace(/^Value error, /, "");
    }
    form.setErrors(fieldErrors);
    if (fieldErrors.request) {
      notifications.show({ color: "red", message: fieldErrors.request });
    }
    return;
  }
  notifications.show({ color: "red", title: "Could not complete the request", message: errorMessage(error) });
}

export function notifySaved(message = "Changes saved"): void {
  notifications.show({ color: "teal", message });
}

export const PASSWORD_MIN_LENGTH = 10;

export function validatePassword(value: string): string | null {
  if (value.length < PASSWORD_MIN_LENGTH) return `Use at least ${PASSWORD_MIN_LENGTH} characters`;
  if (value.length > 128) return "Use at most 128 characters";
  return null;
}

export function validateEmail(value: string): string | null {
  return /^\S+@\S+\.\S+$/.test(value.trim()) ? null : "Enter a valid e-mail address";
}
