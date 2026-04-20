import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export interface SAMLMetadataResponseType {
  provider_name: string;
  metadata_xml: string;
}

export const useGetSAMLMetadata: useQueryFunctionType<
  { providerName: string },
  SAMLMetadataResponseType
> = ({ providerName }, options) => {
  const { query } = UseRequestProcessor();

  const getSAMLMetadataFn = async () => {
    const response = await api.get<SAMLMetadataResponseType>(
      `${getURL("SSO")}/config/${encodeURIComponent(providerName)}/saml/metadata`,
    );
    return response.data;
  };

  return query(["useGetSAMLMetadata", providerName], getSAMLMetadataFn, {
    refetchOnWindowFocus: false,
    ...options,
  });
};
