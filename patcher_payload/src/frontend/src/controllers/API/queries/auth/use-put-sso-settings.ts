import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import type { SSOSettingsResponseType } from "./use-get-sso-settings";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface SSOSettingsUpdateRequest {
  sso_enabled: boolean;
}

export const usePutSSOSettings: useMutationFunctionType<
  undefined,
  SSOSettingsUpdateRequest,
  SSOSettingsResponseType
> = (options) => {
  const { mutate, queryClient } = UseRequestProcessor();

  async function putSSOSettings(
    requestData: SSOSettingsUpdateRequest,
  ): Promise<SSOSettingsResponseType> {
    const res = await api.put(`${getURL("ADMIN_SETTINGS")}/sso`, requestData);
    return res.data;
  }

  const mutation: UseMutationResult<
    SSOSettingsResponseType,
    any,
    SSOSettingsUpdateRequest
  > = mutate(["usePutSSOSettings"], putSSOSettings, {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["useGetSSOSettings"] });
      queryClient.invalidateQueries({ queryKey: ["useGetConfig"] });
      queryClient.invalidateQueries({ queryKey: ["useGetSSOConfig"] });
      queryClient.invalidateQueries({ queryKey: ["useGetSSOProviders"] });
    },
    ...options,
  });

  return mutation;
};
