import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface SSOConfigResponseType {
  provider: string;
  provider_name: string;
  enabled: boolean;
  enforce_sso: boolean;
  client_id: string | null;
  discovery_url: string | null;
  redirect_uri: string | null;
  scopes: string | null;
  token_endpoint: string | null;
  authorization_endpoint: string | null;
  jwks_uri: string | null;
  issuer: string | null;
  email_claim: string;
  username_claim: string;
  user_id_claim: string;
  has_client_secret: boolean;
  saml_entity_id: string | null;
  saml_acs_url: string | null;
  saml_idp_metadata_url: string | null;
  saml_idp_entity_id: string | null;
  saml_sso_url: string | null;
  saml_slo_url: string | null;
  saml_x509_cert: string | null;
  saml_nameid_format: string | null;
}

export const useGetSSOConfig: useQueryFunctionType<
  undefined,
  SSOConfigResponseType[]
> = (options) => {
  const { query } = UseRequestProcessor();

  const getSSOConfigFn = async () => {
    const response = await api.get<SSOConfigResponseType[]>(
      `${getURL("SSO")}/config`,
    );
    return response.data;
  };

  return query(["useGetSSOConfig"], getSSOConfigFn, {
    refetchOnWindowFocus: false,
    ...options,
  });
};
