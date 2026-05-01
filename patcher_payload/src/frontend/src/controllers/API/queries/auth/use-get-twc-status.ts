import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface TWCAuthStatusResponse {
  enabled: boolean;
  configured: boolean;
  authenticated: boolean;
  server_id?: string | null;
  server_label?: string | null;
  username?: string | null;
  external_user_id?: string | null;
  has_refresh_token?: boolean;
  expires_at?: string | null;
  current_user?: Record<string, unknown> | null;
  error?: string | null;
}

export const useGetTWCStatus: useQueryFunctionType<
  undefined,
  TWCAuthStatusResponse
> = (options) => {
  const { query } = UseRequestProcessor();

  const getTWCStatusFn = async () => {
    const response = await api.get<TWCAuthStatusResponse>(
      `${getURL("TWC_AUTH")}/status`,
    );
    return response.data;
  };

  return query(["useGetTWCStatus"], getTWCStatusFn, {
    refetchOnWindowFocus: false,
    retry: false,
    ...options,
  });
};
