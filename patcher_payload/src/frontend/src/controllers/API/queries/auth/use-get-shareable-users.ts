import type { UseQueryOptions } from "@tanstack/react-query";
import type { useQueryFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export type ShareableUserType = {
  id: string;
  username: string;
  profile_image?: string | null;
};

interface GetShareableUsersParams {
  search?: string;
  limit?: number;
}

export const useGetShareableUsersQuery: useQueryFunctionType<
  GetShareableUsersParams,
  ShareableUserType[]
> = (params, options) => {
  const { query } = UseRequestProcessor();

  const getShareableUsersFn = async (
    queryParams: GetShareableUsersParams,
  ): Promise<ShareableUserType[]> => {
    const search = queryParams.search?.trim();
    const limit = queryParams.limit ?? 20;
    const queryString = new URLSearchParams({
      limit: String(limit),
      ...(search ? { search } : {}),
    });

    const response = await api.get<ShareableUserType[]>(
      `${getURL("USERS")}/shareable?${queryString.toString()}`,
    );
    return response.data;
  };

  return query(
    ["useGetShareableUsersQuery", params],
    () => getShareableUsersFn(params ?? {}),
    options as UseQueryOptions,
  );
};
