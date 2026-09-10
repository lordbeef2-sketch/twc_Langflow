import type { useQueryFunctionType } from "@/types/api";
import type { SSOConfigResponseType } from "./use-get-sso-config";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export const useGetSSOProviders: useQueryFunctionType<
  undefined,
  SSOConfigResponseType[]
> = (options) => {
  const { query } = UseRequestProcessor();

  const getSSOProvidersFn = async () => {
    const response = await api.get<SSOConfigResponseType[]>(
      `${getURL("SSO")}/providers`,
    );
    return response.data;
  };

  return query(["useGetSSOProviders"], getSSOProvidersFn, {
    refetchOnWindowFocus: false,
    ...options,
  });
};