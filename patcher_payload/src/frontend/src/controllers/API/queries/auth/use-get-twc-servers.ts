import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface TWCServerOption {
  id: string;
  label: string;
  rest_url: string;
  authorize_url: string;
  ready: boolean;
  error?: string | null;
}

export interface TWCServersResponse {
  enabled: boolean;
  single_server: boolean;
  default_server_id?: string | null;
  servers: TWCServerOption[];
}

export const useGetTWCServers: useQueryFunctionType<
  undefined,
  TWCServersResponse
> = (options) => {
  const { query } = UseRequestProcessor();

  const getTWCServersFn = async () => {
    const response = await api.get<TWCServersResponse>(
      `${getURL("TWC_AUTH")}/servers`,
    );
    return response.data;
  };

  return query(["useGetTWCServers"], getTWCServersFn, {
    refetchOnWindowFocus: false,
    retry: false,
    ...options,
  });
};
