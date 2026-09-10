import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import type { HTTPSSettingsResponseType } from "./use-get-https-settings";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface HTTPSSettingsUpdateRequest {
  ssl_enabled: boolean;
  ssl_cert_file?: string;
  ssl_key_file?: string;
  host?: string;
  port?: number;
  https_hsts_enabled?: boolean;
  https_hsts_max_age?: number;
  https_hsts_include_subdomains?: boolean;
  https_hsts_preload?: boolean;
}

export const usePutHTTPSSettings: useMutationFunctionType<
  undefined,
  HTTPSSettingsUpdateRequest,
  HTTPSSettingsResponseType
> = (options) => {
  const { mutate, queryClient } = UseRequestProcessor();

  async function putHTTPSSettings(
    requestData: HTTPSSettingsUpdateRequest,
  ): Promise<HTTPSSettingsResponseType> {
    const res = await api.put(`${getURL("ADMIN_SETTINGS")}/https`, requestData);
    return res.data;
  }

  const mutation: UseMutationResult<
    HTTPSSettingsResponseType,
    any,
    HTTPSSettingsUpdateRequest
  > = mutate(["usePutHTTPSSettings"], putHTTPSSettings, {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["useGetHTTPSSettings"] });
    },
    ...options,
  });

  return mutation;
};
