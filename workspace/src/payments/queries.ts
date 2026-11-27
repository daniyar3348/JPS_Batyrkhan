import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "../api";

export const billingKey = (submissionId: number) => ["billing", submissionId] as const;
export const paymentSettingsKey = ["payment-settings"] as const;

export function useBilling(submissionId: number, enabled = true) {
  return useQuery({
    queryKey: billingKey(submissionId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/submissions/{submission_id}/billing", {
          params: { path: { submission_id: submissionId } },
        }),
      ),
    enabled,
  });
}

export function usePaymentSettings() {
  return useQuery({
    queryKey: paymentSettingsKey,
    queryFn: () => unwrap(api.GET("/api/v1/journal/payment-settings")),
  });
}
