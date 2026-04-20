import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface SSOSettingsResponseType {
  sso_enabled: boolean;
}

export const useGetSSOSettings: useQueryFunctionType<
  undefined,
  SSOSettingsResponseType
> = (options) => {
  const { query } = UseRequestProcessor();

  const getSSOSettingsFn = async () => {
    const response = await api.get<SSOSettingsResponseType>(
      `${getURL("ADMIN_SETTINGS")}/sso`,
    );
    return response.data;
  };

  return query(["useGetSSOSettings"], getSSOSettingsFn, {
    refetchOnWindowFocus: false,
    ...options,
  });
};
