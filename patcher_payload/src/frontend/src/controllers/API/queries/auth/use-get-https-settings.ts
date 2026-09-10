import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface HTTPSSettingsResponseType {
  ssl_enabled: boolean;
  ssl_cert_file: string | null;
  ssl_key_file: string | null;
  host: string;
  port: number;
  access_secure_cookie: boolean;
  refresh_secure_cookie: boolean;
  https_hsts_enabled: boolean;
  https_hsts_max_age: number;
  https_hsts_include_subdomains: boolean;
  https_hsts_preload: boolean;
  restart_required: boolean;
}

export const useGetHTTPSSettings: useQueryFunctionType<
  undefined,
  HTTPSSettingsResponseType
> = (options) => {
  const { query } = UseRequestProcessor();

  const getHTTPSSettingsFn = async () => {
    const response = await api.get<HTTPSSettingsResponseType>(
      `${getURL("ADMIN_SETTINGS")}/https`,
    );
    return response.data;
  };

  return query(["useGetHTTPSSettings"], getHTTPSSettingsFn, {
    refetchOnWindowFocus: false,
    ...options,
  });
};
