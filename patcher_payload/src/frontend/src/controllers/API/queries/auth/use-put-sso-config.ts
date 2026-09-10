import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import type { SSOConfigResponseType } from "./use-get-sso-config";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface UpsertSSOConfigRequest {
  provider: "oauth" | "oidc" | "saml";
  provider_name: string;
  enabled: boolean;
  enforce_sso: boolean;
  client_id?: string;
  client_secret?: string;
  discovery_url?: string;
  redirect_uri?: string;
  scopes?: string;
  token_endpoint?: string;
  authorization_endpoint?: string;
  jwks_uri?: string;
  issuer?: string;
  saml_entity_id?: string;
  saml_acs_url?: string;
  saml_idp_metadata_url?: string;
  saml_idp_entity_id?: string;
  saml_sso_url?: string;
  saml_slo_url?: string;
  saml_x509_cert?: string;
  saml_nameid_format?: string;
  email_claim: string;
  username_claim: string;
  user_id_claim: string;
}

export const usePutSSOConfig: useMutationFunctionType<
  undefined,
  UpsertSSOConfigRequest,
  SSOConfigResponseType
> = (options) => {
  const { mutate, queryClient } = UseRequestProcessor();

  async function putSSOConfig(
    requestData: UpsertSSOConfigRequest,
  ): Promise<SSOConfigResponseType> {
    const res = await api.put(`${getURL("SSO")}/config`, requestData);
    return res.data;
  }

  const mutation: UseMutationResult<
    SSOConfigResponseType,
    any,
    UpsertSSOConfigRequest
  > = mutate(["usePutSSOConfig"], putSSOConfig, {
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["useGetSSOConfig"] });
      queryClient.invalidateQueries({ queryKey: ["useGetSSOProviders"] });
    },
    ...options,
  });

  return mutation;
};
